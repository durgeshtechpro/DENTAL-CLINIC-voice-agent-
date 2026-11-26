"""Read saved calls and print how slow each part of a turn usually is."""

import argparse
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

COMPONENTS = (
    "transcriptionDelayMs",
    "endOfTurnDelayMs",
    "llmTtftMs",
    "ttsTtfbMs",
    "e2eLatencyMs",
    "toolDurationMs",
    "derivedTotalMs",
)
GROUPS = ("all", "plain", "tool", "kb")
ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "data" / "latency-report.md"


# Read one required setting from the environment, or stop with a short message.
def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing {name}. Set it in the environment and run this script again.")
        raise SystemExit(1)
    return value


# Turn an ISO time string into a UTC time, or None when the text is not a time.
def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# The time a call started, using startedAt when the API stored it.
def call_time(call: dict[str, Any]) -> datetime | None:
    return parse_time(call.get("startedAt")) or parse_time(call.get("createdAt"))


# Keep the calls the command line asked for.
def select_calls(
    calls: list[dict[str, Any]],
    since: datetime | None,
    only_ids: set[str] | None,
) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for call in calls:
        call_id = str(call.get("id") or "")
        if only_ids is not None and call_id not in only_ids:
            continue
        if since is not None:
            when = call_time(call)
            if when is None or when < since:
                continue
        chosen.append(call)
    return chosen


# Download one JSON document. Raises when the API is unreachable or rejects the key.
def fetch_json(client: httpx.Client, url: str) -> Any:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


# Download the call list, then the full record for each selected call.
def load_calls(
    client: httpx.Client,
    base_url: str,
    since: datetime | None,
    only_ids: set[str] | None,
) -> list[dict[str, Any]]:
    listed = fetch_json(client, f"{base_url}/calls")
    if not isinstance(listed, list):
        print("The call list was not a list.")
        raise SystemExit(1)
    rows = [item for item in listed if isinstance(item, dict)]
    selected = select_calls(rows, since, only_ids)
    details: list[dict[str, Any]] = []
    for call in selected:
        call_id = str(call.get("id") or "")
        if not call_id:
            continue
        detail = fetch_json(client, f"{base_url}/calls/{call_id}")
        if isinstance(detail, dict):
            details.append(detail)
    return details


# Every turn metric object stored on these calls.
def collect_turns(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for call in calls:
        raw = call.get("turnMetrics")
        if not isinstance(raw, list):
            continue
        turns.extend(item for item in raw if isinstance(item, dict))
    return turns


# True when this turn belongs in the named group.
def in_group(turn: dict[str, Any], group: str) -> bool:
    if group == "all":
        return True
    return turn.get("kind") == group


# Numbers for one component, skipping nulls and anything that is not a number.
def component_values(turns: list[dict[str, Any]], component: str) -> list[float]:
    values: list[float] = []
    for turn in turns:
        value = turn.get(component)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values.append(float(value))
    return values


# Middle value. An even count uses the average of the two middle values.
def median(values: list[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# 95th percentile by nearest rank: the value at ceil(0.95 * n), counting from 1.
def p95(values: list[float]) -> float:
    ordered = sorted(values)
    rank = math.ceil(0.95 * len(ordered))
    index = min(max(rank, 1), len(ordered)) - 1
    return ordered[index]


# Print a whole number of milliseconds without a trailing .0.
def format_ms(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


# Durations for one table group. FAQ lookups count only on the kb rows.
def http_tool_durations(calls: list[dict[str, Any]], group: str) -> list[float]:
    values: list[float] = []
    for call in calls:
        raw = call.get("toolCalls")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if group == "kb":
                if name != "lookup_faq":
                    continue
            else:
                if item.get("httpCalled") is not True:
                    continue
                if group == "plain":
                    continue
                if group == "tool" and name == "lookup_faq":
                    continue
            value = item.get("durationMs")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            values.append(float(value))
    return values


# How many clinic requests timed out, out of how many were really sent.
def timeout_line(calls: list[dict[str, Any]]) -> str:
    http_calls = 0
    timeouts = 0
    for call in calls:
        raw = call.get("toolCalls")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict) or item.get("httpCalled") is not True:
                continue
            http_calls += 1
            if item.get("outcome") == "timeout":
                timeouts += 1
    return f"Tool timeouts: {timeouts} of {http_calls} HTTP tool calls"


# Timeouts plus clinic-unavailable attempts, out of the same HTTP calls.
def failure_line(calls: list[dict[str, Any]]) -> str:
    http_calls = 0
    failures = 0
    for call in calls:
        raw = call.get("toolCalls")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict) or item.get("httpCalled") is not True:
                continue
            http_calls += 1
            if item.get("outcome") in {"timeout", "unavailable"}:
                failures += 1
    return f"Tool failures (timeout + unavailable): {failures} of {http_calls}"


# One markdown table. n is how many non-null values that row used.
def render_table(turns: list[dict[str, Any]], calls: list[dict[str, Any]]) -> str:
    lines = [
        "| group | component | n | median ms | p95 ms |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for group in GROUPS:
        grouped = [turn for turn in turns if in_group(turn, group)]
        for component in COMPONENTS:
            if component == "toolDurationMs":
                values = http_tool_durations(calls, group)
            else:
                values = component_values(grouped, component)
            if not values:
                lines.append(f"| {group} | {component} | 0 |  |  |")
                continue
            lines.append(
                "| {group} | {component} | {count} | {mid} | {high} |".format(
                    group=group,
                    component=component,
                    count=len(values),
                    mid=format_ms(median(values)),
                    high=format_ms(p95(values)),
                )
            )
    return "\n".join(lines)


# The warning line when the all-turns group has fewer than 30 turns, else empty.
def sample_warning(turn_count: int) -> str:
    if turn_count >= 30:
        return ""
    return (
        f"WARNING: the all-turns group has n={turn_count}, which is below 30. "
        "These numbers can move a lot until there are more turns."
    )


# Header, warning, and table as one markdown document.
def render_report(calls: list[dict[str, Any]], turns: list[dict[str, Any]]) -> str:
    warning = sample_warning(len(turns))
    parts = [
        "# Latency report",
        "",
        f"Calls: {len(calls)}. Turns: {len(turns)}.",
        "",
        "n is the number of non-null values used for that row. Nulls are ignored.",
        "",
    ]
    if warning:
        parts.extend([warning, ""])
    parts.append(render_table(turns, calls))
    parts.extend(["", timeout_line(calls), failure_line(calls), ""])
    return "\n".join(parts)


# Read command-line options.
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print latency medians from saved calls.")
    parser.add_argument("--since", help="Only calls that started on or after this ISO date.")
    parser.add_argument("--calls", help="Comma-separated call ids, such as id1,id2.")
    return parser.parse_args(argv)


# Fetch the calls, print the table, and write data/latency-report.md.
def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    since = parse_time(args.since) if args.since else None
    if args.since and since is None:
        print("--since must be an ISO date, such as 2026-11-01 or 2026-11-01T00:00:00Z.")
        raise SystemExit(1)
    only_ids = None
    if args.calls:
        only_ids = {item.strip() for item in args.calls.split(",") if item.strip()}
    base_url = require_env("API_BASE_URL").rstrip("/")
    api_key = require_env("API_KEY")
    headers = {"X-API-Key": api_key}
    try:
        with httpx.Client(headers=headers, timeout=30.0) as client:
            calls = load_calls(client, base_url, since, only_ids)
    except httpx.HTTPError as exc:
        print(f"Could not read calls from the API: {exc}")
        raise SystemExit(1) from exc
    turns = collect_turns(calls)
    report = render_report(calls, turns)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
