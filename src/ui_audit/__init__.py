"""Responsive UI Auditor."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ui-audit")  # pyproject.toml is the one place the version is written
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
