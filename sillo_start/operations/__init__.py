"""Reversible units of project mutation, and the transaction that applies them."""

from .base import (
    CompositeOperation,
    ExecutionContext,
    Operation,
    OperationResult,
    OperationStatus,
)
from .commands import RegisterPackageGroup, RunCommand, UpdateManifest
from .dependencies import (
    InstallFrontendPackage,
    InstallPythonPackage,
    UpdateJson,
    UpdateToml,
)
from .files import (
    CreateDirectory,
    CreateFile,
    DeleteFile,
    UpdateEnvironment,
    UpdateMarkerSection,
)
from .transaction import (
    ExecutionPlan,
    Transaction,
    TransactionReport,
    execute_plan,
)

__all__ = [
    "Operation",
    "OperationResult",
    "OperationStatus",
    "ExecutionContext",
    "CompositeOperation",
    "CreateDirectory",
    "CreateFile",
    "DeleteFile",
    "UpdateEnvironment",
    "UpdateMarkerSection",
    "UpdateToml",
    "UpdateJson",
    "InstallPythonPackage",
    "InstallFrontendPackage",
    "RunCommand",
    "UpdateManifest",
    "RegisterPackageGroup",
    "ExecutionPlan",
    "Transaction",
    "TransactionReport",
    "execute_plan",
]
