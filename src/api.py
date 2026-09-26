from __future__ import annotations

import time
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote, quote_plus

import requests

from .constants import RETRYABLE_STATUS_CODES
from .exceptions import (
    ApiRejectedError,
    AuthenticationError,
    NetworkError,
    ProtocolError,
)
from .models import CheckinOutcome, CheckinState


class HttpClient:
    def __init__(
        self,
        session,
        retry_max: int,
        retry_backoff: float,
        *,
        timeout: tuple[float, float] = (5, 15),
        max_backoff: float = 10,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.session = session
        self.retry_max = retry_max
        self.retry_backoff = retry_backoff
        self.timeout = timeout
        self.max_backoff = max_backoff
        self.sleep = sleep

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
        return False

    def close(self):
        self.session.close()

    def request(self, method: str, url: str, **kwargs):
        for attempt in range(self.retry_max + 1):
            try:
                response = self.session.request(
                    method=method, url=url, timeout=self.timeout, **kwargs
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.retry_max:
                    raise NetworkError("网络请求在重试后仍失败") from exc
                self.sleep(self._backoff(attempt, None))
                continue
            except requests.RequestException as exc:
                raise NetworkError("网络请求失败") from exc

            status = response.status_code
            if status in RETRYABLE_STATUS_CODES:
                if attempt >= self.retry_max:
                    raise NetworkError(f"HTTP {status} 在重试后仍失败")
                self.sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if status in {401, 403}:
                raise AuthenticationError(f"HTTP {status} 认证失败")
            if 400 <= status:
                raise ProtocolError(f"HTTP {status} 请求被拒绝")
            return response
        raise NetworkError("网络请求失败")

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                seconds = float(retry_after)
            except ValueError:
                try:
                    when = parsedate_to_datetime(retry_after)
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=timezone.utc)
                    seconds = (when - datetime.now(timezone.utc)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    seconds = 0
            if seconds > 0:
                return min(seconds, self.max_backoff)
        return min(self.retry_backoff * (2**attempt), self.max_backoff)


class GladosAPI:
    def __init__(
        self, domain: str, cookie: str, client: HttpClient, *, user_agent: str = ""
    ):
        self.domain = domain
        self.cookie = cookie
        self.client = client
        self.base_url = f"https://{domain}"
        self.headers = {
            "cookie": cookie,
            "origin": self.base_url,
            "user-agent": user_agent or "Glados-Checkin-Toolkit/1",
        }

    def close(self):
        self.client.close()

    def _request_json(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(
            method, f"{self.base_url}{path}", headers=self.headers, **kwargs
        )
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise ProtocolError("接口返回非 JSON 内容") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("接口 JSON 顶层必须是对象")
        return payload

    def status(self) -> int:
        payload = self._request_json("GET", "/api/user/status")
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("leftDays") is None:
            raise ProtocolError("状态响应缺少 data.leftDays")
        return _as_int(data["leftDays"], "leftDays")

    def checkin(self) -> CheckinOutcome:
        payload = self._request_json(
            "POST", "/api/user/checkin", data={"token": self.domain}
        )
        code = payload.get("code")
        if code == 0:
            return CheckinOutcome(
                CheckinState.SUCCESS,
                points_added=_as_int(payload.get("points", 0), "points"),
                message=str(payload.get("message", "")),
            )
        if code == 1:
            return CheckinOutcome(
                CheckinState.ALREADY, message=str(payload.get("message", ""))
            )
        if code is None:
            raise ProtocolError("签到响应缺少 code")
        safe_code = str(code)[:16] if type(code) is int else "invalid"
        error = f"签到接口业务拒绝，code={safe_code}"
        if code == 4 and payload.get("reason") == "device-mismatch":
            error += "；reason=device-mismatch"
        message = self._safe_message(payload.get("message"))
        if message:
            error += f"；message={message}"
        raise ApiRejectedError(error[:200])

    def _safe_message(self, message) -> str:
        if not isinstance(message, str):
            return ""
        # Remove known credentials before truncating, including individual values
        # and URL-encoded echoes. Never include the rest of the response payload.
        secrets = {self.cookie}
        secrets.update(
            part.partition("=")[2].strip()
            for part in self.cookie.split(";")
            if "=" in part
        )
        variants = {
            variant
            for secret in secrets if secret
            for variant in (secret, quote(secret, safe=""), quote_plus(secret, safe=""))
        }
        for secret in sorted(variants, key=len, reverse=True):
            message = message.replace(secret, "[REDACTED]")
        return " ".join(
            "".join(
                " " if unicodedata.category(char).startswith("C") else char
                for char in message
            ).split()
        )[:160]

    def points(self) -> int:
        payload = self._request_json("GET", "/api/user/points")
        if payload.get("points") is None:
            raise ProtocolError("积分响应缺少 points")
        return _as_int(payload["points"], "points")

    def exchange(self, plan: str) -> str:
        payload = self._request_json(
            "POST", "/api/user/exchange", data={"planType": plan}
        )
        if payload.get("code") != 0:
            raise ApiRejectedError(
                f"兑换接口业务拒绝，code={payload.get('code', 'missing')}"
            )
        return str(payload.get("message") or "兑换成功")


def _as_int(value, field: str) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"{field} 字段非数字") from exc
