"""
Public API for site detection and site-specific defaults.
"""

from .site_config import apply_site_defaults, detect_site

__all__ = [
    "apply_site_defaults",
    "detect_site",
]