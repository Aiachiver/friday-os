import pytest

from app.automation.browser.browser_controller import BrowserController
from app.brain.tools import ToolRegistry


class FakeMemory:
    def __init__(self):
        self.remembered = []

    def remember_fact(self, category: str, key: str, value: str) -> dict:
        self.remembered.append((category, key, value))
        return {"success": True}

    def forget_fact(self, category: str, key: str) -> dict:
        return {"success": True}


class FakeProviderRouter:
    """Vision tools (describe_image, analyze_screen) need a provider_router
    but these tests never exercise those specific tools, so a router that
    would raise if actually called is sufficient — it proves nothing here
    accidentally makes a real network call."""

    async def complete(self, messages, tools=None, temperature=0.6):
        raise AssertionError("FakeProviderRouter.complete() should not be called in these tests")

    @property
    def active_providers(self):
        return ["fake"]


@pytest.fixture
def registry():
    # BrowserController is never actually launched in these tests — its
    # methods are only referenced (as tool handlers), never called for
    # tools that aren't exercised here.
    return ToolRegistry(memory=FakeMemory(), browser=BrowserController(), provider_router=FakeProviderRouter())


def test_all_expected_tools_are_registered_exactly(registry):
    """Exhaustive equality, not issubset — a tool that exists in the
    codebase but was never wired into _register_all() (like
    git_current_branch was, until it got caught and fixed) wouldn't fail
    an issubset check, since issubset only complains about *missing*
    expected entries, never about *extra* undocumented ones. This list
    is the full, verified-true set as of the last audit — when you add a
    tool, add it here too; that's the point."""
    names = {spec.name for spec in registry.get_specs()}
    expected = {
        "search_files",
        "move_file",
        "rename_file",
        "create_folder",
        "delete_file",
        "read_file_content",
        "write_file_content",
        "open_application",
        "close_application",
        "list_running_processes",
        "set_volume",
        "set_brightness",
        "lock_pc",
        "sleep_pc",
        "shutdown_pc",
        "restart_pc",
        "enable_startup_on_boot",
        "disable_startup_on_boot",
        "check_startup_on_boot",
        "get_clipboard_text",
        "set_clipboard_text",
        "take_screenshot",
        "browser_navigate",
        "browser_search",
        "browser_read_page",
        "remember_fact",
        "forget_fact",
        "get_current_datetime",
        "get_stock_price",
        "analyze_stock",
        "get_price_chart",
        "get_news_sentiment",
        "add_portfolio_holding",
        "remove_portfolio_holding",
        "get_portfolio_summary",
        "set_price_alert",
        "list_price_alerts",
        "ocr_image",
        "describe_image",
        "analyze_screen",
        "extract_pdf_text",
        "extract_pdf_images",
        "create_project_from_template",
        "git_init",
        "git_status",
        "git_commit",
        "git_current_branch",
        "create_github_repo",
        "search_wikipedia",
        "get_wikipedia_summary",
        "add_note",
        "list_notes",
        "add_reminder",
        "list_reminders",
        "complete_reminder",
    }
    assert names == expected


def test_destructive_tools_require_confirmation(registry):
    for name in ("delete_file", "shutdown_pc", "restart_pc", "sleep_pc"):
        assert registry.requires_confirmation(name) is True


def test_safe_tools_do_not_require_confirmation(registry):
    for name in ("get_current_datetime", "get_clipboard_text", "search_files", "open_application"):
        assert registry.requires_confirmation(name) is False


def test_unknown_tool_requires_confirmation_defaults_false(registry):
    assert registry.requires_confirmation("not_a_real_tool") is False


def test_write_file_content_only_requires_confirmation_when_overwriting(registry):
    """Regression test for a real bug: write_file_content was originally
    registered with a blanket requires_confirmation=True, meaning even
    creating a brand-new file (the common, safe case for saving
    AI-generated code) triggered an unnecessary confirmation prompt
    every time. Caught by tests/integration/test_full_conversation_flow.py,
    fixed with a predicate evaluated against the actual call arguments."""
    assert registry.requires_confirmation("write_file_content", {"path": "x.py", "content": "..."}) is False
    assert (
        registry.requires_confirmation("write_file_content", {"path": "x.py", "content": "...", "overwrite": False})
        is False
    )
    assert (
        registry.requires_confirmation("write_file_content", {"path": "x.py", "content": "...", "overwrite": True})
        is True
    )


def test_requires_confirmation_with_no_arguments_defaults_predicate_to_false(registry):
    """Calling requires_confirmation() with no arguments dict at all
    (e.g. just checking a tool's general shape, not a specific call)
    must not crash a predicate-based tool -- it should evaluate the
    predicate against an empty dict rather than raise."""
    assert registry.requires_confirmation("write_file_content") is False


@pytest.mark.asyncio
async def test_execute_unknown_tool_returns_error_not_exception(registry):
    result = await registry.execute("not_a_real_tool", {})
    assert result["success"] is False
    assert "Unknown tool" in result["error"]


@pytest.mark.asyncio
async def test_execute_sync_handler_runs_off_the_event_loop(registry):
    result = await registry.execute("get_current_datetime", {})
    assert result["success"] is True
    assert "datetime" in result


@pytest.mark.asyncio
async def test_execute_with_bad_arguments_returns_error_not_exception(registry):
    # search_files requires 'query' and 'root' — omit both.
    result = await registry.execute("search_files", {})
    assert result["success"] is False
    assert "Invalid arguments" in result["error"]


@pytest.mark.asyncio
async def test_remember_fact_tool_calls_through_to_memory():
    memory = FakeMemory()
    registry = ToolRegistry(memory=memory, browser=BrowserController(), provider_router=FakeProviderRouter())

    result = await registry.execute("remember_fact", {"category": "preference", "key": "editor", "value": "VS Code"})
    assert result["success"] is True
    assert memory.remembered == [("preference", "editor", "VS Code")]
