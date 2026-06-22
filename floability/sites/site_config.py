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

    if applied:
        print(
            f"[site_config] Applied defaults for {site.display_name}: "
            f"{', '.join(applied)}"
        )
    elif site.name == GENERIC_SITE.name:
        print("[site_config] No site defaults applied.")
    else:
        print(f"[site_config] Detected {site.display_name}; no site defaults applied.")

    return args