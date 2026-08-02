"""Health checks for supervised services.

A process being alive is not the same as a service being ready — uvicorn takes
a moment to bind, and Vite longer still. These checks answer the question the
developer actually has: can I open this URL yet.

Checks use only the standard library. Adding an HTTP client dependency to a
scaffolding tool to poll localhost would be a poor trade.
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass


class HealthCheck(ABC):
    """Reports whether a service is ready to serve."""

    #: How long to keep checking before declaring the service unhealthy.
    timeout: float = 30.0

    @abstractmethod
    def check(self) -> bool:
        """Return True when the service is ready."""

    @abstractmethod
    def describe(self) -> str:
        """Describe what is being checked, for status output."""


@dataclass
class PortCheck(HealthCheck):
    """Ready once something accepts connections on a port."""

    port: int
    host: str = "127.0.0.1"
    timeout: float = 30.0

    def check(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=1.0):
                return True
        except (OSError, ValueError):
            return False

    def describe(self) -> str:
        return f"tcp://{self.host}:{self.port}"


@dataclass
class HttpCheck(HealthCheck):
    """Ready once a URL responds with an acceptable status.

    Args:
        url: URL to request.
        expect_below: Treat any status below this as healthy. The default of
            500 means a 404 still counts as up — the server is answering,
            which is what we are checking for.
    """

    url: str
    expect_below: int = 500
    timeout: float = 30.0

    def check(self) -> bool:
        request = urllib.request.Request(self.url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:  # noqa: S310 — fixed localhost URL
                return response.status < self.expect_below
        except urllib.error.HTTPError as exc:
            # The server answered, which is what "up" means here.
            return exc.code < self.expect_below
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def describe(self) -> str:
        return self.url


def http_check(url: str, *, expect_below: int = 500) -> HttpCheck:
    """Build an :class:`HttpCheck`."""
    return HttpCheck(url=url, expect_below=expect_below)


def port_check(port: int, *, host: str = "127.0.0.1") -> PortCheck:
    """Build a :class:`PortCheck`."""
    return PortCheck(port=port, host=host)
