"""Fingerprinting detection module.

Injects monitoring hooks into page JavaScript before any site code executes,
then collects and classifies fingerprinting events after the crawl dwell period.

Detects: canvas, WebGL, AudioContext, navigator/screen enumeration,
font probing, and storage probing fingerprinting techniques.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from playwright.async_api import Page

from .config import FingerprintingSettings
from .models import FingerprintEvent, FingerprintResult, FingerprintSeverity
from .tracker_db import TrackerDatabase
from .utils import extract_registered_domain

logger = logging.getLogger(__name__)

# URL pattern to extract domains from JS stack traces
_URL_RE = re.compile(r"https?://([^/\s:]+)")

# Active fingerprinting APIs (canvas, webgl, audio are the primary active vectors)
_ACTIVE_APIS = {"canvas", "webgl", "audio"}

# JavaScript init script injected before any page code executes.
# Hooks browser APIs and logs calls to window.__fp_log.
_FP_INIT_SCRIPT = """
(function() {
    'use strict';
    if (window.__fp_log) return;  // already injected
    window.__fp_log = [];

    function _log(api, method, details) {
        var stack = '';
        try {
            stack = new Error().stack || '';
            // Keep first 3 caller frames, skip the hook itself
            stack = stack.split('\\n').slice(2, 5).join(' | ');
        } catch(e) {}
        window.__fp_log.push({
            api: api,
            method: method,
            timestamp: Date.now(),
            stack: stack,
            details: details || ''
        });
    }

    // ── Canvas fingerprinting ──
    try {
        var origToDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function() {
            _log('canvas', 'toDataURL', this.width + 'x' + this.height);
            return origToDataURL.apply(this, arguments);
        };

        var origToBlob = HTMLCanvasElement.prototype.toBlob;
        HTMLCanvasElement.prototype.toBlob = function() {
            _log('canvas', 'toBlob', this.width + 'x' + this.height);
            return origToBlob.apply(this, arguments);
        };

        var origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
        CanvasRenderingContext2D.prototype.getImageData = function() {
            _log('canvas', 'getImageData',
                 arguments[0] + ',' + arguments[1] + ',' + arguments[2] + ',' + arguments[3]);
            return origGetImageData.apply(this, arguments);
        };
    } catch(e) {}

    // ── WebGL fingerprinting ──
    try {
        var glContexts = [
            typeof WebGLRenderingContext !== 'undefined' ? WebGLRenderingContext : null,
            typeof WebGL2RenderingContext !== 'undefined' ? WebGL2RenderingContext : null,
        ];
        // Parameter constants to watch for
        var watchParams = {
            0x1F00: 'VENDOR', 0x1F01: 'RENDERER', 0x1F02: 'VERSION',
            0x9245: 'UNMASKED_VENDOR_WEBGL', 0x9246: 'UNMASKED_RENDERER_WEBGL'
        };

        glContexts.forEach(function(Ctx) {
            if (!Ctx) return;

            var origGetParam = Ctx.prototype.getParameter;
            Ctx.prototype.getParameter = function(pname) {
                if (watchParams[pname]) {
                    _log('webgl', 'getParameter', watchParams[pname]);
                }
                return origGetParam.apply(this, arguments);
            };

            var origGetExt = Ctx.prototype.getExtension;
            Ctx.prototype.getExtension = function(name) {
                _log('webgl', 'getExtension', name);
                return origGetExt.apply(this, arguments);
            };

            var origGetSupported = Ctx.prototype.getSupportedExtensions;
            Ctx.prototype.getSupportedExtensions = function() {
                _log('webgl', 'getSupportedExtensions', '');
                return origGetSupported.apply(this, arguments);
            };
        });
    } catch(e) {}

    // ── AudioContext fingerprinting ──
    try {
        if (typeof AudioContext !== 'undefined') {
            var OrigAC = AudioContext;
            window.AudioContext = function() {
                _log('audio', 'AudioContext', 'constructor');
                return new OrigAC();
            };
            window.AudioContext.prototype = OrigAC.prototype;
            Object.defineProperty(window.AudioContext, 'name', {value: 'AudioContext'});
        }

        if (typeof OfflineAudioContext !== 'undefined') {
            var OrigOAC = OfflineAudioContext;
            window.OfflineAudioContext = function(channels, length, sampleRate) {
                _log('audio', 'OfflineAudioContext', channels + ',' + length + ',' + sampleRate);
                return new OrigOAC(channels, length, sampleRate);
            };
            window.OfflineAudioContext.prototype = OrigOAC.prototype;
            Object.defineProperty(window.OfflineAudioContext, 'name', {value: 'OfflineAudioContext'});
        }

        if (typeof AnalyserNode !== 'undefined') {
            var origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
            if (origGetFloat) {
                AnalyserNode.prototype.getFloatFrequencyData = function(array) {
                    _log('audio', 'getFloatFrequencyData', '');
                    return origGetFloat.apply(this, arguments);
                };
            }
        }
    } catch(e) {}

    // ── Navigator/Screen enumeration ──
    try {
        var navProps = [
            'hardwareConcurrency', 'deviceMemory', 'languages', 'platform'
        ];
        navProps.forEach(function(prop) {
            var desc = Object.getOwnPropertyDescriptor(Navigator.prototype, prop) ||
                       Object.getOwnPropertyDescriptor(navigator, prop);
            if (desc && desc.get) {
                var origGet = desc.get;
                Object.defineProperty(Navigator.prototype, prop, {
                    get: function() {
                        _log('navigator', prop, '');
                        return origGet.call(this);
                    },
                    configurable: true
                });
            }
        });

        // navigator.plugins & navigator.mimeTypes
        ['plugins', 'mimeTypes'].forEach(function(prop) {
            var desc = Object.getOwnPropertyDescriptor(Navigator.prototype, prop);
            if (desc && desc.get) {
                var origGet = desc.get;
                Object.defineProperty(Navigator.prototype, prop, {
                    get: function() {
                        _log('navigator', prop, '');
                        return origGet.call(this);
                    },
                    configurable: true
                });
            }
        });

        // screen properties
        var screenProps = ['colorDepth', 'pixelDepth'];
        screenProps.forEach(function(prop) {
            var desc = Object.getOwnPropertyDescriptor(Screen.prototype, prop) ||
                       Object.getOwnPropertyDescriptor(screen, prop);
            if (desc && desc.get) {
                var origGet = desc.get;
                Object.defineProperty(Screen.prototype, prop, {
                    get: function() {
                        _log('navigator', 'screen.' + prop, '');
                        return origGet.call(this);
                    },
                    configurable: true
                });
            }
        });

        // navigator.connection
        if (navigator.connection) {
            var connProps = ['effectiveType', 'downlink', 'rtt', 'saveData'];
            connProps.forEach(function(prop) {
                var desc = Object.getOwnPropertyDescriptor(
                    Object.getPrototypeOf(navigator.connection), prop
                );
                if (desc && desc.get) {
                    var origGet = desc.get;
                    Object.defineProperty(navigator.connection, prop, {
                        get: function() {
                            _log('navigator', 'connection.' + prop, '');
                            return origGet.call(this);
                        },
                        configurable: true
                    });
                }
            });
        }
    } catch(e) {}

    // ── Font fingerprinting ──
    try {
        if (document.fonts && document.fonts.check) {
            var origFontCheck = document.fonts.check.bind(document.fonts);
            document.fonts.check = function(font, text) {
                _log('font', 'fonts.check', font);
                return origFontCheck(font, text);
            };
        }
    } catch(e) {}

    // ── Storage probing ──
    try {
        var origGetItem = Storage.prototype.getItem;
        var storageCallCount = 0;
        Storage.prototype.getItem = function(key) {
            storageCallCount++;
            // Only log rapid access patterns (fingerprint probing)
            if (storageCallCount <= 5) {
                _log('storage', 'getItem', key);
            }
            return origGetItem.apply(this, arguments);
        };

        if (typeof indexedDB !== 'undefined') {
            var origIDBOpen = indexedDB.open.bind(indexedDB);
            indexedDB.open = function(name, version) {
                _log('storage', 'indexedDB.open', name);
                return origIDBOpen(name, version);
            };
        }
    } catch(e) {}
})();
"""


class FingerprintDetector:
    """Detects browser fingerprinting attempts during page crawl."""

    def __init__(self, config: FingerprintingSettings, tracker_db: TrackerDatabase):
        self._config = config
        self._tracker_db = tracker_db

    async def inject_monitoring(self, page: Page) -> None:
        """Inject fingerprint monitoring hooks. Call BEFORE page.goto()."""
        if not self._config.enabled:
            return
        await page.add_init_script(_FP_INIT_SCRIPT)

    async def collect_results(self, page: Page) -> FingerprintResult:
        """Collect and classify fingerprint events. Call AFTER dwell."""
        if not self._config.enabled:
            return FingerprintResult()

        try:
            raw_events = await page.evaluate("() => window.__fp_log || []")
        except Exception as e:
            logger.debug("Failed to collect fingerprint events: %s", e)
            return FingerprintResult()

        events: list[FingerprintEvent] = []
        apis_seen: set[str] = set()
        entities_seen: set[str] = set()

        for raw in raw_events:
            api = raw.get("api", "")
            method = raw.get("method", "")
            stack = raw.get("stack", "")
            domain = self._extract_domain_from_stack(stack)
            entity = None
            if domain:
                entity, _ = self._tracker_db.classify(domain)

            ts = raw.get("timestamp", "")
            if isinstance(ts, (int, float)):
                try:
                    ts = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    ts = str(ts)

            events.append(FingerprintEvent(
                api=api,
                method=method,
                timestamp=str(ts),
                call_stack_domain=domain,
                tracker_entity=entity,
                details=raw.get("details"),
            ))
            apis_seen.add(api)
            if entity:
                entities_seen.add(entity)

        severity = self._classify_severity(apis_seen, len(events))

        return FingerprintResult(
            severity=severity,
            events=events,
            canvas_detected="canvas" in apis_seen,
            webgl_detected="webgl" in apis_seen,
            audio_detected="audio" in apis_seen,
            font_detected="font" in apis_seen,
            navigator_detected="navigator" in apis_seen,
            storage_detected="storage" in apis_seen,
            unique_apis=len(apis_seen),
            unique_entities=len(entities_seen),
        )

    def _extract_domain_from_stack(self, stack: str) -> str | None:
        """Extract the first third-party domain from a JS stack trace."""
        if not stack:
            return None
        matches = _URL_RE.findall(stack)
        for hostname in matches:
            try:
                reg_domain = extract_registered_domain(hostname)
                if reg_domain:
                    return reg_domain
            except Exception:
                continue
        return None

    @staticmethod
    def _classify_severity(apis: set[str], event_count: int) -> FingerprintSeverity:
        """Classify fingerprinting severity based on detected APIs.

        - none: no fingerprint-relevant events
        - passive: only navigator/screen reads (common in analytics)
        - active: single active technique (canvas OR webgl OR audio)
        - aggressive: multiple active techniques combined
        """
        if event_count == 0:
            return FingerprintSeverity.NONE

        active_detected = apis & _ACTIVE_APIS
        non_active = apis - _ACTIVE_APIS

        if not active_detected:
            # Only passive APIs (navigator, font, storage)
            return FingerprintSeverity.PASSIVE

        if len(active_detected) >= 2:
            return FingerprintSeverity.AGGRESSIVE

        # Single active technique
        return FingerprintSeverity.ACTIVE
