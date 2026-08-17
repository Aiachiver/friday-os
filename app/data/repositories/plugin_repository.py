"""Repository for plugin enable/disable state."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import PluginState


class PluginRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_state(self, plugin_name: str) -> PluginState | None:
        stmt = select(PluginState).where(PluginState.plugin_name == plugin_name)
        return self._session.scalars(stmt).first()

    def get_all_states(self) -> list[PluginState]:
        return list(self._session.scalars(select(PluginState)))

    def register_seen(self, plugin_name: str, version: str) -> PluginState:
        """Called by PluginManager the first time it discovers a plugin.
        If the plugin was already known (e.g. from a previous run), this
        just updates its recorded version and leaves the user's
        enabled/disabled choice untouched — discovery must never silently
        re-enable something the user turned off."""
        existing = self.get_state(plugin_name)
        if existing is not None:
            existing.version = version
            self._session.commit()
            self._session.refresh(existing)
            return existing

        state = PluginState(plugin_name=plugin_name, enabled=True, version=version)
        self._session.add(state)
        self._session.commit()
        self._session.refresh(state)
        return state

    def is_enabled(self, plugin_name: str) -> bool:
        """A plugin with no recorded state is treated as enabled — see
        PluginState's docstring."""
        state = self.get_state(plugin_name)
        return state.enabled if state is not None else True

    def set_enabled(self, plugin_name: str, enabled: bool) -> bool:
        state = self.get_state(plugin_name)
        if state is None:
            return False
        state.enabled = enabled
        self._session.commit()
        return True
