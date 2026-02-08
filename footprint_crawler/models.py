"""Data models for the Footprint Crawler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConsentMode(str, Enum):
    IGNORE = "ignore"
    ACCEPT = "accept"
    REJECT = "reject"


class CrawlStatus(str, Enum):
    SUCCESS = "success"
    TIMEOUT = "timeout"
    ERROR = "error"
    BLOCKED = "blocked"


class FingerprintSeverity(str, Enum):
    NONE = "none"
    PASSIVE = "passive"
    ACTIVE = "active"
    AGGRESSIVE = "aggressive"


class ResourceCategory(str, Enum):
    CONTENT_1P = "content_1p"
    CDN = "cdn"
    TRACKER = "tracker"
    AD = "ad"
    FUNCTIONAL_3P = "functional_3p"
    UNKNOWN_3P = "unknown_3p"


@dataclass
class SiteInfo:
    url: str
    domain: str
    category: str | None = None
    rank_cz: int | None = None


@dataclass
class RequestRecord:
    url: str
    domain: str
    method: str
    resource_type: str
    is_third_party: bool
    tracker_entity: str | None = None
    tracker_category: str | None = None
    status_code: int | None = None
    response_size_bytes: int | None = None
    timing_ms: float | None = None
    timestamp: str = ""
    resource_category: str | None = None
    content_type: str | None = None


@dataclass
class CookieRecord:
    name: str
    domain: str
    value_hash: str
    path: str
    expires_at: str | None = None
    lifetime_days: float | None = None
    is_secure: bool = False
    is_http_only: bool = False
    same_site: str | None = None
    is_session: bool = True
    is_tracking_cookie: bool = False
    tracker_entity: str | None = None
    set_before_consent: bool = False
    timestamp: str = ""


@dataclass
class ConsentInfo:
    banner_detected: bool = False
    cmp_platform: str | None = None
    button_text: str | None = None
    action_taken: bool = False


# ── Phase 2: Fingerprinting ──

@dataclass
class FingerprintEvent:
    api: str
    method: str
    timestamp: str = ""
    call_stack_domain: str | None = None
    tracker_entity: str | None = None
    details: str | None = None


@dataclass
class FingerprintResult:
    severity: FingerprintSeverity = FingerprintSeverity.NONE
    events: list[FingerprintEvent] = field(default_factory=list)
    canvas_detected: bool = False
    webgl_detected: bool = False
    audio_detected: bool = False
    font_detected: bool = False
    navigator_detected: bool = False
    storage_detected: bool = False
    unique_apis: int = 0
    unique_entities: int = 0


# ── Phase 2: Ad Detection ──

@dataclass
class AdElement:
    selector: str
    tag_name: str
    ad_id: str | None = None
    ad_class: str | None = None
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    is_visible: bool = True
    is_iframe: bool = False
    iframe_src: str | None = None
    iab_size: str | None = None
    ad_network: str | None = None


@dataclass
class AdDetectionResult:
    ads: list[AdElement] = field(default_factory=list)
    total_ad_count: int = 0
    visible_ad_count: int = 0
    ad_density: float = 0.0
    total_ad_area_px: int = 0
    iab_standard_count: int = 0


# ── Phase 2: Ad Capture ──

@dataclass
class AdCapture:
    ad_index: int
    screenshot_path: str | None = None
    metadata_path: str | None = None
    width: int = 0
    height: int = 0
    capture_method: str = "failed"


@dataclass
class AdCaptureResult:
    captures: list[AdCapture] = field(default_factory=list)
    total_captured: int = 0
    total_failed: int = 0


# ── Phase 2: Resource Weight ──

@dataclass
class ResourceWeightSummary:
    total_bytes: int = 0
    content_1p_bytes: int = 0
    cdn_bytes: int = 0
    tracker_bytes: int = 0
    ad_bytes: int = 0
    functional_3p_bytes: int = 0
    unknown_3p_bytes: int = 0
    total_requests_with_size: int = 0


# ── Main result ──

@dataclass
class CrawlResult:
    site: SiteInfo
    consent_mode: ConsentMode
    status: CrawlStatus
    started_at: str = ""
    completed_at: str = ""
    final_url: str | None = None
    page_title: str | None = None
    load_time_ms: int | None = None
    requests: list[RequestRecord] = field(default_factory=list)
    cookies: list[CookieRecord] = field(default_factory=list)
    consent_info: ConsentInfo | None = None
    screenshot_path: str | None = None
    error: str | None = None
    fingerprint_result: FingerprintResult | None = None
    ad_detection_result: AdDetectionResult | None = None
    ad_capture_result: AdCaptureResult | None = None
    resource_weight: ResourceWeightSummary | None = None
