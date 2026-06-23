"""
Notre Dame / ND site detection and defaults.
"""

from __future__ import annotations

from .base import BaseSite
from ..utils import get_system_information


class NotreDameSite(BaseSite):
    """Notre Dame CRC site configuration."""

    _HOST_HINTS = (
        "crc.nd.edu",
    )

    @property
    def name(self) -> str:
        return "nd"

    @property
    def display_name(self) -> str:
        return "Notre Dame CRC (ND)"

    @property
    def defaults(self) -> dict[str, str]:
        return {
            "manager_ports": "9100,9200",
        }

    def detect(self) -> bool:
        """Return True when the current host looks like Notre Dame / ND CRC."""
        info = get_system_information()

        hostname = str(info.get("hostname", "") or "").strip().lower().rstrip(".")
        fqdn = str(info.get("fqdn", "") or "").strip().lower().rstrip(".")

        candidates = (hostname, fqdn)

        return any(
            hint in candidate
            for candidate in candidates
            for hint in self._HOST_HINTS
        )