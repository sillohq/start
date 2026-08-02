"""Sillo package groups: declarative capability bundles."""

from . import definitions  # noqa: F401 — registers the built-in groups on import
from .installer import (
    build_install_plan,
    build_removal_plan,
    database_driver_packages,
    sillo_requirement,
)
from .registry import PackageGroup, PackageRegistry, registry
from .resolver import Resolution, dependents_of, resolve, validate_selection

__all__ = [
    "PackageGroup",
    "PackageRegistry",
    "registry",
    "Resolution",
    "resolve",
    "dependents_of",
    "validate_selection",
    "build_install_plan",
    "build_removal_plan",
    "sillo_requirement",
    "database_driver_packages",
]
