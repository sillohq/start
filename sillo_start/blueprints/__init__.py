"""Project blueprints: named archetypes that shape a new project."""

from .base import Blueprint, FileSpec
from .builtins import BLUEPRINT_DEFAULTS, BUILTIN_BLUEPRINTS, apply_defaults
from .registry import BlueprintRegistry, registry

__all__ = [
    "Blueprint",
    "FileSpec",
    "BlueprintRegistry",
    "registry",
    "BUILTIN_BLUEPRINTS",
    "BLUEPRINT_DEFAULTS",
    "apply_defaults",
]
