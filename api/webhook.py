"""Send a call.ended webhook after a result is saved. Failures stay in the attempt log."""

import asyncio
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from api.db import append_webhook_attempt

RETRY_DELAYS_SECONDS = (1, 3, 9)
_client: httpx.AsyncClient | None = None


# Open the webhook HTTP client once. Creating it loads SSL, so do this off a busy call.
def open_webhook_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    return _client


# Close the webhook HTTP client when the API process stops.
async def close_webhook_client() -> None:
    global _client
    client = _client
    _client = None
    if client is not None and not client.is_closed:
        await client.aclose()


# Return the shared client, building it off the event loop when startup did not.
async def _webhook_client() -> httpx.AsyncClient:
    if _client is not None and not _client.is_closed:
        return _client
    return await asyncio.to_thread(open_webhook_client)


# Print one webhook event with the current time. Never print the secret.
def log_webhook(event: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} {event}")


# Turn one labeled line into a sentence.
def _sentence(label: str, text: str) -> str:
    line = f"{label}: {_clip(text)}"
    if line[-1] not in ".!?":
        return line + "."
    return line


# Shorten one spoken line so the summary stays a sentence.
def _clip(text: str, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


# Build one to three plain sentences from the transcript. This does not call an LLM.
def plain_summary(transcript: Any) -> str:
    if not isinstance(transcript, list):
        return "The call ended with no transcript."
    caller = ""
    last_agent = ""
    for turn in transcript:
        if not isinstance(turn, dict):
            continue
        text = " ".join(str(turn.get("text") or "").split())
        if not text:
            continue
        if turn.get("role") == "user" and not caller:
            caller = text
        if turn.get("role") == "agent":
            last_agent = text
    sentences: list[str] = []
    if caller:
        sentences.append(_sentence("The caller said", caller))
    if last_agent:
        sentences.append(_sentence("The agent ended with", last_agent))
    if not sentences:
        return "The call ended with no transcript."
    return " ".join(sentences)


# Keep only the tool fields the webhook receiver needs.
def _public_tools(tool_calls: Any) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list):
        return []
    public: list[dict[str, Any]] = []
    for item in tool_calls:
        if not isinstance(item, dict):
            continue
        public.append(
            {
                "name": item.get("name"),
                "arguments": item.get("arguments"),
                "result": item.get("result"),
            }
        )
    return public


# The webhook URL on the call, or None when this call should not notify anyone.
def webhook_url_from(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    url = config.get("webhookUrl")
    if not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    return cleaned


# True when the URL is an http or https address we can POST to.
def _http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


# Build the call.ended JSON body.
def webhook_body(call_id: str, result: dict[str, Any], cost: dict[str, Any]) -> dict[str, Any]:
    transcript = result.get("transcript")
    return {
        "event": "call.ended",
        "callId": call_id,
        "status": "completed",
        "startedAt": result.get("startedAt"),
        "endedAt": result.get("endedAt"),
        "durationSeconds": result.get("durationSeconds"),
        "hangupReason": result.get("hangupReason"),
        "transcriptTurns": len(transcript) if isinstance(transcript, list) else 0,
        "toolCalls": _public_tools(result.get("toolCalls")),
        "cost": cost,
        "summary": plain_summary(transcript),
    }


# Sign the exact bytes that will be sent. The header looks like sha256=<hex>.
def sign_body(raw_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


# Save one try on the call, and keep going even if the database write fails.
def _record(call_id: str, attempt: dict[str, Any]) -> None:
    try:
        append_webhook_attempt(call_id, attempt)
    except Exception as exc:
        log_webhook(f"webhook attempt not saved call_id={call_id} error={type(exc).__name__}")
        return
    result = attempt.get("statusCode", attempt.get("error"))
    log_webhook(f"webhook attempt call_id={call_id} result={result}")


# True for a temporary failure: timeout, connection error, HTTP 429, or HTTP 5xx.
def _should_retry(status_code: int | None, error: BaseException | None) -> bool:
    if isinstance(error, httpx.TransportError):
        return True
    if status_code is None:
        return False
    return status_code == 429 or status_code >= 500


# POST the webhook. Retry temporary failures up to three times. Never raise.
async def deliver_webhook(call_id: str, url: str, result: dict[str, Any], cost: dict[str, Any]) -> None:
    try:
        if not _http_url(url):
            _record(
                call_id,
                {
                    "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "error": "unsupported webhook url",
                },
            )
            return
        raw_body = json.dumps(
            webhook_body(call_id, result, cost),
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        secret = os.environ.get("WEBHOOK_SECRET", "")
        signature = sign_body(raw_body, secret)
        client = await _webhook_client()
        for index in range(len(RETRY_DELAYS_SECONDS) + 1):
            attempt: dict[str, Any] = {
                "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            retry = False
            try:
                response = await client.post(
                    url,
                    content=raw_body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature": signature,
                        "X-Timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                    },
                )
                attempt["statusCode"] = response.status_code
                retry = _should_retry(response.status_code, None)
            except httpx.TransportError as exc:
                attempt["error"] = type(exc).__name__
                retry = _should_retry(None, exc)
            except Exception as exc:
                attempt["error"] = type(exc).__name__
                retry = False
            _record(call_id, attempt)
            if not retry or index >= len(RETRY_DELAYS_SECONDS):
                return
            await asyncio.sleep(RETRY_DELAYS_SECONDS[index])
    except Exception as exc:
        log_webhook(f"webhook delivery failed call_id={call_id} error={type(exc).__name__}")
