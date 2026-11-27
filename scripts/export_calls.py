"""Save every call as a JSON file and write a short Markdown summary."""

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "data" / "call-exports"
SUMMARY_PATH = ROOT / "data" / "calls-summary.md"
TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 5


# Read one required setting from the environment, or stop with a short message.
def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing {name}. Set it in the environment and run this script again.")
        raise SystemExit(1)
    return value


# Download one JSON document. Retry while the API is still waking up.
def fetch_json(client: httpx.Client, url: str) -> Any:
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            waking = isinstance(exc, httpx.TransportError) or status == 429 or (
                status is not None and status >= 500
            )
            if not waking or attempt == MAX_RETRIES:
                break
            print("API is waking up, retrying...")
            time.sleep(RETRY_WAIT_SECONDS)
    print(f"Could not read {url}: {last_error}")
    raise SystemExit(1)


# Download the call list, then the full record for each call.
def load_calls(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    listed = fetch_json(client, f"{base_url}/calls")
    if not isinstance(listed, list):
        print("The call list was not a list.")
        raise SystemExit(1)
    details: list[dict[str, Any]] = []
    for item in listed:
        if not isinstance(item, dict):
            continue
        call_id = str(item.get("id") or "").strip()
        if not call_id or "/" in call_id or "\\" in call_id or call_id in {".", ".."}:
            continue
        detail = fetch_json(client, f"{base_url}/calls/{call_id}")
        if isinstance(detail, dict):
            details.append(detail)
    return details


# How many items are in a list field. Missing or empty counts as zero.
def list_count(call: dict[str, Any], key: str) -> int:
    value = call.get(key)
    if not isinstance(value, list):
        return 0
    return len(value)


# The saved total cost, or a blank cell when this call has no cost yet.
def cost_cell(call: dict[str, Any]) -> str:
    cost = call.get("cost")
    if not isinstance(cost, dict):
        return ""
    total = cost.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        return ""
    currency = cost.get("currency")
    if isinstance(currency, str) and currency.strip():
        return f"{total} {currency.strip()}"
    return str(total)


# Make one table cell safe to put in Markdown.
def cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("|", "\\|").strip()
    return text


# Write one pretty JSON file for each call.
def write_exports(calls: list[dict[str, Any]]) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    for call in calls:
        call_id = str(call.get("id") or "").strip()
        path = EXPORT_DIR / f"{call_id}.json"
        path.write_text(json.dumps(call, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# Write the one-row-per-call summary. This file is meant to be committed.
def write_summary(calls: list[dict[str, Any]]) -> None:
    lines = [
        "# Calls",
        "",
        f"{len(calls)} calls.",
        "",
        "| id | createdAt | durationSeconds | status | hangupReason | transcript turns | tool calls | interruptions | total cost |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for call in calls:
        lines.append(
            "| {id} | {created} | {duration} | {status} | {hangup} | {turns} | {tools} | {interruptions} | {cost} |".format(
                id=cell(call.get("id")),
                created=cell(call.get("createdAt")),
                duration=cell(call.get("durationSeconds")),
                status=cell(call.get("status")),
                hangup=cell(call.get("hangupReason")),
                turns=list_count(call, "transcript"),
                tools=list_count(call, "toolCalls"),
                interruptions=list_count(call, "interruptions"),
                cost=cell(cost_cell(call)),
            )
        )
    lines.append("")
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text("\n".join(lines), encoding="utf-8")


# Fetch every call and write the JSON files plus the summary.
def main() -> None:
    base_url = require_env("API_BASE_URL").rstrip("/")
    api_key = require_env("API_KEY")
    with httpx.Client(headers={"X-API-Key": api_key}, timeout=TIMEOUT_SECONDS) as client:
        calls = load_calls(client, base_url)
    write_exports(calls)
    write_summary(calls)
    print(f"Wrote {len(calls)} calls to {EXPORT_DIR}")
    print(f"Wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
