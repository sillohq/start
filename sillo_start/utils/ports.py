"""TCP port availability checks.

The development orchestrator starts several servers at once, and the failure
mode when a port is taken — one service dying seconds after the others start —
is confusing. Checking up front turns that into a clear message before anything
launches.
"""

from __future__ import annotations

import socket
from contextlib import closing

#: Ports the generated projects use by convention.
DEFAULT_BACKEND_PORT = 8000
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_REDIS_PORT = 6379
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_MYSQL_PORT = 3306
DEFAULT_MAILPIT_PORT = 8025


def is_port_free(port: int, host: str = "127.0.0.1") -> bool:
    """Report whether *port* can be bound on *host*.

    ``SO_REUSEADDR`` is deliberately not set: we want to know whether a bind
    would succeed as an ordinary server, not whether we could steal a socket in
    ``TIME_WAIT``.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Inverse of :func:`is_port_free`, for readability at call sites."""
    return not is_port_free(port, host)


def find_free_port(start: int, *, limit: int = 50, host: str = "127.0.0.1") -> int:
    """Find the first free port at or after *start*.

    Args:
        start: Port to begin scanning from.
        limit: How many consecutive ports to try.
        host: Interface to test against.

    Returns:
        A port number that was free at the time of checking.

    Raises:
        OSError: If no free port was found within *limit* attempts.
    """
    for candidate in range(start, start + limit):
        if candidate > 65535:
            break
        if is_port_free(candidate, host):
            return candidate
    raise OSError(f"No free port found in range {start}-{start + limit}.")


def can_connect(host: str, port: int, *, timeout: float = 1.0) -> bool:
    """Report whether something is listening at ``host:port``.

    This is the positive form used by health checks — it answers "is Redis up"
    rather than "is the port free".
    """
    try:
        with closing(socket.create_connection((host, port), timeout=timeout)):
            return True
    except (OSError, ValueError):
        return False
