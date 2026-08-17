"""
Tests PluginManager against real temp files on disk (actual .py plugin
files written to a temp directory and imported for real via
importlib.util.spec_from_file_location — the same code path the external
plugin loader uses in production) and a real temporary SQLite database
for enable/disable persistence. Not mocked — this exercises the actual
discovery/import/instantiate/register pipeline end to end.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.automation.browser.browser_controller import BrowserController
from app.brain.memory.memory_manager import MemoryManager
from app.brain.tools import ToolRegistry

GOOD_PLUGIN_SOURCE = """
from app.plugins.base import BasePlugin

class GreetPlugin(BasePlugin):
    name = "greet_test_plugin"
    version = "2.1.0"
    description = "Says hello."

    def register_tools(self, register):
        register(
            "say_hello",
            "Says hello to someone.",
            {"type": "object", "properties": {"who": {"type": "string"}}, "required": ["who"]},
            lambda who: {"success": True, "message": f"Hello, {who}!"},
        )
"""

BROKEN_IMPORT_SOURCE = """
import this_module_does_not_exist_anywhere

from app.plugins.base import BasePlugin

class NeverLoadsPlugin(BasePlugin):
    name = "never_loads"
    def register_tools(self, register):
        pass
"""

BROKEN_ON_LOAD_SOURCE = """
from app.plugins.base import BasePlugin

class ExplodesOnLoadPlugin(BasePlugin):
    name = "explodes_on_load"

    def on_load(self):
        raise RuntimeError("simulated setup failure")

    def register_tools(self, register):
        register("never_reached", "unreachable", {"type": "object", "properties": {}}, lambda: {"success": True})
