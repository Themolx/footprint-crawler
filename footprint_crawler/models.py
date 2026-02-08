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
