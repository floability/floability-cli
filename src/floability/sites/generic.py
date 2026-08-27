"""
Generic / unknown site fallback.
"""

from __future__ import annotations

from .base import BaseSite


class GenericSite(BaseSite):
    """Fallback site used when no known site is detected."""

    @property
    def name(self) -> str:
        return "generic"

    @property
    def display_name(self) -> str:
        return "generic/unknown"

    def detect(self) -> bool:
        """
        Generic is a fallback, not an actual site detector.

        This should not be used in the main detection loop.
        """
        return True