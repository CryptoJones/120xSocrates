"""120xSocrates — Socratic interview tool for 120x Operators Kit projects."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("socrates120x")
except PackageNotFoundError:
    # Running from a source checkout that was never installed.
    __version__ = "0.0.0+unknown"
