"""Configuration loading and typed config dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class CrawlerSettings:
    concurrency: int = 8
    page_timeout_ms: int = 45000
    consent_timeout_ms: int = 15000
    post_consent_wait_ms: int = 60000  # 60s after consent — trackers cascade for a long time
    final_dwell_ms: int = 15000        # additional wait after scrolling
    scroll_delay_ms: int = 1500
    inter_site_delay_ms: int = 1000
    max_retries: int = 3
    screenshot: bool = False
    headless: bool = True


@dataclass
class Geolocation:
    latitude: float = 50.0755
    longitude: float = 14.4378


@dataclass
class Viewport:
    width: int = 1920
    height: int = 1080


@dataclass
class BrowserSettings:
    locale: str = "cs-CZ"
    timezone: str = "Europe/Prague"
    geolocation: Geolocation = field(default_factory=Geolocation)
    viewport: Viewport = field(default_factory=Viewport)
    user_agent: str | None = None


@dataclass
class DatabaseSettings:
    path: str = "data/footprint.db"


@dataclass
class ConsentPatterns:
    accept: list[str] = field(default_factory=lambda: [
        "přijmout vše", "souhlasím", "accept all", "přijmout",
        "souhlasím se vším", "povolit vše", "Souhlasím", "Rozumím",
        "Přijmout a zavřít", "Přijmout cookies",
    ])
    reject: list[str] = field(default_factory=lambda: [
        "odmítnout vše", "odmítnout", "pouze nezbytné", "reject all",
        "nesouhlasím", "pouze technické", "jen nezbytné", "Odmítnout vše",
    ])


@dataclass
class OutputSettings:
    export_dir: str = "output/"
    screenshot_dir: str = "output/screenshots/"


@dataclass
class CrawlerConfig:
    project_root: Path = field(default_factory=lambda: Path.cwd())
    crawler: CrawlerSettings = field(default_factory=CrawlerSettings)
    browser: BrowserSettings = field(default_factory=BrowserSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    consent_patterns: ConsentPatterns = field(default_factory=ConsentPatterns)
    output: OutputSettings = field(default_factory=OutputSettings)
    sites_file: str = "data/sites/czech_top_100.csv"

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path against the project root."""
        p = Path(relative_path)
        if p.is_absolute():
            return p
        return self.project_root / p


def _build_nested(cls, data: dict):
    """Recursively build a dataclass from a dict, ignoring unknown keys."""
    if data is None:
        return cls()
    fieldnames = {f.name for f in cls.__dataclass_fields__.values()}
    filtered = {}
    for key, val in data.items():
        if key not in fieldnames:
            continue
        f = cls.__dataclass_fields__[key]
        # If the field type is itself a dataclass, recurse
        if hasattr(f.type, "__dataclass_fields__") if isinstance(f.type, type) else False:
            filtered[key] = _build_nested(f.type, val) if isinstance(val, dict) else val
        else:
            filtered[key] = val
    return cls(**filtered)


def load_config(path: str | Path) -> CrawlerConfig:
    """Load configuration from a YAML file, falling back to defaults."""
    config_path = Path(path)
    project_root = config_path.parent

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
    else:
        raw = {}

    config = CrawlerConfig(
        project_root=project_root,
        crawler=_build_nested(CrawlerSettings, raw.get("crawler")),
        browser=BrowserSettings(
            locale=raw.get("browser", {}).get("locale", "cs-CZ"),
            timezone=raw.get("browser", {}).get("timezone", "Europe/Prague"),
            geolocation=_build_nested(Geolocation, raw.get("browser", {}).get("geolocation")),
            viewport=_build_nested(Viewport, raw.get("browser", {}).get("viewport")),
            user_agent=raw.get("browser", {}).get("user_agent"),
        ),
        database=_build_nested(DatabaseSettings, raw.get("database")),
        consent_patterns=_build_nested(ConsentPatterns, raw.get("consent_patterns")),
        output=_build_nested(OutputSettings, raw.get("output")),
        sites_file=raw.get("sites_file", "data/sites/czech_top_100.csv"),
    )

    return config
