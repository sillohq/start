"""Discovering and loading plugins from entry points.

A broken plugin must not stop the tool working. Loading is therefore
fault-tolerant: a plugin that fails to import or raises during registration is
reported as a warning and skipped, and everything else still loads. The
alternative — one bad third-party package making ``sillo-start`` unusable — is
far worse than running without that plugin.
"""

from __future__ import annotations

from importlib.metadata import entry_points

from ..utils.console import console
from .api import ENTRY_POINT_GROUP, Plugin

#: Plugins loaded in this process, keyed by entry point name.
_loaded: dict[str, Plugin] = {}
#: Failures, kept so `doctor` can report them.
_failures: dict[str, str] = {}


def load_plugins(*, reload: bool = False) -> dict[str, Plugin]:
    """Load every registered plugin.

    Args:
        reload: Load again even if plugins were already loaded. Used by tests.

    Returns:
        The successfully loaded plugins, keyed by entry point name.
    """
    if _loaded and not reload:
        return _loaded
    if reload:
        _loaded.clear()
        _failures.clear()

    for entry_point in _discover():
        try:
            factory = entry_point.load()
        except Exception as exc:  # noqa: BLE001 — one bad plugin must not break the CLI
            _fail(entry_point.name, f"could not be imported: {exc}")
            continue

        plugin = Plugin(name=entry_point.name)
        try:
            factory(plugin)
        except Exception as exc:  # noqa: BLE001
            _fail(entry_point.name, f"failed during registration: {exc}")
            continue

        _loaded[entry_point.name] = plugin
        console.debug(f"loaded plugin '{entry_point.name}': {plugin.registered}")

    return _loaded


def _discover():
    """Return the entry points in our group, tolerating an unreadable env."""
    try:
        return list(entry_points(group=ENTRY_POINT_GROUP))
    except Exception as exc:  # noqa: BLE001
        console.debug(f"plugin discovery failed: {exc}")
        return []


def _fail(name: str, reason: str) -> None:
    """Record and report a plugin failure without aborting."""
    _failures[name] = reason
    console.warning(f"Plugin '{name}' {reason}")


def loaded_plugins() -> dict[str, Plugin]:
    """The plugins loaded so far."""
    return dict(_loaded)


def plugin_failures() -> dict[str, str]:
    """Plugins that failed to load, mapped to why."""
    return dict(_failures)
