"""Slack Events API integration.

Two things here are not optional and are easy to get wrong:

1. **Signature verification.** Slack signs every request with HMAC-SHA256 over
   `v0:{timestamp}:{body}`. Without checking it, the endpoint is a public API
   that will answer anyone who finds the URL. Compared with `compare_digest`
   so the check is not timing-attackable.

2. **The 3-second ack.** Slack retries any request it does not get a 200 for
   within 3 seconds, so a slow agent turns one question into three duplicate
   answers. The handler acks immediately and does the work in the background.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Slack's own guidance: reject anything older than five minutes, which bounds
# how long a captured request stays replayable.
REPLAY_WINDOW_S = 60 * 5


def verify_signature(
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    *,
    now: float | None = None,
) -> bool:
    if not signing_secret or not timestamp or not signature:
        return False

    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False

    current = time.time() if now is None else now
    if abs(current - sent_at) > REPLAY_WINDOW_S:
        return False

    basestring = b"v0:" + timestamp.encode() + b":" + body
    digest = hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


def extract_question(event: dict[str, Any]) -> str:
    """Strip the bot mention out of the message text.

    `<@U123> why is spark slow` -> `why is spark slow`
    """
    text = (event.get("text") or "").strip()
    out = []
    for token in text.split():
        if token.startswith("<@") and token.endswith(">"):
            continue
        out.append(token)
    return " ".join(out).strip()


def should_handle(event: dict[str, Any]) -> bool:
    """Ignore anything that would make the bot talk to itself.

    `bot_id` catches our own posts; `subtype` catches edits, joins and
    deletions, none of which are questions.
    """
    if event.get("bot_id"):
        return False
    if event.get("subtype"):
        return False
    return event.get("type") in {"app_mention", "message"}


class SlackClient:
    def __init__(self, bot_token: str, timeout: int = 10) -> None:
        self.bot_token = bot_token
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token)

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> bool:
        """Reply in-thread when we can, so a busy channel stays readable."""
        if not self.enabled:
            log.info("slack disabled; would have posted to %s: %s", channel, text)
            return False

        import httpx

        payload: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts

        try:
            response = httpx.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json=payload,
                timeout=self.timeout,
            )
            data = response.json()
            if not data.get("ok"):
                log.warning("slack post failed: %s", data.get("error"))
                return False
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("slack post error: %s", exc)
            return False
