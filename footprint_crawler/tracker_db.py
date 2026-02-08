"""Tracker entity identification and classification.

Combines a built-in tracker database (major global + Czech-specific trackers)
with optional Disconnect.me JSON loading for comprehensive coverage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .utils import extract_registered_domain

logger = logging.getLogger(__name__)

# Built-in tracker database: domain -> (entity, category)
# Categories: advertising, analytics, social, fingerprinting, cdn, other
BUILTIN_TRACKERS: dict[str, tuple[str, str]] = {
    # Google
    "google-analytics.com": ("Google", "analytics"),
    "googletagmanager.com": ("Google", "analytics"),
    "googleadservices.com": ("Google", "advertising"),
    "googlesyndication.com": ("Google", "advertising"),
    "doubleclick.net": ("Google", "advertising"),
    "googletagservices.com": ("Google", "advertising"),
    "google.com": ("Google", "analytics"),
    "googleapis.com": ("Google", "cdn"),
    "gstatic.com": ("Google", "cdn"),
    "youtube.com": ("Google", "social"),
    "ytimg.com": ("Google", "cdn"),
    "ggpht.com": ("Google", "cdn"),
    "googlevideo.com": ("Google", "cdn"),
    "googleusercontent.com": ("Google", "cdn"),
    # Meta / Facebook
    "facebook.com": ("Meta", "social"),
    "facebook.net": ("Meta", "advertising"),
    "fbcdn.net": ("Meta", "cdn"),
    "instagram.com": ("Meta", "social"),
    "connect.facebook.net": ("Meta", "social"),
    "fbsbx.com": ("Meta", "social"),
    # Microsoft
    "bing.com": ("Microsoft", "advertising"),
    "msn.com": ("Microsoft", "advertising"),
    "microsoft.com": ("Microsoft", "analytics"),
    "clarity.ms": ("Microsoft", "analytics"),
    "msecnd.net": ("Microsoft", "cdn"),
    # Amazon
    "amazon-adsystem.com": ("Amazon", "advertising"),
    "amazonaws.com": ("Amazon", "cdn"),
    "cloudfront.net": ("Amazon", "cdn"),
    # Twitter / X
    "twitter.com": ("Twitter/X", "social"),
    "t.co": ("Twitter/X", "social"),
    "twimg.com": ("Twitter/X", "cdn"),
    # Adobe
    "demdex.net": ("Adobe", "advertising"),
    "omtrdc.net": ("Adobe", "analytics"),
    "2o7.net": ("Adobe", "analytics"),
    "adobe.com": ("Adobe", "analytics"),
    "typekit.net": ("Adobe", "cdn"),
    # Criteo
    "criteo.com": ("Criteo", "advertising"),
    "criteo.net": ("Criteo", "advertising"),
    # Taboola
    "taboola.com": ("Taboola", "advertising"),
    # Outbrain
    "outbrain.com": ("Outbrain", "advertising"),
    # AppNexus / Xandr
    "adnxs.com": ("Xandr", "advertising"),
    # The Trade Desk
    "adsrvr.org": ("The Trade Desk", "advertising"),
    # Hotjar
    "hotjar.com": ("Hotjar", "analytics"),
    # HubSpot
    "hubspot.com": ("HubSpot", "analytics"),
    "hsforms.com": ("HubSpot", "analytics"),
    "hs-analytics.net": ("HubSpot", "analytics"),
    # Quantcast
    "quantserve.com": ("Quantcast", "advertising"),
    "quantcount.com": ("Quantcast", "analytics"),
    # Oracle / BlueKai
    "bluekai.com": ("Oracle", "advertising"),
    "addthis.com": ("Oracle", "social"),
    # Cloudflare
    "cloudflare.com": ("Cloudflare", "cdn"),
    "cloudflareinsights.com": ("Cloudflare", "analytics"),
    # New Relic
    "newrelic.com": ("New Relic", "analytics"),
    "nr-data.net": ("New Relic", "analytics"),
    # Sentry
    "sentry.io": ("Sentry", "analytics"),
    # Pinterest
    "pinimg.com": ("Pinterest", "social"),
    "pinterest.com": ("Pinterest", "social"),
    # LinkedIn
    "linkedin.com": ("LinkedIn", "social"),
    "licdn.com": ("LinkedIn", "cdn"),
    # Snap
    "snapchat.com": ("Snap", "social"),
    "sc-static.net": ("Snap", "cdn"),
    # TikTok
    "tiktok.com": ("TikTok", "social"),
    "byteoversea.com": ("TikTok", "analytics"),
    # Yandex
    "yandex.ru": ("Yandex", "analytics"),
    "mc.yandex.ru": ("Yandex", "analytics"),
    # --- Czech-specific trackers ---
    # Seznam.cz
    "sklik.cz": ("Seznam.cz", "advertising"),
    "imedia.cz": ("Seznam.cz", "advertising"),
    "im.cz": ("Seznam.cz", "advertising"),
    "sssp.cz": ("Seznam.cz", "advertising"),
    "seznam.cz": ("Seznam.cz", "analytics"),
    "toplist.cz": ("Seznam.cz", "analytics"),
    # Heureka Group
    "heureka.cz": ("Heureka Group", "analytics"),
    "glami.cz": ("Heureka Group", "analytics"),
    "glami.eco": ("Heureka Group", "analytics"),
    # Gemius
    "gemius.com": ("Gemius", "analytics"),
    "gemius.pl": ("Gemius", "analytics"),
    "gemiuscdn.com": ("Gemius", "analytics"),
    # Adform
    "adform.net": ("Adform", "advertising"),
    "adform.com": ("Adform", "advertising"),
    "adformdsp.net": ("Adform", "advertising"),
    # R2B2
    "r2b2.cz": ("R2B2", "advertising"),
    "r2b2.io": ("R2B2", "advertising"),
    # Impression Media
    "impressionmedia.cz": ("Impression Media", "advertising"),
    # Mediaresearch / NetMonitor
    "netmonitor.cz": ("Mediaresearch", "analytics"),
    "mediaresearch.cz": ("Mediaresearch", "analytics"),
    # Zboží.cz (Seznam subsidiary)
    "zbozi.cz": ("Seznam.cz", "analytics"),
    # LiveChat / Smartsupp (Czech-origin)
    "smartsupp.com": ("Smartsupp", "analytics"),
    # Exponea / Bloomreach
    "exponea.com": ("Bloomreach", "analytics"),
    "bloomreach.com": ("Bloomreach", "analytics"),
}

# Known tracking cookie name patterns
TRACKING_COOKIE_PATTERNS: list[str] = [
    # Google Analytics
    "_ga", "_gid", "_gat", "_gcl_au", "_gac_",
    # Google Ads
    "IDE", "NID", "DSID", "1P_JAR", "ANID", "CONSENT",
    # Facebook / Meta
    "_fbp", "_fbc", "fr", "datr", "sb",
    # Microsoft
    "_uetsid", "_uetvid", "MUID", "_clck", "_clsk",
    # Hotjar
    "_hjid", "_hjSession", "_hjSessionUser", "_hjAbsoluteSessionInProgress",
    # HubSpot
    "hubspotutk", "__hssc", "__hssrc", "__hstc",
    # UTM / general
    "__utm",
    # Criteo
    "cto_bundle", "cto_bidid",
    # Adobe
    "s_cc", "s_sq", "s_vi",
    # Seznam / Sklik
    "sid", "lps",
    # Generic patterns
    "_pk_id", "_pk_ses",  # Matomo/Piwik
]


def _is_tracking_cookie_by_name(name: str) -> bool:
    """Check if a cookie name matches known tracking patterns."""
    name_lower = name.lower()
    for pattern in TRACKING_COOKIE_PATTERNS:
        pattern_lower = pattern.lower()
        if name_lower == pattern_lower or name_lower.startswith(pattern_lower):
            return True
    return False


class TrackerDatabase:
    """Tracker classification database.

    Combines built-in tracker knowledge with optional Disconnect.me
    and Czech-specific tracker JSON files.
    """

    def __init__(
        self,
        disconnect_path: str | Path | None = None,
        czech_trackers_path: str | Path | None = None,
    ):
        # domain -> (entity, category)
        self._lookup: dict[str, tuple[str, str]] = dict(BUILTIN_TRACKERS)
        self._load_count = len(self._lookup)

        if disconnect_path:
            self._load_disconnect(Path(disconnect_path))

        if czech_trackers_path:
            self._load_czech_trackers(Path(czech_trackers_path))

        logger.info("TrackerDatabase loaded with %d domain entries", len(self._lookup))

    def _load_disconnect(self, path: Path) -> None:
        """Load Disconnect.me services.json format."""
        if not path.exists():
            logger.warning("Disconnect.me file not found: %s", path)
            return
        try:
            with open(path) as f:
                data = json.load(f)
            categories = data.get("categories", data)
            count = 0
            for category_name, entries in categories.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    for entity_name, entity_data in entry.items():
                        if not isinstance(entity_data, dict):
                            continue
                        for domain_list in entity_data.values():
                            if isinstance(domain_list, list):
                                for domain in domain_list:
                                    if isinstance(domain, str) and "." in domain:
                                        self._lookup[domain] = (entity_name, category_name.lower())
                                        count += 1
            logger.info("Loaded %d domains from Disconnect.me", count)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse Disconnect.me file: %s", e)

    def _load_czech_trackers(self, path: Path) -> None:
        """Load Czech-specific trackers JSON."""
        if not path.exists():
            logger.warning("Czech trackers file not found: %s", path)
            return
        try:
            with open(path) as f:
                data = json.load(f)
            count = 0
            for _key, entry in data.items():
                entity_name = entry.get("name", _key)
                category = entry.get("category", "other")
                for domain in entry.get("domains", []):
                    self._lookup[domain] = (entity_name, category)
                    count += 1
            logger.info("Loaded %d domains from Czech trackers file", count)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse Czech trackers file: %s", e)

    def classify(self, domain: str) -> tuple[str | None, str | None]:
        """Classify a domain as a tracker.

        Returns (entity_name, category) or (None, None) if unknown.
        Walks up the domain hierarchy: ads.doubleclick.net -> doubleclick.net
        """
        # Try exact match first
        if domain in self._lookup:
            return self._lookup[domain]

        # Walk up parent domains
        reg_domain = extract_registered_domain(domain)
        if reg_domain in self._lookup:
            return self._lookup[reg_domain]

        # Try removing subdomains one level at a time
        parts = domain.split(".")
        for i in range(1, len(parts)):
            parent = ".".join(parts[i:])
            if parent in self._lookup:
                return self._lookup[parent]

        return (None, None)

    def is_tracking_cookie(self, name: str, domain: str) -> bool:
        """Check if a cookie is likely a tracking cookie.

        Checks both the cookie name patterns and the cookie domain.
        """
        if _is_tracking_cookie_by_name(name):
            return True
        entity, _category = self.classify(domain.lstrip("."))
        return entity is not None

    @property
    def domain_count(self) -> int:
        return len(self._lookup)
