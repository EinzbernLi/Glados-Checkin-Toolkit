from pathlib import Path
import re

import yaml

from src.models import CheckinOutcome, CheckinState
from src.main import main


ROOT = Path(__file__).resolve().parents[1]


def test_dry_run_uses_fake_values_and_makes_no_network(capsys):
    env = {
        "GLADOS_COOKIES": "fake-cookie-a&fake-cookie-b",
        "PUSHPLUS_TOKEN": "fake-token",
    }

    def forbidden_factory(*_):
        raise AssertionError("dry-run must not construct an API")

    assert main(["--dry-run"], environ=env, api_factory=forbidden_factory) == 0
    output = capsys.readouterr().out
    assert "签到目标数: 2" in output
    assert "pushplus" in output
    assert "fake-cookie" not in output
    assert "fake-token" not in output


def test_dry_run_shows_each_domain_exchange_policy(capsys):
    env = {
        "GLADOS_COOKIES": "private-glados",
        "RAILGUN_COOKIES": "private-railgun",
        "GLADOS_EXCHANGE_PLAN": "plan100",
        "RAILGUN_EXCHANGE_PLAN": "plan500",
        "RAILGUN_ENABLE_EXCHANGE": "false",
    }
    assert main(["--dry-run"], environ=env) == 0
    output = capsys.readouterr().out
    assert "glados.cloud（1 个账号）: 启用 · plan100" in output
    assert "railgun.info（1 个账号）: 关闭 · plan500" in output
    assert "private-glados" not in output
    assert "private-railgun" not in output


def test_config_error_returns_two_without_constructing_api():
    def forbidden_factory(*_):
        raise AssertionError("config error must stop before API construction")

    assert main([], environ={}, api_factory=forbidden_factory) == 2


def test_ambiguous_legacy_domains_stop_before_api_construction():
    def forbidden_factory(*_):
        raise AssertionError("ambiguous config must stop before API construction")

    env = {
        "GLADOS_COOKIES": "fake-cookie",
        "GLADOS_DOMAINS": "glados.cloud,railgun.info",
    }
    assert main([], environ=env, api_factory=forbidden_factory) == 2


def test_unauthorized_custom_domain_stops_before_api_construction():
    def forbidden_factory(*_):
        raise AssertionError("unsafe config must stop before API construction")

    env = {
        "CUSTOM_DOMAIN_COOKIES": '{"check.example.com":["fake-cookie"]}'
    }
    assert main([], environ=env, api_factory=forbidden_factory) == 2


class SuccessfulAPI:
    def status(self):
        return 120

    def checkin(self):
        return CheckinOutcome(CheckinState.ALREADY)

    def points(self):
        return 72

    def exchange(self, _plan):
        raise AssertionError("72 points must not trigger plan500 exchange")

    def close(self):
        pass


class FakePostResponse:
    def __init__(self, payload, status_code=200, content=b"json"):
        self.payload = payload
        self.status_code = status_code
        self.content = content

    def json(self):
        return self.payload


def test_partial_notification_failure_attempts_all_and_returns_one(capsys, caplog):
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        if "pushplus" in url:
            return FakePostResponse({"code": 500})
        return FakePostResponse({"code": 0})

    env = {
        "GLADOS_COOKIES": "fake-cookie",
        "PUSHDEER_SENDKEY": "fake-sendkey",
        "PUSHPLUS_TOKEN": "fake-token",
    }
    code = main(
        [],
        environ=env,
        api_factory=lambda *_: SuccessfulAPI(),
        post=post,
    )
    assert code == 1
    assert len(calls) == 2
    assert "pushdeer" in calls[0]
    assert "pushplus" in calls[1]
    output = capsys.readouterr().out + capsys.readouterr().err + caplog.text
    assert "fake-cookie" not in output
    assert "fake-sendkey" not in output
    assert "fake-token" not in output


def test_success_without_notification_returns_zero():
    assert (
        main(
            [],
            environ={"GLADOS_COOKIES": "fake-cookie"},
            api_factory=lambda *_: SuccessfulAPI(),
        )
        == 0
    )


def load_workflow(name):
    with (ROOT / ".github" / "workflows" / name).open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def test_workflow_yaml_is_parseable_and_split():
    assert load_workflow("ci.yml")
    assert load_workflow("gladosCheck.yml")


def test_ci_does_not_reference_secrets():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "secrets." not in text
    assert "pytest" in text