"""

NO_PLUGIN_CLASS_SOURCE = """
# A .py file with no BasePlugin subclass at all -- should just be skipped,
# not treated as an error.
CONSTANT = 42
"""


@pytest.fixture
def temp_db(monkeypatch):
    tmp_dir = tempfile.mkdtemp()
    db_path = Path(tmp_dir) / "test_plugins.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    import app.core.config as config_module
    import app.data.database as database_module

    config_module.get_settings.cache_clear()
    database_module._engine = None
    database_module._SessionLocal = None

    from app.data.models import Base

    Base.metadata.create_all(database_module.get_engine())

    yield

    database_module._engine = None
    database_module._SessionLocal = None
    config_module.get_settings.cache_clear()


@pytest.fixture
def tool_registry():
    memory = MemoryManager()
    from app.brain.router import NoProvidersConfiguredRouter

    return ToolRegistry(memory=memory, browser=BrowserController(), provider_router=NoProvidersConfiguredRouter())


@pytest.fixture
def plugins_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


def _write_plugin(plugins_dir: Path, filename: str, source: str) -> None:
    (plugins_dir / filename).write_text(source)


def test_valid_external_plugin_loads_and_registers_its_tool(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "greet.py", GOOD_PLUGIN_SOURCE)
    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)

    records = manager.discover_and_load()

    matching = [r for r in records if r.name == "greet_test_plugin"]
    assert len(matching) == 1
    assert matching[0].loaded is True
    assert matching[0].version == "2.1.0"
    assert matching[0].source == "external"
    assert tool_registry.exists("say_hello")


def test_registered_tool_actually_works_when_executed(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "greet.py", GOOD_PLUGIN_SOURCE)
    PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir).discover_and_load()

    import asyncio

    result = asyncio.run(tool_registry.execute("say_hello", {"who": "Suraj"}))
    assert result == {"success": True, "message": "Hello, Suraj!"}


def test_broken_import_is_isolated_not_fatal(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "broken_import.py", BROKEN_IMPORT_SOURCE)
    _write_plugin(plugins_dir, "greet.py", GOOD_PLUGIN_SOURCE)  # a healthy sibling plugin

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)
    records = manager.discover_and_load()  # must not raise

    broken = [r for r in records if r.name == "broken_import"]
    assert len(broken) == 1
    assert broken[0].loaded is False
    assert broken[0].error is not None

    # The broken plugin must not have taken down its sibling.
    healthy = [r for r in records if r.name == "greet_test_plugin"]
    assert healthy[0].loaded is True


def test_exception_in_on_load_is_isolated_and_tools_are_not_left_registered(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "explodes.py", BROKEN_ON_LOAD_SOURCE)
    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)

    records = manager.discover_and_load()

    record = next(r for r in records if r.name == "explodes_on_load")
    assert record.loaded is False
    assert "simulated setup failure" in record.error
    assert not tool_registry.exists("never_reached")


def test_module_with_no_plugin_class_is_silently_skipped(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "not_a_plugin.py", NO_PLUGIN_CLASS_SOURCE)
    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)

    records = manager.discover_and_load()
    assert all(r.name != "not_a_plugin" for r in records)


def test_nonexistent_external_dir_does_not_crash(temp_db, tool_registry):
    from app.plugins.registry import PluginManager

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=Path("/definitely/does/not/exist"))
    records = manager.discover_and_load()  # must not raise
    assert isinstance(records, list)


def test_disabling_a_plugin_persists_and_is_not_loaded_on_next_discovery(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    _write_plugin(plugins_dir, "greet.py", GOOD_PLUGIN_SOURCE)

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)
    manager.discover_and_load()
    assert manager.set_enabled("greet_test_plugin", False) is True

    # Fresh manager + fresh registry, simulating an app restart.
    from app.brain.router import NoProvidersConfiguredRouter

    fresh_registry = ToolRegistry(
        memory=MemoryManager(), browser=BrowserController(), provider_router=NoProvidersConfiguredRouter()
    )
    fresh_manager = PluginManager(tool_registry=fresh_registry, external_plugins_dir=plugins_dir)
    records = fresh_manager.discover_and_load()

    record = next(r for r in records if r.name == "greet_test_plugin")
    assert record.enabled is False
    assert record.loaded is False
    assert not fresh_registry.exists("say_hello")


def test_set_enabled_on_unknown_plugin_returns_false(temp_db, tool_registry):
    from app.plugins.registry import PluginManager

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=None)
    assert manager.set_enabled("totally_made_up_plugin", False) is False


def test_duplicate_plugin_name_second_one_is_skipped(temp_db, tool_registry, plugins_dir):
    from app.plugins.registry import PluginManager

    # Two different files, same declared plugin `name` -- must not double-register.
    dup_source = GOOD_PLUGIN_SOURCE.replace("say_hello", "say_hello_again")
    _write_plugin(plugins_dir, "greet_a.py", GOOD_PLUGIN_SOURCE)
    _write_plugin(plugins_dir, "greet_b.py", dup_source)

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)
    records = manager.discover_and_load()

    matching = [r for r in records if r.name == "greet_test_plugin"]
    assert len(matching) == 1  # second one was skipped, not overwritten as a second record


def test_shutdown_calls_on_unload_for_every_loaded_plugin(temp_db, tool_registry, plugins_dir):
    unload_source = """
from app.plugins.base import BasePlugin

class TracksUnloadPlugin(BasePlugin):
    name = "tracks_unload"
    def register_tools(self, register):
        pass
    def on_unload(self):
        import pathlib
        pathlib.Path(r"{marker_path}").write_text("unloaded")
"""
    marker_path = Path(tempfile.mkdtemp()) / "unload_marker.txt"
    _write_plugin(plugins_dir, "tracks_unload.py", unload_source.format(marker_path=str(marker_path)))

    from app.plugins.registry import PluginManager

    manager = PluginManager(tool_registry=tool_registry, external_plugins_dir=plugins_dir)
    manager.discover_and_load()
    assert not marker_path.exists()

    manager.shutdown()
    assert marker_path.exists()
