"""
Anvil site detection and defaults.
"""

from __future__ import annotations

from .base import BaseSite


class AnvilSite(BaseSite):
    """Anvil site configuration placeholder."""

    @property
    def name(self) -> str:
        return "anvil"

    @property
    def display_name(self) -> str:
        return "Anvil"

    def detect(self) -> bool:
        """TODO: Implement Anvil detection."""
        return False