def test_scheduled_workflow_has_safe_triggers_and_cron():
    path = ROOT / ".github" / "workflows" / "gladosCheck.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    triggers = workflow[True]  # YAML 1.1 parses the key `on` as True.
    assert "push" not in triggers
    assert triggers["schedule"] == [{"cron": "0 4,10 * * *"}]
    dispatch = triggers["workflow_dispatch"]
    run_mode = dispatch["inputs"]["run_mode"]
    assert run_mode["required"] is True
    assert run_mode["default"] == "dry-run"
    assert run_mode["type"] == "choice"
    assert run_mode["options"] == ["dry-run", "live"]
    assert '"${{ inputs.run_mode }}" != "live"' in text
    assert "python checkin.py --dry-run" in text
    assert "python checkin.py" in text
    assert "pytest" not in text
    assert "matrix:" not in text
    assert "pip install --upgrade pip" not in text
    assert "keepalive" not in text.lower()
    assert "delete-workflow-runs" not in text
    assert "continue-on-error" not in text
    assert "contents: read" in text
    assert "timeout-minutes: 3" in text
    assert "RAILGUN_COOKIES: ${{ secrets.RAILGUN_COOKIES }}" in text
    assert "RAILGUN_EXCHANGE_PLAN: ${{ secrets.RAILGUN_EXCHANGE_PLAN }}" in text
    assert "RAILGUN_ENABLE_EXCHANGE: ${{ vars.RAILGUN_ENABLE_EXCHANGE }}" in text
    assert "CUSTOM_DOMAIN_COOKIES: ${{ secrets.CUSTOM_DOMAIN_COOKIES }}" in text


def test_all_actions_are_pinned_to_commit_sha():
    for name in ("ci.yml", "gladosCheck.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        uses = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", text)
        assert uses
        assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in uses)


def test_readme_local_links_and_images_exist():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    targets = re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text)
    local_targets = [
        target.split("#", 1)[0]
        for target in targets
        if "://" not in target and not target.startswith("#")
    ]
    assert local_targets
    assert all((ROOT / target).is_file() for target in local_targets)


def test_independent_repository_identity_and_provenance_are_documented():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    package_doc = (ROOT / "src" / "__init__.py").read_text(encoding="utf-8")
    api = (ROOT / "src" / "api.py").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert readme.startswith("# GLaDOS Check-in Toolkit")
    assert "EinzbernLi/Glados-Checkin-Toolkit" in readme
    assert "branch=main" in readme
    assert "本 Fork" not in readme
    for repository in (
        "Devilstore/Glados-Railgun-checkin",
        "EinzbernLi/Glados-Railgun-checkin",
        "EinzbernLi/Glados-Checkin-Toolkit",
    ):
        assert repository in notice
    assert "Glados-Checkin-Toolkit/1" in api
    assert "Independent GPL-3.0 project" in package_doc
    assert "branches: [main]" in ci


def test_readme_documents_all_exchange_plans_and_disable_switch():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "积分兑换策略" in text
    assert "| `plan100` | 100 积分 | 10 天 |" in text
    assert "| `plan200` | 200 积分 | 30 天 |" in text
    assert "| `plan500` | 500 积分 | 100 天 |" in text
    assert "GLADOS_ENABLE_EXCHANGE=false" in text
    assert "RAILGUN_EXCHANGE_PLAN" in text
    assert "RAILGUN_ENABLE_EXCHANGE=false" in text
    assert "未配置 Railgun 专属值时" in text


def test_readme_documents_domain_binding_aggregation_and_beijing_time():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "GLADOS_COOKIES" in text and "glados.cloud" in text
    assert "RAILGUN_COOKIES" in text and "railgun.info" in text
    assert "CUSTOM_DOMAIN_COOKIES" in text
    assert '{"check.example.com":["cookie-account-1","cookie-account-2"]}' in text
    assert '"exchange_plan":"plan200"' in text
    assert '"enable_exchange":false' in text
    assert "一张 HTML 卡片" in text
    assert "一张 Markdown 卡片" in text
    assert "GLaDOS 签到结果" in text
    assert "Railgun 签到结果" in text
    assert "两个及以上域名" in text
    assert "北京时间" in text


def test_readme_documents_telegram_secret_setup():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Telegram 配置步骤" in text
    assert "@BotFather" in text
    assert "/newbot" in text
    assert "TG_BOT_TOKEN" in text and "TG_CHAT_ID" in text
    assert "https://api.telegram.org/bot<BOT_TOKEN>/getUpdates" in text
    assert "message.chat.id" in text
    assert "channel_post.chat.id" in text
    assert "Repository secret" in text



def test_workflow_passes_glados_user_agent_as_environment_variable():
    workflow = load_workflow("gladosCheck.yml")
    step = next(step for step in workflow["jobs"]["checkin"]["steps"] if "GLADOS_COOKIES" in step.get("env", {}))
    assert step["env"]["GLADOS_USER_AGENT"] == "${{ vars.GLADOS_USER_AGENT }}"
    assert "GLADOS_USER_AGENT" not in step["run"]
