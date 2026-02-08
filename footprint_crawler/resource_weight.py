"""Third-party resource weight classification and measurement.

Classifies each network request as first-party content, CDN, tracker,
advertising, functional third-party, or unknown third-party. Aggregates
byte-level statistics to answer: how much bandwidth does tracking consume?
"""

from __future__ import annotations

import logging

from .config import ResourceWeightSettings
from .models import RequestRecord, ResourceCategory, ResourceWeightSummary
from .tracker_db import TrackerDatabase

logger = logging.getLogger(__name__)

# Known CDN domains that serve first-party content
CDN_DOMAINS = frozenset({
    "cdnjs.cloudflare.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "ajax.googleapis.com",
    "maxcdn.bootstrapcdn.com",
    "stackpath.bootstrapcdn.com",
    "code.jquery.com",
})

# CDN domain patterns (substring match)
CDN_PATTERNS = (
    "cloudfront.net",
    "akamaized.net",
    "akamai.net",
    "fastly.net",
    "azureedge.net",
    "cloudflare.com",
)

# Functional third-party services (not tracking)
FUNCTIONAL_3P_DOMAINS = frozenset({
    "recaptcha.net",
    "hcaptcha.com",
    "stripe.com",
    "paypal.com",
    "braintreegateway.com",
    "gstatic.com",
    "twimg.com",
})

FUNCTIONAL_3P_PATTERNS = (
    "maps.google",
    "maps.googleapis",
    "recaptcha",
    "hcaptcha",
)

# Ad-serving domain patterns (supplement to tracker_db advertising category)
AD_DOMAIN_PATTERNS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "amazon-adsystem.com",
    "adnxs.com",
    "adsrvr.org",
)


class ResourceWeightClassifier:
    """Classifies requests into resource categories and aggregates byte totals."""

    def __init__(self, config: ResourceWeightSettings, tracker_db: TrackerDatabase):
        self._config = config
        self._tracker_db = tracker_db

    def classify_request(self, record: RequestRecord, site_reg_domain: str) -> str:
        """Classify a single request into a resource category."""
        if not record.is_third_party:
            return ResourceCategory.CONTENT_1P.value

        domain = record.domain or ""
        entity, category = self._tracker_db.classify(domain)

        if category == "advertising":
            return ResourceCategory.AD.value
        if category in ("analytics", "fingerprinting", "social"):
            return ResourceCategory.TRACKER.value

        if domain in CDN_DOMAINS:
            return ResourceCategory.CDN.value
        for pattern in CDN_PATTERNS:
            if pattern in domain:
                return ResourceCategory.CDN.value

        if domain in FUNCTIONAL_3P_DOMAINS:
            return ResourceCategory.FUNCTIONAL_3P.value
        for pattern in FUNCTIONAL_3P_PATTERNS:
            if pattern in domain:
                return ResourceCategory.FUNCTIONAL_3P.value

        for pattern in AD_DOMAIN_PATTERNS:
            if pattern in domain:
                return ResourceCategory.AD.value

        if entity:
            return ResourceCategory.TRACKER.value

        return ResourceCategory.UNKNOWN_3P.value

    @staticmethod
    def aggregate(requests: list[RequestRecord]) -> ResourceWeightSummary:
        """Compute byte-level summary across all requests."""
        summary = ResourceWeightSummary()
        for r in requests:
            size = r.response_size_bytes or 0
            summary.total_bytes += size
            if size > 0:
                summary.total_requests_with_size += 1
            cat = r.resource_category or ResourceCategory.UNKNOWN_3P.value
            if cat == ResourceCategory.CONTENT_1P.value:
                summary.content_1p_bytes += size
            elif cat == ResourceCategory.CDN.value:
                summary.cdn_bytes += size
            elif cat == ResourceCategory.TRACKER.value:
                summary.tracker_bytes += size
            elif cat == ResourceCategory.AD.value:
                summary.ad_bytes += size
            elif cat == ResourceCategory.FUNCTIONAL_3P.value:
                summary.functional_3p_bytes += size
            else:
                summary.unknown_3p_bytes += size
        return summary
