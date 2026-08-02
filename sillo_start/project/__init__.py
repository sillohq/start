"""Creating, inspecting and validating projects on disk."""

from .creator import CreationResult, ProjectCreator
from .manifest import ProjectOptions, build_manifest
from .structure import directories_for, package_directories

__all__ = [
    "ProjectCreator",
    "CreationResult",
    "ProjectOptions",
    "build_manifest",
    "directories_for",
    "package_directories",
]
