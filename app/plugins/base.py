"""
Plugin interface. A plugin is a self-contained unit that adds one or
more tools to the AI brain's existing ToolRegistry — it does NOT get its
own parallel routing/dispatch mechanism, because Phase 3 already built a
complete, working tool-calling system (JSON-schema specs, confirmation
gating, async/sync dispatch) and reinventing that per-plugin would be
pure duplication for zero behavioral gain.

A plugin registers tools through the `register` callback passed to
`register_tools()` rather than importing ToolRegistry directly — this
keeps plugin code decoupled from the registry's internals (a plugin
author only needs to know this one small function signature, not
ToolRegistry's constructor, its automation/finance/vision imports, or
its confirmation-flag bookkeeping).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

ToolHandler = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


class ToolRegistrar(Protocol):
    """The one function a plugin needs to register a tool. Matches
    ToolRegistry.register_external_tool's signature exactly — see
    app/brain/tools.py."""

    def __call__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolHandler,
        requires_confirmation: bool = False,
    ) -> None: ...


class BasePlugin(ABC):
    """Subclass this, set the three class attributes, and implement
    register_tools(). See docs/architecture/PLUGIN_SYSTEM.md for a full
    walkthrough and docs/architecture/... individual plugin setup guides
    for the built-in examples."""

    name: str
    version: str = "1.0.0"
    description: str = ""

    @abstractmethod
    def register_tools(self, register: ToolRegistrar) -> None:
        """Call `register(...)` once per tool this plugin provides."""

    def on_load(self) -> None:  # noqa: B027 -- intentionally optional, not a forgotten @abstractmethod
        """Optional: called once when the plugin is loaded (e.g. to
        validate an API key is present, open a persistent client). Not
        required to raise on a missing key — a plugin can instead simply
        register no tools, or register tools whose handlers themselves
        report a clear 'not configured' error, matching the graceful-
        degradation pattern used throughout this project (voice, AI
        brain). Default: no-op."""

    def on_unload(self) -> None:  # noqa: B027 -- intentionally optional, not a forgotten @abstractmethod
        """Optional: called when the plugin is disabled or the app shuts
        down (e.g. to close a persistent client/connection). Default: no-op."""
