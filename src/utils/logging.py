"""Logging setup.

The CLI prints a human report to stdout; logs go to stderr so they do
not corrupt piped output (e.g. --json).
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup_logging(level: str = "INFO", quiet: bool = False) -> None:
    """Configure root logging once. Safe to call multiple times."""
    global _CONFIGURED
    numeric = getattr(logging, str(level).upper(), logging.INFO)
    if quiet:
        numeric = max(numeric, logging.WARNING)
    root = logging.getLogger()
    if not _CONFIGURED:
        handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt="%H:%M:%S"))
        root.addHandler(handler)
        _CONFIGURED = True
    root.setLevel(numeric)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(f"trading_agent.{name}")
