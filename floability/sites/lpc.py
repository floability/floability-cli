"""
LPC site detection and defaults.
"""

from __future__ import annotations

from floability.utils import get_system_information

from .base import BaseSite


class LPCSite(BaseSite):
    """LPC site configuration placeholder."""
    
    _HOST_HINTS = (
        "fnal.gov",
    )

    @property
    def name(self) -> str:
        return "lpc"

    @property
    def display_name(self) -> str:
        return "LPC (Fermilab)"
    
    @property
    def defaults(self) -> dict[str, str]:
        return {
            "manager_ports": "10000,11000",
            "worker_transfer_ports": "10000:11000",
        }

    def detect(self) -> bool:
        info = get_system_information()

        hostname = str(info.get("hostname", "") or "").strip().lower().rstrip(".")
        fqdn = str(info.get("fqdn", "") or "").strip().lower().rstrip(".")

        candidates = (hostname, fqdn)

        return any(
            hint in candidate
            for candidate in candidates
            for hint in self._HOST_HINTS
        )