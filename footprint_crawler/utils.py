"""Utility functions for domain extraction, hashing, and URL normalization."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse

import tldextract


def extract_registered_domain(url_or_domain: str) -> str:
    """Extract the registered domain from a URL or domain string.

    Examples:
        'https://ads.google.com/page' -> 'google.com'
        'tracker.cdn.example.co.uk' -> 'example.co.uk'
    """
    ext = tldextract.extract(url_or_domain)
    if ext.registered_domain:
        return ext.registered_domain
    # Fallback for IPs or unusual domains
    try:
        parsed = urlparse(url_or_domain if "://" in url_or_domain else f"https://{url_or_domain}")
        return parsed.hostname or url_or_domain
    except Exception:
        return url_or_domain


def extract_hostname(url: str) -> str:
    """Extract hostname from a URL."""
    try:
        parsed = urlparse(url)
        return parsed.hostname or ""
    except Exception:
        return ""


def is_third_party(request_domain: str, page_domain: str) -> bool:
    """Check if a request domain is third-party relative to the page domain."""
    return extract_registered_domain(request_domain) != extract_registered_domain(page_domain)


def hash_cookie_value(value: str) -> str:
    """SHA-256 hash of a cookie value for privacy-safe storage."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url: str) -> str:
    """Ensure URL has a scheme and strip trailing slash."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    return url.rstrip("/")
