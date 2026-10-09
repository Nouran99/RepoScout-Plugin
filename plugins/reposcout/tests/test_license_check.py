"""Tests for LicenseChecker middleware."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from mcp_server.middleware.license_check import (
    _FREE_DAILY_LIMIT,
    LicenseChecker,
    LicenseError,
)

BACKEND = "http://localhost:8000"
VALID_KEY = "nk_test_valid_key_abc123"
_VALIDATE_URL = re.compile(r"http://localhost:8000/api/v1/reposcout/validate-key")
_USAGE_LOG_URL = re.compile(r"http://localhost:8000/api/v1/reposcout/usage")


# ── Fixture: isolated usage file ─────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_usage_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect the usage file to a temp dir so tests don't touch ~/.reposcout."""
    fake_usage = tmp_path / ".reposcout" / "usage.json"
    monkeypatch.setattr(
        "mcp_server.middleware.license_check._USAGE_FILE", fake_usage
    )
    yield fake_usage


# ── 1. Free tier: allows up to 10 calls per day ───────────────────────────────

class TestFreeTierAllows10:
    def test_first_call_allowed(self):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        result = checker._check_local()
        assert result["allowed"] is True
        assert result["tier"] == "free"
        assert result["source"] == "local"

    def test_nine_calls_all_allowed(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        today = str(date.today())
        # Pre-populate with 9 calls
        isolate_usage_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_usage_file.write_text(json.dumps({today: 9}))

        result = checker._check_local()
        assert result["allowed"] is True
        assert result["calls_today"] == 9

    def test_limit_reported_correctly(self):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        result = checker._check_local()
        assert result["daily_limit"] == _FREE_DAILY_LIMIT


# ── 2. Free tier: blocks after 10 calls ──────────────────────────────────────

class TestFreeTierBlocksAfter10:
    def test_blocks_at_exactly_10(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        today = str(date.today())
        isolate_usage_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_usage_file.write_text(json.dumps({today: 10}))

        with pytest.raises(LicenseError) as exc_info:
            checker._check_local()
        assert "Free tier limit reached" in str(exc_info.value)
        assert "10" in str(exc_info.value)

    def test_blocks_above_10(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        today = str(date.today())
        isolate_usage_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_usage_file.write_text(json.dumps({today: 50}))

        with pytest.raises(LicenseError):
            checker._check_local()

    def test_increment_persists(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        checker.increment_local_usage()
        checker.increment_local_usage()

        data = json.loads(isolate_usage_file.read_text())
        today = str(date.today())
        assert data[today] == 2

    def test_yesterday_count_does_not_block_today(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        # Simulate 10 calls yesterday
        isolate_usage_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_usage_file.write_text(json.dumps({"2000-01-01": 10}))

        result = checker._check_local()  # should not raise
        assert result["allowed"] is True


# ── 3. Pro key: valid response ────────────────────────────────────────────────

class TestProKeyValid:
    async def test_returns_allowed_true(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 5, "daily_limit": None},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        result = await checker.check()
        assert result["allowed"] is True
        assert result["tier"] == "pro"
        assert result["source"] == "backend"

    async def test_sends_x_api_key_header(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 0, "daily_limit": None},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        await checker.check()

        request = httpx_mock.get_request()
        assert request.headers.get("x-api-key") == VALID_KEY

    async def test_team_tier_allowed(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "team", "calls_today": 200, "daily_limit": None},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        result = await checker.check()
        assert result["tier"] == "team"


# ── 4. Invalid key ────────────────────────────────────────────────────────────

class TestInvalidKey:
    async def test_401_raises_license_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_VALIDATE_URL, status_code=401)
        checker = LicenseChecker(api_key="bad_key", backend_url=BACKEND)
        with pytest.raises(LicenseError) as exc_info:
            await checker.check()
        assert "Invalid" in str(exc_info.value) or "expired" in str(exc_info.value)

    async def test_403_raises_license_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_VALIDATE_URL, status_code=403)
        checker = LicenseChecker(api_key="inactive_key", backend_url=BACKEND)
        with pytest.raises(LicenseError) as exc_info:
            await checker.check()
        assert "inactive" in str(exc_info.value).lower() or "denied" in str(exc_info.value).lower()


# ── 5. Over limit (backend says not allowed) ──────────────────────────────────

class TestOverLimit:
    async def test_backend_allowed_false_raises(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": False, "tier": "pro", "calls_today": 100, "daily_limit": 100},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        with pytest.raises(LicenseError) as exc_info:
            await checker.check()
        assert "exceeded" in str(exc_info.value).lower()

    async def test_error_message_includes_counts(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": False, "tier": "pro", "calls_today": 100, "daily_limit": 100},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        with pytest.raises(LicenseError) as exc_info:
            await checker.check()
        msg = str(exc_info.value)
        assert "100" in msg


# ── 6. Backend unreachable → fail open ───────────────────────────────────────

class TestBackendUnreachable:
    async def test_connection_error_allows_call(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            url=_VALIDATE_URL,
            exception=httpx.ConnectError("Connection refused"),
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        result = await checker.check()
        assert result["allowed"] is True
        assert result["source"] == "fail_open"

    async def test_timeout_allows_call(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            url=_VALIDATE_URL,
            exception=httpx.TimeoutException("Timeout"),
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        result = await checker.check()
        assert result["allowed"] is True
        assert result["source"] == "fail_open"

    async def test_fail_open_does_not_raise(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            url=_VALIDATE_URL,
            exception=httpx.NetworkError("Network error"),
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        # Must not raise — fail open
        result = await checker.check()
        assert result is not None

    async def test_fail_open_returns_outage_telemetry(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            url=_VALIDATE_URL,
            exception=httpx.ConnectError("Connection refused"),
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND, fail_open=True)
        result = await checker.check()
        telemetry = result.get("telemetry", {})
        assert result["source"] == "fail_open"
        assert telemetry.get("event") == "license_backend_outage"
        assert telemetry.get("fallback_mode") == "fail_open"
        assert telemetry.get("retry_after_seconds") == 60
        assert telemetry.get("alert_threshold_warning") == 3
        assert telemetry.get("alert_threshold_critical") == 10

    async def test_fail_open_alert_level_reaches_warning_threshold(self, httpx_mock: HTTPXMock):
        for _ in range(3):
            httpx_mock.add_exception(
                url=_VALIDATE_URL,
                exception=httpx.ConnectError("Connection refused"),
            )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND, fail_open=True)
        result = {}
        for _ in range(3):
            result = await checker.check()
        assert result["telemetry"]["alert_level"] == "warning"

    async def test_fail_closed_raises_actionable_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(
            url=_VALIDATE_URL,
            exception=httpx.ConnectError("Connection refused"),
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND, fail_open=False)
        with pytest.raises(LicenseError) as exc_info:
            await checker.check()
        msg = str(exc_info.value)
        assert "Please retry in 60 seconds" in msg
        assert "support@nouran-darwish-ai.dev" in msg
# ── 7. Cache: second call within 5 min uses cached response ──────────────────

class TestCacheWorks:
    async def test_second_call_hits_cache(self, httpx_mock: HTTPXMock):
        # Only one mock response registered — if cache misses, second call errors
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 1, "daily_limit": None},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        result1 = await checker.check()
        result2 = await checker.check()   # must use cache, no second HTTP call

        assert result1["source"] == "backend"
        assert result2["source"] == "cache"
        assert result2["allowed"] is True

    async def test_expired_cache_refetches(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 1, "daily_limit": None},
        )
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 2, "daily_limit": None},
        )
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        await checker.check()

        # Manually expire the cache
        checker._cache["expires_at"] = time.monotonic() - 1

        result2 = await checker.check()
        assert result2["source"] == "backend"
        assert result2["calls_today"] == 2

    async def test_cache_not_used_for_different_instance(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 1, "daily_limit": None},
        )
        httpx_mock.add_response(
            url=_VALIDATE_URL,
            json={"allowed": True, "tier": "pro", "calls_today": 1, "daily_limit": None},
        )
        # Each instance starts with an empty cache
        c1 = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        c2 = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        r1 = await c1.check()
        r2 = await c2.check()
        assert r1["source"] == "backend"
        assert r2["source"] == "backend"


# ── 8. Local file: cleanup / edge cases ──────────────────────────────────────

class TestLocalFileCleanup:
    def test_missing_file_treated_as_zero_calls(self, isolate_usage_file: Path):
        assert not isolate_usage_file.exists()
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        result = checker._check_local()
        assert result["calls_today"] == 0

    def test_corrupt_file_treated_as_zero_calls(self, isolate_usage_file: Path):
        isolate_usage_file.parent.mkdir(parents=True, exist_ok=True)
        isolate_usage_file.write_text("not valid json {{{")
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        result = checker._check_local()   # must not raise
        assert result["calls_today"] == 0

    def test_increment_creates_file(self, isolate_usage_file: Path):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        checker.increment_local_usage()
        assert isolate_usage_file.exists()

    def test_increment_creates_parent_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        deep_path = tmp_path / "a" / "b" / "c" / "usage.json"
        monkeypatch.setattr("mcp_server.middleware.license_check._USAGE_FILE", deep_path)
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        checker.increment_local_usage()
        assert deep_path.exists()

    async def test_log_usage_no_key_is_noop(self):
        checker = LicenseChecker(api_key=None, backend_url=BACKEND)
        # Must not raise and must not make any HTTP calls
        await checker.log_usage("find_repos", "fastapi saas", 5, "tiangolo/fastapi")

    async def test_log_usage_with_key_posts(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(url=_USAGE_LOG_URL, status_code=200, json={})
        checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
        await checker.log_usage("find_repos", "fastapi saas", 5, "tiangolo/fastapi")
        request = httpx_mock.get_request()
        assert request is not None
        assert request.headers.get("x-api-key") == VALID_KEY




@pytest.mark.asyncio
async def test_backend_quota_429_blocks_tool_call(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=_VALIDATE_URL,
        status_code=429,
        headers={"Retry-After": "120"},
        json={
            "detail": {
                "code": "reposcout_quota_exceeded",
                "calls_today": 10,
                "daily_limit": 10,
                "quota_reset_at": "2030-01-02T00:00:00+00:00",
            }
        },
    )

    checker = LicenseChecker(api_key=VALID_KEY, backend_url=BACKEND)
    with pytest.raises(LicenseError, match=r"10/10"):
        await checker.check(idempotency_key="quota-test-request")
