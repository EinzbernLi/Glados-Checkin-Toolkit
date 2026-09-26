import json

import pytest
import requests

from src.api import GladosAPI, HttpClient
from src.exceptions import ApiRejectedError, AuthenticationError, ProtocolError
from src.models import CheckinState


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, events):
        self.events = list(events)
        self.calls = []
        self.closed = False

    def request(self, **kwargs):
        self.calls.append(kwargs)
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    def close(self):
        self.closed = True


def test_retries_429_using_retry_after_then_succeeds():
    session = FakeSession(
        [
            FakeResponse(429, {"message": "slow"}, {"Retry-After": "2"}),
            FakeResponse(200, {"code": 0}),
        ]
    )
    sleeps = []
    client = HttpClient(session, retry_max=1, retry_backoff=0.1, sleep=sleeps.append)
    response = client.request("POST", "https://glados.cloud/api/user/checkin")
    assert response.status_code == 200
    assert len(session.calls) == 2
    assert sleeps == [2.0]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_regular_4xx_is_not_retried(status):
    session = FakeSession([FakeResponse(status, {"message": "denied"})])
    client = HttpClient(session, retry_max=3, retry_backoff=0, sleep=lambda _: None)
    with pytest.raises(AuthenticationError if status in (401, 403) else ProtocolError):
        client.request("GET", "https://glados.cloud/api/user/status")
    assert len(session.calls) == 1


def test_retries_timeout_exactly_to_configured_limit():
    session = FakeSession(
        [
            requests.Timeout("first"),
            requests.Timeout("second"),
            FakeResponse(200, {"code": 0}),
        ]
    )
    client = HttpClient(session, retry_max=2, retry_backoff=0, sleep=lambda _: None)
    assert client.request("GET", "https://glados.cloud/api/user/status").status_code == 200
    assert len(session.calls) == 3


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_retries_each_transient_server_status(status):
    session = FakeSession(
        [FakeResponse(status, {"message": "temporary"}), FakeResponse(200, {"code": 0})]
    )
    client = HttpClient(session, retry_max=1, retry_backoff=0, sleep=lambda _: None)
    assert client.request("GET", "https://glados.cloud/api/user/status").status_code == 200
    assert len(session.calls) == 2


def test_client_context_closes_session():
    session = FakeSession([FakeResponse(200, {"code": 0})])
    with HttpClient(session, retry_max=0, retry_backoff=0) as client:
        client.request("GET", "https://glados.cloud/api/user/status")
    assert session.closed


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"code": 0, "points": 1, "message": "ok"}, CheckinState.SUCCESS),
        ({"code": 1, "message": "checked"}, CheckinState.ALREADY),
    ],
)
def test_checkin_business_codes(payload, expected):
    client = HttpClient(FakeSession([FakeResponse(200, payload)]), 0, 0)
    outcome = GladosAPI("glados.cloud", "fake-cookie", client).checkin()
    assert outcome.state is expected


def test_invalid_json_is_protocol_error():
    client = HttpClient(
        FakeSession([FakeResponse(200, ValueError("bad json"), text="not-json")]),
        0,
        0,
    )
    with pytest.raises(ProtocolError):
        GladosAPI("glados.cloud", "fake-cookie", client).status()


def test_missing_status_field_is_protocol_error():
    client = HttpClient(FakeSession([FakeResponse(200, {"code": 0})]), 0, 0)
    with pytest.raises(ProtocolError):
        GladosAPI("glados.cloud", "fake-cookie", client).status()


def test_unknown_checkin_business_code_is_rejected():
    client = HttpClient(
        FakeSession([FakeResponse(200, {"code": 999, "message": "unknown"})]),
        0,
        0,
    )
    with pytest.raises(ApiRejectedError):
        GladosAPI("glados.cloud", "fake-cookie", client).checkin()


def rejected_checkin_message(message, cookie="fake-cookie", code=4):
    client = HttpClient(
        FakeSession([FakeResponse(200, {"code": code, "message": message})]), 0, 0
    )
    with pytest.raises(ApiRejectedError) as exc:
        GladosAPI("glados.cloud", cookie, client).checkin()
    return str(exc.value)


def test_rejection_includes_server_message_without_changing_failure_state():
    assert "code=4；message=please check in on the website" == (
        rejected_checkin_message("please check in on the website").split("，", 1)[1]
    )


def test_rejection_redacts_cookie_and_individual_encoded_values():
    from urllib.parse import quote

    cookie = "koa:sess=private/value+123; koa:sess.sig=signature-secret"
    message = f"denied {cookie} {quote('private/value+123', safe='')}"
    result = rejected_checkin_message(message, cookie)
    assert "message=denied" in result
    for value in (cookie, "private/value+123", "signature-secret", "private%2Fvalue%2B123"):
        assert value not in result


def test_rejection_message_is_single_line_and_bounded():
    result = rejected_checkin_message("denied\n\r\x1b[31m" + "x" * 500)
    assert "message=denied" in result
    assert len(result) <= 200
    assert not any(ord(char) < 32 or ord(char) == 127 for char in result)


@pytest.mark.parametrize("message", [None, {"cookie": "sensitive"}, ["sensitive"]])
def test_rejection_does_not_dump_structured_messages(message):
    assert rejected_checkin_message(message) == "签到接口业务拒绝，code=4"


def test_rejection_does_not_dump_non_numeric_code():
    result = rejected_checkin_message("denied", code={"cookie": "sensitive"})
    assert "sensitive" not in result
    assert "code=invalid" in result
