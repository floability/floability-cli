"""
Top-level site detection and site-default application logic.
"""

from __future__ import annotations

from argparse import Namespace
from collections.abc import Iterable

from .base import BaseSite
from .generic import GenericSite
from .nd import NotreDameSite
from .anvil import AnvilSite
from .lpc import LPCSite


KNOWN_SITES: tuple[BaseSite, ...] = (
    NotreDameSite(),
    AnvilSite(),
    LPCSite(),
)

GENERIC_SITE = GenericSite()


def detect_site() -> BaseSite:
    """
    Detect the current computing site.

    Returns:
        Matching site object, or GenericSite when no known site matches.
    """
    for site in KNOWN_SITES:
        try:
            if site.detect():
                print(f"[site_config] Detected site: {site.display_name}")
                return site
        except Exception as exc:
            print(f"[site_config] Warning: detection failed for {site.display_name}: {exc}")

    print("[site_config] No known site detected; using generic site settings.")
    return GENERIC_SITE


def apply_site_defaults(
    args: Namespace,
    explicit_args: Iterable[str] | None = None,
) -> Namespace:
    """
    Apply detected site defaults in-place.

    User-provided CLI values are preserved.

    Args:
        args: Parsed CLI arguments.
        explicit_args: Argument names explicitly provided by the user.

    Returns:
        The same argparse Namespace, modified in-place.
    """
    site = detect_site()

    # Store this for debugging/downstream introspection if needed.
    setattr(args, "_detected_site", site.name)

    applied = site.apply_defaults(args, explicit_args=explicit_args)
    
    _print_site_config_summary(site, applied)
    
    return args

def _get_hostname() -> str:
    """Return best-effort hostname for site configuration messages."""
    try:
        from ..utils import get_system_information

        info = get_system_information()
        fqdn = str(info.get("fqdn", "") or "").strip()
        hostname = str(info.get("hostname", "") or "").strip()
        return fqdn or hostname or "unknown"
    except Exception:
        return "unknown"
    

def _print_site_config_summary(site: BaseSite, applied: list[str]) -> None:
    """Print a visible summary of detected site configuration."""
    hostname = _get_hostname()

    print("=" * 60)
    print("[site_config] Site Configuration")
    print("=" * 60)
    print(f"  Hostname      : {hostname}")
    print(f"  Detected site : {site.display_name}")

    if site.name == GENERIC_SITE.name:
        print("  Site config   : no known site-specific config")
    elif site.defaults:
        print("  Site config   : known site with special defaults")
    else:
        print("  Site config   : known site, no defaults configured")

    if applied:
        print(f"  Applied       : {', '.join(applied)}")
    else:
        print("  Applied       : none")

    print("=" * 60)