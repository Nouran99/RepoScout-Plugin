"""License check middleware validates API keys and enforces usage limits."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any, cast

import httpx
import structlog

logger = structlog.get_logger(__name__)

_FREE_DAILY_LIMIT = 10
_CACHE_TTL_SECONDS = 300  # 5 minutes
_USAGE_FILE = Path.home() / ".reposcout" / "usage.json"
_VALIDATE_PATH = "/api/v1/reposcout/validate-key"
_USAGE_PATH = "/api/v1/reposcout/usage"
_OUTAGE_RETRY_AFTER_SECONDS = 60
_OUTAGE_ALERT_WARN_THRESHOLD = 3
_OUTAGE_ALERT_CRITICAL_THRESHOLD = 10


class LicenseError(Exception):
    """Raised when a usage limit is exceeded or a key is invalid."""


class LicenseChecker:
    """Validates API keys and enforces per-day usage limits.

    Free tier (no API key): tracks calls locally in ~/.reposcout/usage.json
    with a hard limit of 10 calls per calendar day.

    Pro/Team tier (API key set): validates against the RepoScout backend and
    respects the tier limits returned by the server. Responses are cached for
    5 minutes to avoid hammering the backend on every tool call.

    If the backend is unreachable behavior depends on fail-open policy:
    - fail-open: allow call and include outage telemetry
    - fail-closed: block call with retry/support guidance
    """

    def __init__(
        self,
        api_key: str | None,
        backend_url: str,
        fail_open: bool = True,
    ) -> None:
        self._api_key = api_key
        self._backend_url = backend_url.rstrip("/")
        self._fail_open = fail_open
        # In-process cache: {"result": dict, "expires_at": float}
        self._cache: dict[str, Any] | None = None
        self._backend_outage_count = 0

    async def check(self, idempotency_key: str | None = None) -> dict[str, Any]:
        """Check whether the current call is permitted.

        Returns a dict with at minimum:
          allowed, tier, calls_today, daily_limit, source

        Raises LicenseError when usage is denied.
        """
        if not self._api_key:
            return self._check_local()
        return await self._check_backend(idempotency_key=idempotency_key)

    def increment_local_usage(self) -> None:
        """Increment today's local call counter (free-tier only)."""
        data = self._load_usage()
        today = str(date.today())
        data.setdefault(today, 0)
        data[today] += 1
        self._save_usage(data)

    async def log_usage(
        self,
        tool_name: str,
        query: str,
        results_count: int,
        chosen_repo: str | None,
        *,
        reservation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Log a tool call to the backend (best-effort, fails silently)."""
        if not self._api_key:
            return

        payload = {
            "tool_name": tool_name,
            "query": query,
            "results_count": results_count,
            "chosen_repo": chosen_repo,
            "reservation_id": reservation_id,
            "idempotency_key": idempotency_key,
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"X-API-Key": self._api_key}
                if idempotency_key:
                    headers["Idempotency-Key"] = idempotency_key
                await client.post(
                    f"{self._backend_url}{_USAGE_PATH}",
                    json=payload,
                    headers=headers,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("log_usage_failed", error=str(exc))

    def _check_local(self) -> dict[str, Any]:
        """Enforce the free-tier daily limit using ~/.reposcout/usage.json."""
        data = self._load_usage()
        today = str(date.today())
        calls_today: int = data.get(today, 0)

        if calls_today >= _FREE_DAILY_LIMIT:
            raise LicenseError(
                f"Free tier limit reached ({_FREE_DAILY_LIMIT} calls/day). "
                "Set REPOSCOUT_API_KEY to unlock unlimited usage."
            )

        return {
            "allowed": True,
            "tier": "free",
            "calls_today": calls_today,
            "daily_limit": _FREE_DAILY_LIMIT,
            "source": "local",
        }

    def _load_usage(self) -> dict[str, Any]:
        """Read the local usage file, returning an empty dict on any error."""
        try:
            if _USAGE_FILE.exists():
                return cast(dict[str, Any], json.loads(_USAGE_FILE.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            logger.warning("usage_file_read_error", error=str(exc))
        return {}

    def _save_usage(self, data: dict[str, Any]) -> None:
        """Persist usage data, creating parent dirs as needed."""
        try:
            _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _USAGE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("usage_file_write_error", error=str(exc))

    async def _check_backend(self, *, idempotency_key: str | None = None) -> dict[str, Any]:
        """Validate API key against the RepoScout backend with 5-min caching."""
        # Reservation-bearing checks must hit the backend on every tool call;
        # caching them would make the client spend beyond an authoritative quota.
        if not idempotency_key and self._cache and time.monotonic() < self._cache["expires_at"]:
            cached_result = dict(self._cache["result"])
            cached_result["source"] = "cache"
            self._enforce(cached_result)
            return cached_result

        api_key = self._api_key
        if not api_key:
            return self._check_local()

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"X-API-Key": api_key}
                if idempotency_key:
                    headers["Idempotency-Key"] = idempotency_key
                response = await client.get(
                    f"{self._backend_url}{_VALIDATE_PATH}",
                    headers=headers,
                )
        except Exception as exc:  # noqa: BLE001
            self._backend_outage_count += 1
            telemetry = self._build_outage_telemetry(error=str(exc))
            action = "fail_open" if self._fail_open else "fail_closed"
            logger.warning(
                "reposcout_backend_unreachable",
                action=action,
                telemetry=telemetry,
            )

            if self._fail_open:
                return {
                    "allowed": True,
                    "tier": "unknown",
                    "calls_today": 0,
                    "daily_limit": None,
                    "source": "fail_open",
                    "telemetry": telemetry,
                    "outage": True,
                }

            raise LicenseError(
                "RepoScout licensing service is temporarily unavailable. "
                f"Please retry in {_OUTAGE_RETRY_AFTER_SECONDS} seconds. "
                "If this continues for more than 10 minutes, contact support@nouran-darwish-ai.dev."
            ) from exc

        if response.status_code == 401:
            raise LicenseError("Invalid or expired API key.")
        if response.status_code == 403:
            raise LicenseError("API key is inactive or access denied.")
        if response.status_code == 429:
            try:
                detail = response.json().get("detail", {})
            except Exception:  # noqa: BLE001
                detail = {}
            if isinstance(detail, dict) and detail.get("code") == "reposcout_quota_exceeded":
                calls = detail.get("calls_today", "the current")
                limit = detail.get("daily_limit", "daily")
                reset_at = detail.get("quota_reset_at")
                suffix = f" Reset at {reset_at}." if reset_at else ""
                raise LicenseError(
                    f"RepoScout quota reached ({calls}/{limit} calls today).{suffix}"
                )
            raise LicenseError("RepoScout usage limit reached. Please retry later.")
        if response.status_code >= 400:
            raise LicenseError(
                f"RepoScout licensing service returned HTTP {response.status_code}."
            )

        try:
            body: dict[str, Any] = response.json()
        except Exception:  # noqa: BLE001
            body = {}

        result: dict[str, Any] = {
            "allowed": body.get("allowed", True),
            "tier": body.get("tier", "pro"),
            "calls_today": body.get("calls_today", 0),
            "daily_limit": body.get("daily_limit"),
            "quota_remaining": body.get("quota_remaining"),
            "quota_reset_at": body.get("quota_reset_at"),
            "reservation_id": body.get("reservation_id"),
            "source": "backend",
        }

        if response.is_success:
            self._backend_outage_count = 0
            if not idempotency_key:
                self._cache = {
                    "result": dict(result),
                    "expires_at": time.monotonic() + _CACHE_TTL_SECONDS,
                }

        self._enforce(result)
        return result

    def _build_outage_telemetry(self, error: str) -> dict[str, Any]:
        alert_level = "none"
        if self._backend_outage_count >= _OUTAGE_ALERT_CRITICAL_THRESHOLD:
            alert_level = "critical"
        elif self._backend_outage_count >= _OUTAGE_ALERT_WARN_THRESHOLD:
            alert_level = "warning"

        return {
            "event": "license_backend_outage",
            "fallback_mode": "fail_open" if self._fail_open else "fail_closed",
            "retry_after_seconds": _OUTAGE_RETRY_AFTER_SECONDS,
            "outage_count": self._backend_outage_count,
            "alert_threshold_warning": _OUTAGE_ALERT_WARN_THRESHOLD,
            "alert_threshold_critical": _OUTAGE_ALERT_CRITICAL_THRESHOLD,
            "alert_level": alert_level,
            "error": error,
        }

    @staticmethod
    def _enforce(result: dict[str, Any]) -> None:
        """Raise LicenseError if the backend says the call is not allowed."""
        if not result.get("allowed", True):
            limit = result.get("daily_limit")
            calls = result.get("calls_today", 0)
            tier = result.get("tier", "unknown")
            msg = f"Usage limit exceeded for {tier} tier ({calls}/{limit} calls today)."
            raise LicenseError(msg)
