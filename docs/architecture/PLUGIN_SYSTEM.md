# Plugin System

FRIDAY's plugin system lets you add new capabilities — new tools the AI
brain can call — without touching any core code. A plugin is a single
Python file (or package) that subclasses `BasePlugin` and registers one
or more tools.

## Where plugins live

- **Built-in**: `app/plugins/builtin/` — shipped with FRIDAY (Weather,
  System Monitor, Spotify). These are regular part of the codebase.
- **External**: `<user_data_root>/plugins/` — a folder outside the `app/`
  package, created automatically if missing. Drop a `.py` file here and
  it's discovered on the next restart. This directory is gitignored and
  survives an app update, since it's not part of the installed package.
  When running from source, `user_data_root` is the project root, so
  this is just `plugins/` in the repo. In an installed (PyInstaller)
  build, it's `%LOCALAPPDATA%\FridayOS\plugins` — deliberately NOT next
  to the installed .exe, since a standard Windows user account typically
  can't write under Program Files.

## Writing a plugin

```python
# plugins/my_plugin.py
from app.plugins.base import BasePlugin

class MyPlugin(BasePlugin):
    name = "my_plugin"              # must be globally unique
    version = "1.0.0"
    description = "One-line description shown in the Plugins dialog."

    def register_tools(self, register):
        register(
            "my_tool_name",                    # must be globally unique across ALL tools
            "What this tool does, in plain language the AI brain reads to decide when to call it.",
            {
                "type": "object",
                "properties": {
                    "some_argument": {"type": "string", "description": "..."},
                },
                "required": ["some_argument"],
            },
            self.my_handler,                     # sync or async, both work
            requires_confirmation=False,          # True for anything destructive/consequential
        )

    def my_handler(self, some_argument: str) -> dict:
        # Always return a dict with at least {"success": bool}.
        # Never raise for expected failure conditions -- report them
        # in the dict instead, the same way every built-in tool does.
        return {"success": True, "result": f"did something with {some_argument}"}
```

That's the entire contract. A few rules that matter:

- **`name` and every registered tool name must be globally unique.**
  A collision with a built-in tool or another plugin causes that
  specific registration to fail (logged, not fatal to the whole app) —
  see `ToolRegistry.register_external_tool`.
- **Handlers return dicts, not exceptions**, for anything the AI brain
  or user should hear about ("Spotify isn't configured", "no file
  found"). Let real bugs raise — `ToolRegistry.execute()` catches
  unexpected exceptions and reports them as a tool failure rather than
  crashing the conversation, but that's a safety net, not something to
  rely on for expected error paths.
- **Use `requires_confirmation=True`** for anything a user would want a
  chance to back out of (deleting things, spending money, sending
  messages, changing system state) — the orchestrator already has a
  complete confirm-then-execute flow (see Phase 3's `_ask_for_confirmation`
  in `app/core/orchestrator.py`); a plugin just opts into it with this one
  flag, no extra plumbing needed.
- **`on_load()` / `on_unload()` are optional.** Use `on_load()` to fail
  fast on a genuinely broken setup, or leave it as a no-op and have your
  tool handlers themselves report a clear "not configured" error — the
  Spotify plugin does the latter, since a user without Spotify configured
  should still get the rest of FRIDAY working normally, not a crash at
  startup.

## Enabling/disabling

Every discovered plugin (built-in or external) gets a persisted
enabled/disabled row in SQLite the first time it's seen, defaulting to
enabled. Toggle it from the dashboard's **Plugins** button. Changes take
effect on the next restart — `register_tools()` only runs during
startup discovery, so there's no half-loaded/half-unloaded state to
reason about mid-session.

## Error isolation

A broken plugin (import error, exception in `__init__`, `on_load()`, or
`register_tools()`) is caught, logged, and shown in the Plugins dialog
with its error message — it never takes down the rest of the app or
prevents other plugins from loading. This is exercised directly in
`tests/unit/test_plugin_registry.py` with real broken plugin files
written to a temp directory and loaded through the actual discovery
path, not mocked.

## The three built-in plugins

| Plugin | Setup needed | Doc |
|---|---|---|
| Weather | None — Open-Meteo requires no API key | — |
| System Monitor | None — pure psutil | — |
| Spotify | Free Spotify Developer app + OAuth | `docs/architecture/SPOTIFY_SETUP.md` |
