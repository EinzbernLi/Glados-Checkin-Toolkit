from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Mapping

from .constants import DEFAULT_DOMAINS, EXCHANGE_PLANS
from .exceptions import ConfigError


_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def _bool(value: str | None, default: bool, name: str) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} 必须是 true/false")


def _bounded_int(value: str | None, default: int, name: str, low: int, high: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数") from exc
    if not low <= parsed <= high:
        raise ConfigError(f"{name} 必须在 {low}..{high} 范围内")
    return parsed


def _bounded_float(
    value: str | None, default: float, name: str, low: float, high: float
) -> float:
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是数字") from exc
    if not low <= parsed <= high:
        raise ConfigError(f"{name} 必须在 {low}..{high} 范围内")
    return parsed


def _user_agent(value: str | None) -> str:
    if value is None:
        return ""
    if len(value) > 1024 or any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise ConfigError("GLADOS_USER_AGENT 必须是最多 1024 字符的单行 ASCII 请求头值")
    return value.strip()


def _valid_hostname(host: str) -> bool:
    if any(mark in host for mark in ("://", "/", "\\", "@", ":")):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return bool(_HOST_RE.fullmatch(host))


@dataclass(frozen=True)
class CheckinTarget:
    domain: str
    cookie: str
    exchange_plan: str
    enable_exchange: bool


def _cookies(value: str | None) -> tuple[str, ...]:
    return tuple(item.strip() for item in (value or "").split("&") if item.strip())


def _validated_domain(domain: object, name: str) -> str:
    if not isinstance(domain, str):
        raise ConfigError(f"{name} 中的域名必须是字符串")
    normalized = domain.strip().lower()
    if not _valid_hostname(normalized):
        raise ConfigError(f"{name} 只能包含纯 DNS 主机名")
    return normalized


def _exchange_plan(value: object, default: str, name: str) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if not isinstance(value, str) or value.strip() not in EXCHANGE_PLANS:
        raise ConfigError(f"{name} 必须是 plan100/plan200/plan500")
    return value.strip()


def _custom_targets(
    value: str | None,
    allow_custom: bool,
    fallback_plan: str,
    fallback_enabled: bool,
) -> list[CheckinTarget]:
    if value is None or not value.strip():
        return []
    try:
        mapping = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigError("CUSTOM_DOMAIN_COOKIES 必须是有效 JSON 对象") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise ConfigError("CUSTOM_DOMAIN_COOKIES 必须是非空 JSON 对象")
    if not allow_custom:
        raise ConfigError(
            "CUSTOM_DOMAIN_COOKIES 需要 GLADOS_ALLOW_CUSTOM_DOMAINS=true"
        )

    targets = []
    seen_domains = set()
    for raw_domain, raw_config in mapping.items():
        domain = _validated_domain(raw_domain, "CUSTOM_DOMAIN_COOKIES")
        if domain in DEFAULT_DOMAINS:
            raise ConfigError(
                "CUSTOM_DOMAIN_COOKIES 不得重复内置域名，请使用对应专属 Secret"
            )
        if domain in seen_domains:
            raise ConfigError("CUSTOM_DOMAIN_COOKIES 包含重复域名")
        seen_domains.add(domain)
        plan = fallback_plan
        enabled = fallback_enabled
        if isinstance(raw_config, dict):
            allowed_fields = {"cookies", "exchange_plan", "enable_exchange"}
            unknown = set(raw_config) - allowed_fields
            if unknown:
                raise ConfigError(
                    "CUSTOM_DOMAIN_COOKIES 配置对象包含未知字段: "
                    + ", ".join(sorted(str(item) for item in unknown))
                )
            raw_cookies = raw_config.get("cookies")
            plan = _exchange_plan(
                raw_config.get("exchange_plan"),
                fallback_plan,
                f"CUSTOM_DOMAIN_COOKIES[{domain}].exchange_plan",
            )
            raw_enabled = raw_config.get("enable_exchange", fallback_enabled)
            if not isinstance(raw_enabled, bool):
                raise ConfigError(
                    f"CUSTOM_DOMAIN_COOKIES[{domain}].enable_exchange 必须是布尔值"
                )
            enabled = raw_enabled
        else:
            raw_cookies = raw_config
        if not isinstance(raw_cookies, list) or not raw_cookies:
            raise ConfigError("CUSTOM_DOMAIN_COOKIES 中每个域名必须对应非空 Cookie 列表")
        for cookie in raw_cookies:
            if not isinstance(cookie, str) or not cookie.strip():
                raise ConfigError("CUSTOM_DOMAIN_COOKIES 中的 Cookie 必须是非空字符串")
            targets.append(CheckinTarget(domain, cookie.strip(), plan, enabled))
    return targets


@dataclass(frozen=True)
class AppConfig:
    targets: tuple[CheckinTarget, ...]
    verbose: bool
    retry_max: int
    retry_backoff: float
    connect_timeout: float
    read_timeout: float
    pushdeer_sendkey: str = ""
    pushplus_token: str = ""
    tg_bot_token: str = ""
    tg_chat_id: str = ""
    glados_user_agent: str = ""

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> "AppConfig":
        glados_cookies = _cookies(environ.get("GLADOS_COOKIES"))
        railgun_cookies = _cookies(environ.get("RAILGUN_COOKIES"))
        glados_plan = _exchange_plan(
            environ.get("GLADOS_EXCHANGE_PLAN"),
            "plan500",
            "GLADOS_EXCHANGE_PLAN",
        )
        glados_enabled = _bool(
            environ.get("GLADOS_ENABLE_EXCHANGE"),
            True,
            "GLADOS_ENABLE_EXCHANGE",
        )
        railgun_plan = _exchange_plan(
            environ.get("RAILGUN_EXCHANGE_PLAN"),
            glados_plan,
            "RAILGUN_EXCHANGE_PLAN",
        )
        railgun_enabled = _bool(
            environ.get("RAILGUN_ENABLE_EXCHANGE"),
            glados_enabled,
            "RAILGUN_ENABLE_EXCHANGE",
        )
        allow_custom = _bool(
            environ.get("GLADOS_ALLOW_CUSTOM_DOMAINS"),
            False,
            "GLADOS_ALLOW_CUSTOM_DOMAINS",
        )

        targets = []
        legacy_domains = environ.get("GLADOS_DOMAINS")
        if legacy_domains is not None and legacy_domains.strip():
            domains = tuple(
                _validated_domain(item, "GLADOS_DOMAINS")
                for item in legacy_domains.split(",")
                if item.strip()
            )
            if len(domains) != 1:
                raise ConfigError(
                    "GLADOS_DOMAINS 多域映射不明确；请改用域名专属 Secret"
                )
            legacy_domain = domains[0]
            if legacy_domain not in DEFAULT_DOMAINS and not allow_custom:
                raise ConfigError("自定义域名需要 GLADOS_ALLOW_CUSTOM_DOMAINS=true")
            if legacy_domain == "railgun.info" and railgun_cookies:
                raise ConfigError(
                    "旧 GLADOS_DOMAINS=railgun.info 不能与 RAILGUN_COOKIES 同时使用"
                )
            legacy_plan, legacy_enabled = (
                (railgun_plan, railgun_enabled)
                if legacy_domain == "railgun.info"
                else (glados_plan, glados_enabled)
            )
            targets.extend(
                CheckinTarget(legacy_domain, item, legacy_plan, legacy_enabled)
                for item in glados_cookies
            )
        else:
            targets.extend(
                CheckinTarget("glados.cloud", item, glados_plan, glados_enabled)
                for item in glados_cookies
            )

        targets.extend(
            CheckinTarget("railgun.info", item, railgun_plan, railgun_enabled)
            for item in railgun_cookies
        )
        targets.extend(
            _custom_targets(
                environ.get("CUSTOM_DOMAIN_COOKIES"),
                allow_custom,
                glados_plan,
                glados_enabled,
            )
        )
        if not targets:
            raise ConfigError(
                "至少配置 GLADOS_COOKIES、RAILGUN_COOKIES 或 CUSTOM_DOMAIN_COOKIES 之一"
            )

        pushdeer = (environ.get("PUSHDEER_SENDKEY") or "").strip()
        pushplus = (environ.get("PUSHPLUS_TOKEN") or "").strip()
        tg_token = (environ.get("TG_BOT_TOKEN") or "").strip()
        tg_chat = (environ.get("TG_CHAT_ID") or "").strip()
        if bool(tg_token) != bool(tg_chat):
            raise ConfigError("TG_BOT_TOKEN 与 TG_CHAT_ID 必须同时配置")

        return cls(
            targets=tuple(targets),
            verbose=_bool(environ.get("GLADOS_VERBOSE"), False, "GLADOS_VERBOSE"),
            retry_max=_bounded_int(
                environ.get("GLADOS_RETRY_MAX"), 2, "GLADOS_RETRY_MAX", 0, 5
            ),
            retry_backoff=_bounded_float(
                environ.get("GLADOS_RETRY_BACKOFF"),
                0.5,
                "GLADOS_RETRY_BACKOFF",
                0,
                10,
            ),
            connect_timeout=_bounded_float(
                environ.get("GLADOS_CONNECT_TIMEOUT"),
                5,
                "GLADOS_CONNECT_TIMEOUT",
                1,
                30,
            ),
            read_timeout=_bounded_float(
                environ.get("GLADOS_READ_TIMEOUT"),
                15,
                "GLADOS_READ_TIMEOUT",
                1,
                60,
            ),
            pushdeer_sendkey=pushdeer,
            pushplus_token=pushplus,
            tg_bot_token=tg_token,
            tg_chat_id=tg_chat,
            glados_user_agent=_user_agent(environ.get("GLADOS_USER_AGENT")),
        )

    @property
    def cookies(self) -> tuple[str, ...]:
        return tuple(target.cookie for target in self.targets)

    @property
    def domains(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(target.domain for target in self.targets))

    @property
    def enabled_channels(self) -> tuple[str, ...]:
        channels = []
        if self.pushdeer_sendkey:
            channels.append("pushdeer")
        if self.pushplus_token:
            channels.append("pushplus")
        if self.tg_bot_token and self.tg_chat_id:
            channels.append("telegram")
        return tuple(channels)

    def safe_summary(self) -> dict[str, object]:
        policies: dict[tuple[str, str, bool], int] = {}
        for target in self.targets:
            key = (target.domain, target.exchange_plan, target.enable_exchange)
            policies[key] = policies.get(key, 0) + 1

        target_policies = []
        for (domain, plan, enabled), accounts in policies.items():
            threshold, days = EXCHANGE_PLANS[plan]
            target_policies.append(
                {
                    "domain": domain,
                    "accounts": accounts,
                    "exchange_enabled": enabled,
                    "exchange_plan": plan,
                    "exchange_threshold": threshold,
                    "exchange_days": days,
                }
            )
        return {
            "accounts": len(self.targets),
            "domains": self.domains,
            "target_policies": tuple(target_policies),
            "channels": self.enabled_channels,
            "retry_attempts": self.retry_max + 1,
            "glados_user_agent_configured": bool(self.glados_user_agent),
        }
