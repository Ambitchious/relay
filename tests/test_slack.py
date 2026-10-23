"""Slack signature verification and event filtering.

Signature verification is the security boundary of this service, so it is
tested against forged, stale and malformed input rather than only the happy path.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.slack import (
    REPLAY_WINDOW_S,
    extract_question,
    should_handle,
    verify_signature,
)

SECRET = "8f742231b10e4e2193b7f0ab1ba4fd8e"


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_accepts_a_correctly_signed_request():
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    assert verify_signature(SECRET, ts, body, _sign(SECRET, ts, body)) is True


def test_rejects_a_forged_signature():
    ts = str(int(time.time()))
    body = b'{"type":"event_callback"}'
    assert verify_signature(SECRET, ts, body, "v0=deadbeef") is False


def test_rejects_a_signature_made_with_the_wrong_secret():
    ts = str(int(time.time()))
    body = b"{}"
    assert verify_signature(SECRET, ts, body, _sign("other-secret", ts, body)) is False


def test_rejects_a_replayed_request_outside_the_window():
    stale = str(int(time.time()) - REPLAY_WINDOW_S - 60)
    body = b"{}"
    assert verify_signature(SECRET, stale, body, _sign(SECRET, stale, body)) is False


def test_accepts_a_request_just_inside_the_window():
    recent = str(int(time.time()) - REPLAY_WINDOW_S + 30)
    body = b"{}"
    assert verify_signature(SECRET, recent, body, _sign(SECRET, recent, body)) is True


def test_rejects_when_the_body_has_been_tampered_with():
    ts = str(int(time.time()))
    signature = _sign(SECRET, ts, b'{"amount":1}')
    assert verify_signature(SECRET, ts, b'{"amount":1000}', signature) is False


def test_rejects_malformed_or_missing_input():
    ts = str(int(time.time()))
    assert verify_signature("", ts, b"{}", "v0=x") is False
    assert verify_signature(SECRET, "", b"{}", "v0=x") is False
    assert verify_signature(SECRET, ts, b"{}", "") is False
    assert verify_signature(SECRET, "not-a-number", b"{}", "v0=x") is False


def test_strips_the_bot_mention_from_the_question():
    assert extract_question({"text": "<@U07AB> why is spark slow"}) == "why is spark slow"
    assert extract_question({"text": "  <@U07AB>   "}) == ""
    assert extract_question({}) == ""


def test_ignores_its_own_messages_and_non_questions():
    assert should_handle({"type": "app_mention", "text": "hi"}) is True
    assert should_handle({"type": "app_mention", "bot_id": "B1"}) is False
    assert should_handle({"type": "message", "subtype": "message_changed"}) is False
    assert should_handle({"type": "reaction_added"}) is False
