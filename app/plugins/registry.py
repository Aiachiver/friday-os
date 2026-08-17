"""
Discovers plugins from two places:

  1. app/plugins/builtin/ — shipped with FRIDAY (Weather, System Monitor,
     Spotify).
  2. <project_root>/plugins/ — an external, user-writable directory
     OUTSIDE the app package. This is what makes "installable without
     modifying core code" literally true: dropping a .py file here is
     enough, no edits to anything under app/ required, and it survives
     an app update/reinstall since it's not part of the installed
     package.

A broken plugin (import error, missing class, exception in on_load or
register_tools) is caught, logged, and skipped — it must never take
the rest of the app down. Each plugin's enable/disable state is
persisted in SQLite (see app/data/repositories/plugin_repository.py) so
a user's choice to turn a plugin off survives a restart.
"""

from __future__ import annotations

import functools
import importlib
import importlib.util
import inspect
import pkgutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

from app.brain.tools import ToolRegistry
from app.data.database import get_session
from app.data.repositories.plugin_repository import PluginRepository
from app.plugins.base import BasePlugin
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class PluginRecord:
    name: str
    version: str
    description: str
    source: str  # "builtin" | "external"
    enabled: bool
    loaded: bool  # True if register_tools() ran successfully
    error: str | None = field(default=None)


class _FailedImport:
    """Sentinel carrying an import-time failure through to _load_module
    so a broken module file still produces a visible PluginRecord (for
    the GUI plugin manager) instead of just silently vanishing from the
    list of known plugins."""

    def __init__(self, name: str, error: str) -> None:
        self.name = name
        self.error = error


class PluginManager:
    def __init__(self, tool_registry: ToolRegistry, external_plugins_dir: Path | None = None) -> None:
        self._registry = tool_registry
        self._external_dir = external_plugins_dir
        self._instances: dict[str, BasePlugin] = {}
        self._records: dict[str, PluginRecord] = {}

    def discover_and_load(self) -> list[PluginRecord]:
        self._records.clear()

        builtin_path = Path(__file__).resolve().parent / "builtin"
        for module in self._iter_builtin_modules(builtin_path):
            self._load_module(module, source="builtin")

        if self._external_dir is not None:
            if self._external_dir.exists():
                for module in self._iter_external_modules(self._external_dir):
                    self._load_module(module, source="external")
            else:
                log.debug("External plugins directory {} does not exist; skipping.", self._external_dir)

        return list(self._records.values())

    def list_plugins(self) -> list[PluginRecord]:
        return list(self._records.values())

    def set_enabled(self, plugin_name: str, enabled: bool) -> bool:
        """Toggles a plugin's persisted state. Takes effect on the next
        app restart (register_tools() only runs during discovery) rather
        than hot-unloading mid-session — simpler and safer than trying to
        cleanly tear down a plugin's open connections/state on the fly."""
        with get_session() as session:
            success = PluginRepository(session).set_enabled(plugin_name, enabled)
        if success and plugin_name in self._records:
            self._records[plugin_name].enabled = enabled
        return success

    def shutdown(self) -> None:
        for name, instance in self._instances.items():
            try:
                instance.on_unload()
            except Exception:
                log.exception("Plugin '{}' raised during on_unload()", name)

    # --- discovery -----------------------------------------------------------

    @staticmethod
    def _iter_builtin_modules(builtin_path: Path) -> Iterator[ModuleType | _FailedImport]:
        if not builtin_path.exists():
            return
        package_name = "app.plugins.builtin"
        for _, module_name, is_pkg in pkgutil.iter_modules([str(builtin_path)]):
            if is_pkg or module_name.startswith("_"):
                continue
            try:
                yield importlib.import_module(f"{package_name}.{module_name}")
            except Exception as exc:
                log.error("Failed to import built-in plugin module '{}': {}", module_name, exc)
                yield _FailedImport(module_name, str(exc))

    @staticmethod
    def _iter_external_modules(external_dir: Path) -> Iterator[ModuleType | _FailedImport]:
        for py_file in sorted(external_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            module_name = f"friday_external_plugin_{py_file.stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    raise ImportError(f"Could not load spec for {py_file}")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                yield module
            except Exception as exc:
                log.error("Failed to import external plugin file '{}': {}", py_file.name, exc)
                yield _FailedImport(py_file.stem, str(exc))

    # --- loading ---------------------------------------------------------------

    def _load_module(self, module: ModuleType | _FailedImport, source: str) -> None:
        if isinstance(module, _FailedImport):
            self._records[module.name] = PluginRecord(
                name=module.name,
                version="?",
                description="",
                source=source,
                enabled=False,
                loaded=False,
                error=module.error,
            )
            return

        plugin_classes = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BasePlugin) and obj is not BasePlugin and obj.__module__ == module.__name__
        ]
        if not plugin_classes:
            log.debug("Module {} defines no BasePlugin subclass; skipping.", module.__name__)
            return

        for plugin_class in plugin_classes:
            self._load_plugin_class(plugin_class, source)

    def _load_plugin_class(self, plugin_class: type[BasePlugin], source: str) -> None:
        try:
            instance = plugin_class()
        except Exception as exc:
            name = getattr(plugin_class, "name", plugin_class.__name__)
            log.error("Failed to instantiate plugin '{}': {}", name, exc)
            self._records[name] = PluginRecord(
                name=name,
                version="?",
                description="",
                source=source,
                enabled=False,
                loaded=False,
                error=str(exc),
            )
            return

        name = instance.name
        version = instance.version

        if name in self._records:
            log.warning(
                "Plugin name collision: '{}' was already loaded from {} — skipping this duplicate from {}.",
                name,
                self._records[name].source,
                source,
            )
            return

        with get_session() as session:
            repo = PluginRepository(session)
            repo.register_seen(name, version)
            enabled = repo.is_enabled(name)

        if not enabled:
            log.info("Plugin '{}' is disabled; not loading its tools.", name)
            self._records[name] = PluginRecord(
                name=name,
                version=version,
                description=instance.description,
                source=source,
                enabled=False,
                loaded=False,
            )
            return

        try:
            instance.on_load()
            registrar = functools.partial(self._registry.register_external_tool, name)
            instance.register_tools(registrar)
        except Exception as exc:
            log.error("Plugin '{}' failed during load/registration: {}", name, exc)
            self._registry.unregister_plugin_tools(name)
            self._records[name] = PluginRecord(
                name=name,
                version=version,
                description=instance.description,
                source=source,
                enabled=True,
                loaded=False,
                error=str(exc),
            )
            return

        self._instances[name] = instance
        self._records[name] = PluginRecord(
            name=name,
            version=version,
            description=instance.description,
            source=source,
            enabled=True,
            loaded=True,
        )
        log.info("Loaded plugin '{}' v{} ({})", name, version, source)
