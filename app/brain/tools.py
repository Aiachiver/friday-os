"""
Tool registry: defines what the AI brain is allowed to *do*, not just
say. Each tool has a JSON-schema spec (sent to the LLM so it knows the
tool exists and how to call it) and a handler (the real Python function
that actually runs).

Tools whose `requires_confirmation` evaluates to True for a given call
are never executed directly by `execute()` — the orchestrator
intercepts them first, asks the user to confirm out loud, and only
calls `execute()` for real after a "yes" (see
Orchestrator._ask_for_confirmation / _resolve_pending_confirmation in
app/core/orchestrator.py). This is the single choke point for the
spec's "delete files only after confirmation" / "form filling with user
approval" requirements, so every destructive tool gets that guarantee
for free just by being registered here correctly, rather than each
automation module reimplementing its own confirmation logic.

`requires_confirmation` can be either a plain `bool` (always/never
needs confirmation) or a `Callable[[dict], bool]` predicate evaluated
against the actual call arguments — e.g. write_file_content only needs
confirmation when the caller is actually asking to overwrite an
existing file (`overwrite=True`), not on every write; a blanket
`requires_confirmation=True` there would mean the common, safe case of
saving newly-generated code needs an unnecessary confirmation step
every single time, which was a real bug caught by an integration test
before it ever shipped.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.automation.browser.browser_controller import BrowserController
from app.automation.desktop import (
    clipboard_manager,
    file_manager,
    screenshot,
    startup_manager,
    system_control,
)
from app.brain.memory.memory_manager import MemoryManager
from app.brain.providers.base import ToolSpec
from app.brain.router import ProviderRouter
from app.coding import git_tools, github_tools, project_templates
from app.finance import alert_service, analysis, charts, news_sentiment, portfolio_service
from app.finance.providers import market_data
from app.productivity import productivity_service
from app.research import wikipedia_tools
from app.utils.logger import get_logger
from app.vision import image_understanding, ocr, pdf_extractor, screen_analysis

log = get_logger(__name__)

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]
ConfirmationCheck = bool | Callable[[dict[str, Any]], bool]


@dataclass(slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler
    requires_confirmation: ConfirmationCheck = False


class ToolRegistry:
    def __init__(self, memory: MemoryManager, browser: BrowserController, provider_router: ProviderRouter) -> None:
        self._memory = memory
        self._browser = browser
        self._provider_router = provider_router
        self._tools: dict[str, RegisteredTool] = {}
        self._plugin_owned_tools: dict[str, set[str]] = {}
        self._register_all()

    # --- vision tool wrappers ------------------------------------------------
    # describe_image and analyze_screen need `provider_router` injected --
    # that's an app-internal dependency, not something the LLM should ever
    # supply as a tool argument. Real bound async methods (not a lambda
    # wrapping a coroutine call) are required here: execute() detects
    # coroutine functions via inspect.iscoroutinefunction() to decide
    # whether to await directly or run in a thread pool, and a lambda
    # wrapping an async call is itself a *sync* function that would return
    # an un-awaited, never-run coroutine object if dispatched through the
    # thread-pool path.

    async def _tool_describe_image(self, image_path: str, question: str | None = None) -> dict[str, Any]:
        return await image_understanding.describe_image(image_path, question, self._provider_router)

    async def _tool_analyze_screen(self, mode: str = "describe", question: str | None = None) -> dict[str, Any]:
        return await screen_analysis.analyze_screen(mode, question, self._provider_router)

    # --- registration -------------------------------------------------------

    def _register(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        requires_confirmation: ConfirmationCheck = False,
    ) -> None:
        self._tools[name] = RegisteredTool(
            spec=ToolSpec(name=name, description=description, parameters=parameters),
            handler=handler,
            requires_confirmation=requires_confirmation,
        )

    def _register_all(self) -> None:
        # --- file management ---
        self._register(
            "search_files",
            "Search for files or folders by name under a given root directory.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Filename substring or glob pattern, e.g. '*.pdf'"},
                    "root": {
                        "type": "string",
                        "description": "Directory to search under, e.g. 'C:\\\\Users\\\\Suraj\\\\Documents'",
                    },
                },
                "required": ["query", "root"],
            },
            file_manager.search_files,
        )
        self._register(
            "move_file",
            "Move a file or folder to a new location.",
            {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            },
            file_manager.move_file,
        )
        self._register(
            "rename_file",
            "Rename a file or folder in place.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_name": {"type": "string", "description": "New filename only, no path separators."},
                },
                "required": ["path", "new_name"],
            },
            file_manager.rename_file,
        )
        self._register(
            "create_folder",
            "Create a new folder (and any missing parent folders).",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            file_manager.create_folder,
        )
        self._register(
            "delete_file",
            "Delete a file or folder. Sends it to the recycle bin by default (recoverable).",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "permanent": {
                        "type": "boolean",
                        "description": (
                            "If true, bypasses the recycle bin permanently. " "Requires explicit user confirmation."
                        ),
                        "default": False,
                    },
                },
                "required": ["path"],
            },
            file_manager.delete_file,
            requires_confirmation=True,
        )
        self._register(
            "read_file_content",
            "Read a text file's contents (e.g. to explain, debug, or review code or any other text file).",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            file_manager.read_file_content,
        )
        self._register(
            "write_file_content",
            "Write text to a file, creating parent folders as needed. Used to save "
            "AI-generated code or any other text content to disk.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {
                        "type": "boolean",
                        "description": "If true, replaces an existing file. Requires explicit user confirmation.",
                        "default": False,
                    },
                },
                "required": ["path", "content"],
            },
            file_manager.write_file_content,
            requires_confirmation=lambda args: bool(args.get("overwrite", False)),
        )

        # --- system control ---
        self._register(
            "open_application",
            "Launch an application by name, e.g. 'notepad', 'chrome', 'code'.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            system_control.open_application,
        )
        self._register(
            "close_application",
            "Close all running processes matching a name.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            system_control.close_application,
        )
        self._register(
            "list_running_processes",
            "List currently running processes sorted by memory usage.",
            {"type": "object", "properties": {}},
            system_control.list_running_processes,
        )
        self._register(
            "set_volume",
            "Set the system master volume.",
            {
                "type": "object",
                "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
                "required": ["percent"],
            },
            system_control.set_volume,
        )
        self._register(
            "set_brightness",
            "Set the screen brightness.",
            {
                "type": "object",
                "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
                "required": ["percent"],
            },
            system_control.set_brightness,
        )
        self._register(
            "lock_pc",
            "Lock the computer immediately.",
            {"type": "object", "properties": {}},
            system_control.lock_pc,
        )
        self._register(
            "sleep_pc",
            "Put the computer to sleep.",
            {"type": "object", "properties": {}},
            system_control.sleep_pc,
            requires_confirmation=True,
        )
        self._register(
            "shutdown_pc",
            "Shut down the computer after a delay.",
            {"type": "object", "properties": {"delay_seconds": {"type": "integer", "default": 10}}},
            system_control.shutdown_pc,
            requires_confirmation=True,
        )
        self._register(
            "restart_pc",
            "Restart the computer after a delay.",
            {"type": "object", "properties": {"delay_seconds": {"type": "integer", "default": 10}}},
            system_control.restart_pc,
            requires_confirmation=True,
        )
        self._register(
            "enable_startup_on_boot",
            "Make FRIDAY launch automatically when Windows starts.",
            {"type": "object", "properties": {}},
            startup_manager.enable_startup,
        )
        self._register(
            "disable_startup_on_boot",
            "Stop FRIDAY from launching automatically when Windows starts.",
            {"type": "object", "properties": {}},
            startup_manager.disable_startup,
        )
        self._register(
            "check_startup_on_boot",
            "Check whether FRIDAY is currently set to launch automatically when Windows starts.",
            {"type": "object", "properties": {}},
            lambda: {"success": True, "enabled": startup_manager.is_enabled()},
        )

        # --- clipboard / screenshot ---
        self._register(
            "get_clipboard_text",
            "Read the current clipboard contents.",
            {"type": "object", "properties": {}},
            clipboard_manager.get_clipboard_text,
        )
        self._register(
            "set_clipboard_text",
            "Write text to the clipboard.",
            {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            clipboard_manager.set_clipboard_text,
        )
        self._register(
            "take_screenshot",
            "Capture a screenshot of the full screen and save it to disk.",
            {"type": "object", "properties": {}},
            screenshot.take_screenshot,
        )

        # --- browser ---
        self._register(
            "browser_navigate",
            "Open a URL in the browser.",
            {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            self._browser.navigate,
        )
        self._register(
            "browser_search",
            "Search Google, YouTube, or GitHub in the browser.",
            {
                "type": "object",
                "properties": {
                    "site": {"type": "string", "enum": ["google", "youtube", "github"]},
                    "query": {"type": "string"},
                },
                "required": ["site", "query"],
            },
            self._browser.search,
        )
        self._register(
            "browser_read_page",
            "Read the visible text of the currently open browser page.",
            {"type": "object", "properties": {}},
            self._browser.get_page_text,
        )

        # --- finance: market data & analysis ---
        self._register(
            "get_stock_price",
            "Get the current price and basic stats for a stock, crypto, forex, or commodity symbol. "
            "Use Yahoo Finance ticker conventions: US stocks like 'AAPL', Indian stocks like "
            "'RELIANCE.NS' or 'TCS.NS' (NSE) / 'INFY.BO' (BSE), crypto like 'BTC-USD', "
            "forex like 'EURUSD=X', gold like 'GC=F'.",
            {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
            market_data.get_quote,
        )
        self._register(
            "analyze_stock",
            "Run technical analysis on a symbol: RSI, MACD, moving averages, Bollinger Bands, ATR, "
            "VWAP, support/resistance, and trend direction. This is historical/statistical analysis, "
            "never a guaranteed prediction.",
            {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "period": {
                        "type": "string",
                        "enum": ["1mo", "3mo", "6mo", "1y", "2y"],
                        "default": "3mo",
                    },
                },
                "required": ["symbol"],
            },
            analysis.analyze_symbol,
        )
        self._register(
            "get_price_chart",
            "Generate and save a candlestick chart with moving averages for a symbol. Returns a file path.",
            {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "period": {
                        "type": "string",
                        "enum": ["1mo", "3mo", "6mo", "1y", "2y"],
                        "default": "3mo",
                    },
                },
                "required": ["symbol"],
            },
            charts.get_chart_for_symbol,
        )
        self._register(
            "get_news_sentiment",
            "Get recent news headlines for a symbol with sentiment scoring (positive/negative/neutral).",
            {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
            news_sentiment.get_news_sentiment,
        )

        # --- finance: portfolio ---
        self._register(
            "add_portfolio_holding",
            "Record a purchase in the user's portfolio (adds to an existing position with "
            "quantity-weighted average cost if the symbol is already held).",
            {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "asset_class": {"type": "string", "enum": ["stock", "crypto", "forex", "commodity"]},
                    "quantity": {"type": "number"},
                    "price_paid": {"type": "number", "description": "Price per unit paid"},
                },
                "required": ["symbol", "asset_class", "quantity", "price_paid"],
            },
            portfolio_service.add_holding,
        )
        self._register(
            "remove_portfolio_holding",
            "Remove a holding from the portfolio entirely, or reduce its quantity (partial sell).",
            {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "quantity": {"type": "number", "description": "Omit to remove the entire position"},
                },
                "required": ["symbol"],
            },
            portfolio_service.remove_holding,
        )
        self._register(
            "get_portfolio_summary",
            "Get the user's full portfolio with live prices, current value, and unrealized profit/loss.",
            {"type": "object", "properties": {}},
            portfolio_service.get_portfolio_summary,
        )

        # --- finance: price alerts ---
        self._register(
            "set_price_alert",
            "Set an alert that notifies the user when a symbol's price crosses a target.",
            {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "condition": {"type": "string", "enum": ["above", "below"]},
                    "target_price": {"type": "number"},
                },
                "required": ["symbol", "condition", "target_price"],
            },
            alert_service.add_alert,
        )
        self._register(
            "list_price_alerts",
            "List all currently active (not yet triggered) price alerts.",
            {"type": "object", "properties": {}},
            alert_service.list_active_alerts,
        )

        # --- vision ---
        self._register(
            "ocr_image",
            "Extract exact text from an image file using OCR. Use this for reading text precisely "
            "(error messages, documents, signs) rather than describe_image, which paraphrases.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the image file"},
                },
                "required": ["path"],
            },
            ocr.extract_text_from_image,
        )
        self._register(
            "describe_image",
            "Use AI vision to describe an image, answer a question about it, or identify objects/people/"
            "scenes in it. Use this for understanding content and meaning, not for extracting exact text "
            "(use ocr_image for that).",
            {
                "type": "object",
                "properties": {
                    "image_path": {"type": "string"},
                    "question": {
                        "type": "string",
                        "description": "What to ask about the image. Omit for a general description.",
                    },
                },
                "required": ["image_path"],
            },
            self._tool_describe_image,
        )
        self._register(
            "analyze_screen",
            "Take a screenshot of the current screen and either OCR it (mode='ocr', for exact text) "
            "or have AI describe/answer questions about what's currently displayed (mode='describe').",
            {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["ocr", "describe"], "default": "describe"},
                    "question": {
                        "type": "string",
                        "description": "Only used with mode='describe'. What to ask about the screen.",
                    },
                },
            },
            self._tool_analyze_screen,
        )
        self._register(
            "extract_pdf_text",
            "Extract all text from a PDF. Uses the PDF's native text layer where available, and OCR "
            "automatically for any scanned/image-only pages.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            pdf_extractor.extract_text_from_pdf,
        )
        self._register(
            "extract_pdf_images",
            "Extract and save embedded images (photos/figures) from a PDF to disk.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            pdf_extractor.extract_images_from_pdf,
        )

        # --- coding assistant: project templates & git/github ---
        self._register(
            "create_project_from_template",
            "Scaffold a new software project (python-cli, fastapi, or react) with real, "
            "runnable starter files, including tests.",
            {
                "type": "object",
                "properties": {
                    "template": {"type": "string", "enum": ["python-cli", "fastapi", "react"]},
                    "project_name": {"type": "string"},
                    "target_dir": {
                        "type": "string",
                        "description": "Directory the project folder will be created inside.",
                    },
                },
                "required": ["template", "project_name", "target_dir"],
            },
            project_templates.create_project_from_template,
        )
        self._register(
            "git_init",
            "Initialize a new git repository in a directory.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            git_tools.git_init,
        )
        self._register(
            "git_status",
            "Show the working tree status of a git repository (current branch, changed files).",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            git_tools.git_status,
        )
        self._register(
            "git_commit",
            "Stage all changes and commit them in a git repository.",
            {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "message": {"type": "string"},
                },
                "required": ["path", "message"],
            },
            git_tools.git_add_commit,
        )
        self._register(
            "git_current_branch",
            "Get the name of the current git branch in a repository.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            git_tools.git_current_branch,
        )

        # --- productivity: notes & reminders ---
        self._register(
            "add_note",
            "Save a note with a title and content for later reference.",
            {
                "type": "object",
                "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
                "required": ["title", "content"],
            },
            productivity_service.add_note,
        )
        self._register(
            "list_notes",
            "List saved notes, most recent first.",
            {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}},
            productivity_service.list_notes,
        )
        self._register(
            "add_reminder",
            "Set a reminder for a specific date and time. Compute due_at_iso yourself "
            "(use get_current_datetime plus the requested offset, e.g. 'in 20 minutes') — "
            "pass a real ISO 8601 datetime, not a natural-language phrase.",
            {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "due_at_iso": {"type": "string", "description": "ISO 8601, e.g. '2026-07-27T15:30:00'"},
                },
                "required": ["text", "due_at_iso"],
            },
            productivity_service.add_reminder,
        )
        self._register(
            "list_reminders",
            "List pending (not yet due or completed) reminders.",
            {"type": "object", "properties": {}},
            productivity_service.list_reminders,
        )
        self._register(
            "complete_reminder",
            "Mark a reminder as completed so it won't fire.",
            {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]},
            productivity_service.complete_reminder,
        )
        self._register(
            "create_github_repo",
            "Create a new repository on GitHub for the authenticated account.",
            {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "private": {"type": "boolean", "default": True},
                    "description": {"type": "string", "default": ""},
                },
                "required": ["name"],
            },
            github_tools.create_github_repo,
        )

        # --- research: wikipedia ---
        self._register(
            "search_wikipedia",
            "Search Wikipedia for articles matching a topic. Returns titles and short "
            "excerpts — use get_wikipedia_summary with the exact title from these results "
            "to read more.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            wikipedia_tools.search_wikipedia,
        )
        self._register(
            "get_wikipedia_summary",
            "Get the summary of a specific Wikipedia article by its exact title. "
            "Use search_wikipedia first if you're not sure of the exact title.",
            {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]},
            wikipedia_tools.get_wikipedia_summary,
        )

        # --- memory ---
        self._register(
            "remember_fact",
            "Save a fact about the user for future conversations "
            "(preference, project, habit, goal, folder location, etc.).",
            {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["project", "habit", "folder", "preference", "goal", "misc"],
                    },
                    "key": {"type": "string", "description": "Short label for the fact, e.g. 'favorite_editor'"},
                    "value": {"type": "string"},
                },
                "required": ["category", "key", "value"],
            },
            self._memory.remember_fact,
        )
        self._register(
            "forget_fact",
            "Delete a previously remembered fact.",
            {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "key": {"type": "string"},
                },
                "required": ["category", "key"],
            },
            self._memory.forget_fact,
        )
        self._register(
            "get_current_datetime",
            "Get the current date and time.",
            {"type": "object", "properties": {}},
            lambda: {"success": True, "datetime": datetime.now().isoformat()},
        )

    # --- plugin tool registration --------------------------------------------
    # Public surface used by PluginManager (app/plugins/registry.py). Kept
    # separate from the built-in _register() calls above so a plugin can
    # never silently shadow a core tool by registering the same name —
    # that's the difference between "extends the assistant" and "corrupts
    # it," and it's worth a real guard rather than trusting plugin authors
    # to pick unique names.

    def register_external_tool(
        self,
        plugin_name: str,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        requires_confirmation: ConfirmationCheck = False,
    ) -> None:
        if name in self._tools:
            raise ValueError(
                f"Plugin '{plugin_name}' tried to register tool '{name}', which already "
                "exists (either a built-in tool or another plugin registered it first). "
                "Tool names must be unique — rename the tool in the plugin."
            )
        self._register(name, description, parameters, handler, requires_confirmation)
        self._plugin_owned_tools.setdefault(plugin_name, set()).add(name)
        log.info("Plugin '{}' registered tool '{}'", plugin_name, name)

    def unregister_plugin_tools(self, plugin_name: str) -> None:
        """Called when a plugin is disabled or fails to load partway
        through — removes only the tools that plugin actually registered,
        leaving everything else (built-ins, other plugins) untouched."""
        for tool_name in self._plugin_owned_tools.pop(plugin_name, set()):
            self._tools.pop(tool_name, None)
        log.info("Unregistered all tools owned by plugin '{}'", plugin_name)

    # --- access for the router/orchestrator --------------------------------

    def get_specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def requires_confirmation(self, name: str, arguments: dict[str, Any] | None = None) -> bool:
        tool = self._tools.get(name)
        if tool is None:
            return False
        check = tool.requires_confirmation
        if callable(check):
            return check(arguments or {})
        return check

    def exists(self, name: str) -> bool:
        return name in self._tools

    async def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"success": False, "error": f"Unknown tool '{name}'"}

        log.info("Executing tool {} with args {}", name, arguments)
        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await tool.handler(**arguments)
            else:
                # Blocking calls (file I/O, subprocess, psutil) must not
                # freeze the asyncio loop / GUI thread.
                result = await asyncio.to_thread(tool.handler, **arguments)
        except TypeError as exc:
            log.warning("Tool {} called with bad arguments {}: {}", name, arguments, exc)
            return {"success": False, "error": f"Invalid arguments for {name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 — a broken tool must not crash the conversation
            log.exception("Tool {} raised an unexpected error", name)
            return {"success": False, "error": str(exc)}

        if not isinstance(result, dict):
            result = {"success": True, "result": result}
        return result
