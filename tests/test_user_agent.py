import contextlib
import io
import unittest
from unittest.mock import patch

from src.config import AppConfig
from src.exceptions import ConfigError
from src.main import _default_api_factory, main


class RecordingSession:
    def __init__(self):
        self.calls = []

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return self

    def json(self):
        return {"data": {"leftDays": 5}, "code": 0, "points": 1}

    status_code = 200
    headers = {}

    def close(self):
        pass


class UserAgentTests(unittest.TestCase):
    def test_optional_user_agent_retains_default(self):
        for value in (None, "", "   "):
            env = {"GLADOS_COOKIES": "fake-cookie"}
            if value is not None:
                env["GLADOS_USER_AGENT"] = value
            config = AppConfig.from_env(env)
            with patch("src.main.requests.Session", return_value=RecordingSession()):
                api = _default_api_factory(config)("glados.cloud", "fake-cookie")
            self.assertEqual(api.headers["user-agent"], "Glados-Checkin-Toolkit/1")
            api.close()

    def test_user_agent_reaches_actual_glados_requests(self):
        ua = "Mozilla/5.0 (Test OS) TestBrowser/123.0"
        config = AppConfig.from_env({"GLADOS_COOKIES": "fake-cookie", "GLADOS_USER_AGENT": " " + ua + " "})
        session = RecordingSession()
        with patch("src.main.requests.Session", return_value=session):
            api = _default_api_factory(config)("glados.cloud", "fake-cookie")
        try:
            api.status()
            api.checkin()
            self.assertEqual(len(session.calls), 2)
            for call in session.calls:
                self.assertEqual(call["headers"]["user-agent"], ua)
                self.assertEqual(call["headers"]["cookie"], "fake-cookie")
            self.assertEqual(session.calls[1]["data"], {"token": "glados.cloud"})
        finally:
            api.close()

    def test_glados_override_does_not_change_other_domains(self):
        config = AppConfig.from_env({"GLADOS_COOKIES": "fake-cookie", "GLADOS_USER_AGENT": "TestBrowser/123"})
        for domain in ("railgun.info", "check.example.com"):
            with patch("src.main.requests.Session", return_value=RecordingSession()):
                api = _default_api_factory(config)(domain, "fake-cookie")
            self.assertEqual(api.headers["user-agent"], "Glados-Checkin-Toolkit/1")
            api.close()

    def test_invalid_user_agent_stops_before_network_without_echoing_it(self):
        for ua in ("private-value\r\nX-Foo: bar", "private-value\n", "private-value\t", "private-value\x7f", "private-value中文", "x" * 1025):
            with self.subTest(ua_length=len(ua)):
                with self.assertRaises(ConfigError) as caught:
                    AppConfig.from_env({"GLADOS_COOKIES": "fake-cookie", "GLADOS_USER_AGENT": ua})
                self.assertIn("GLADOS_USER_AGENT", str(caught.exception))
                self.assertNotIn("private-value", str(caught.exception))

    def test_invalid_user_agent_returns_config_exit_code(self):
        def forbidden(*args):
            raise AssertionError("Invalid configuration must not access network")
        with contextlib.redirect_stdout(io.StringIO()):
            code = main([], environ={"GLADOS_COOKIES": "fake-cookie", "GLADOS_USER_AGENT": "bad\r\nua"}, api_factory=forbidden)
        self.assertEqual(code, 2)

    def test_dry_run_reports_override_without_echoing_value(self):
        env = {"GLADOS_COOKIES": "fake-cookie", "GLADOS_USER_AGENT": "private-user-agent"}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["--dry-run"], environ=env), 0)
        self.assertIn("GLaDOS User-Agent: 已配置", output.getvalue())
        self.assertNotIn("private-user-agent", output.getvalue())
