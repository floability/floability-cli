"""
Base class for site detection and site-specific CLI defaults.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from argparse import Namespace
from collections.abc import Iterable, Mapping
from typing import Any


class BaseSite(ABC):
    """
    Abstract base class for a supported computing site.

    Each site should define:
    - name: short internal site name, e.g. "nd"
    - display_name: user-facing site name
    - defaults: CLI defaults to apply when not explicitly provided
    - detect(): site-specific detection logic
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short internal site name."""
        pass

    @property
    def display_name(self) -> str:
        """Human-readable site name."""
        return self.name

    @property
    def defaults(self) -> Mapping[str, Any]:
        """Site-specific CLI defaults."""
        return {}

    @abstractmethod
    def detect(self) -> bool:
        """Return True if the current host matches this site."""
        pass

    def apply_defaults(
        self,
        args: Namespace,
        explicit_args: Iterable[str] | None = None,
    ) -> list[str]:
        """
        Apply site defaults in-place, preserving explicitly provided CLI args.

        Returns:
            List of applied defaults formatted as strings.
        """
        explicit = self._resolve_explicit_args(args, explicit_args)
        applied: list[str] = []

        for key, value in self.defaults.items():
            if key in explicit:
                continue

            setattr(args, key, value)
            applied.append(f"{key}={value}")

        return applied

    def _resolve_explicit_args(
        self,
        args: Namespace,
        explicit_args: Iterable[str] | None,
    ) -> set[str]:
        return set(explicit_args or getattr(args, "_explicit_args", ()) or ())