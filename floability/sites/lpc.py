"""
LPC site detection and defaults.
"""

from __future__ import annotations

from .base import BaseSite


class LPCSite(BaseSite):
    """LPC site configuration placeholder."""

    @property
    def name(self) -> str:
        return "lpc"

    @property
    def display_name(self) -> str:
        return "LPC"

    def detect(self) -> bool:
        """TODO: Implement LPC detection."""
        return False