"""Estimate what 1,000 calls a day would cost, in rupees."""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

# Hidden costs added on top of the vendor prices. Edit these numbers in one place.
ASSUMPTIONS = {
    "failedMinutesPct": 5,
    "recordingObservabilityPerMinuteUsd": 0.01,
    "platformFeeMonthlyUsd": 50,
    "forexMarkupPct": 2,
    "gstPct": 18,
}
# Costs this model does not try to price.
NOT_INCLUDED = (
    "engineering time",
    "monitoring",
    "support",
    "carrier minimum commitments",
    "concurrency upgrades",
    "database hosting",
)
# Phone calls use SIP. This is the example rate unless --telephony-per-minute is set.
PHONE_TELEPHONY_PER_MINUTE = 0.012
MIN_CALL_SECONDS = 20
ROOT = Path(__file__).resolve().parent.parent
PRICING_PATH = ROOT / "api" / "pricing.json"
REPORT_PATH = ROOT / "data" / "cost-model.md"


@dataclass
class Measured:
    calls: int
    ignored_short: int
    ignored_no_usage: int
    minutes: float
    stt_minutes_per_minute: float
    prompt_tokens_per_minute: float
    completion_tokens_per_minute: float
    characters_per_minute: float


@dataclass
class Rates:
    telephony: float
    stt: float
    prompt: float
    completion: float
    tts: float
    server: float
    usd_inr: float
    notes: dict[str, str]


@dataclass
class Volume:
    calls_per_day: float
    minutes_per_call: float
    days: float

    # Planned call minutes in one day.
    def minutes_per_day(self) -> float:
        return self.calls_per_day * self.minutes_per_call

    # Planned call minutes across the whole month.
    def minutes_per_month(self) -> float:
        return self.minutes_per_day() * self.days


# Read one required setting from the environment, or stop with a short message.
def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing {name}. Set it in the environment and run this script again.")
        raise SystemExit(1)
    return value


# Read a non-negative number from a JSON object, or None when it is missing.
def number_or_none(source: object, key: str) -> float | None:
    if not isinstance(source, dict) or key not in source or source[key] is None:
        return None
    value = source[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return float(value)


# Read api/pricing.json using the same rate names as the call API.
def load_pricing(usd_inr_override: float | None) -> tuple[Rates, float]:
    try:
        loaded = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Could not read {PRICING_PATH}: {exc}")
        raise SystemExit(1) from exc
    if not isinstance(loaded, dict):
        print("pricing.json was not an object.")
        raise SystemExit(1)
    rates = loaded.get("rates")
    if not isinstance(rates, dict):
        print("pricing.json has no rates object.")
        raise SystemExit(1)
    file_fx = number_or_none(loaded, "usdToInr")
    usd_inr = usd_inr_override if usd_inr_override is not None else file_fx
    if usd_inr is None or usd_inr <= 0:
        print("usdToInr is missing. Pass --usd-inr.")
        raise SystemExit(1)
    telephony = _rate(rates.get("telephony"), "perMinute")
    stt = _rate(rates.get("stt"), "perAudioMinute")
    prompt = _rate(rates.get("llm"), "perMillionPromptTokens")
    completion = _rate(rates.get("llm"), "perMillionCompletionTokens")
    tts = _rate(rates.get("tts"), "perMillionCharacters")
    server = _rate(rates.get("server"), "perMinute")
    notes = {
        "telephony": _note(rates.get("telephony")),
        "stt": _note(rates.get("stt")),
        "llm": _note(rates.get("llm")),
        "tts": _note(rates.get("tts")),
        "server": _note(rates.get("server")),
    }
    parsed = Rates(telephony, stt, prompt, completion, tts, server, usd_inr, notes)
    return parsed, file_fx or usd_inr


# Read one price. Stop if that price is missing.
def _rate(block: object, key: str) -> float:
    value = number_or_none(block, key)
    if value is None:
        print(f"pricing.json is missing rates.{key}.")
        raise SystemExit(1)
    return value


# The note stored next to a price, or a blank string.
def _note(block: object) -> str:
    if not isinstance(block, dict):
        return ""
    note = block.get("note")
    return note.strip() if isinstance(note, str) else ""


# Download one JSON document.
def fetch_json(client: httpx.Client, url: str) -> Any:
    response = client.get(url)
    response.raise_for_status()
    return response.json()


# Download completed calls, then each call's full record.
def load_completed_calls(client: httpx.Client, base_url: str) -> list[dict[str, Any]]:
    listed = fetch_json(client, f"{base_url}/calls")
    if not isinstance(listed, list):
        print("The call list was not a list.")
        raise SystemExit(1)
    details: list[dict[str, Any]] = []
    for item in listed:
        if not isinstance(item, dict) or item.get("status") != "completed":
            continue
        call_id = str(item.get("id") or "")
        if not call_id:
            continue
        detail = fetch_json(client, f"{base_url}/calls/{call_id}")
        if isinstance(detail, dict):
            details.append(detail)
    return details


# Average the saved usage over calls that lasted at least 20 seconds.
def measure(calls: list[dict[str, Any]]) -> Measured:
    used = 0
    ignored_short = 0
    ignored_no_usage = 0
    minutes = 0.0
    stt_minutes = 0.0
    prompt_tokens = 0.0
    completion_tokens = 0.0
    characters = 0.0
    for call in calls:
        seconds = number_or_none(call, "durationSeconds")
        if seconds is None:
            ignored_no_usage += 1
            continue
        if seconds < MIN_CALL_SECONDS:
            ignored_short += 1
            continue
        usage = call.get("usage")
        if not isinstance(usage, dict):
            ignored_no_usage += 1
            continue
        audio = number_or_none(usage, "sttAudioSeconds") or 0.0
        prompt = number_or_none(usage, "llmPromptTokens") or 0.0
        completion = number_or_none(usage, "llmCompletionTokens") or 0.0
        spoken = number_or_none(usage, "ttsCharacters") or 0.0
        call_minutes = seconds / 60.0
        used += 1
        minutes += call_minutes
        stt_minutes += audio / 60.0
        prompt_tokens += prompt
        completion_tokens += completion
        characters += spoken
    if used == 0 or minutes <= 0:
        print(
            "No completed call lasted at least 20 seconds with saved usage. "
            "This model will not invent usage numbers."
        )
        raise SystemExit(1)
    return Measured(
        calls=used,
        ignored_short=ignored_short,
        ignored_no_usage=ignored_no_usage,
        minutes=minutes,
        stt_minutes_per_minute=stt_minutes / minutes,
        prompt_tokens_per_minute=prompt_tokens / minutes,
        completion_tokens_per_minute=completion_tokens / minutes,
        characters_per_minute=characters / minutes,
    )


# One priced part of a call minute.
def component_usd(name: str, measured: Measured, rates: Rates) -> tuple[str, str, float]:
    if name == "telephony":
        quantity = "1 call minute"
        rate = f"${rates.telephony:.6f} per minute"
        usd = rates.telephony
    elif name == "stt":
        quantity = f"{measured.stt_minutes_per_minute:.4f} audio minutes"
        rate = f"${rates.stt:.6f} per audio minute"
        usd = measured.stt_minutes_per_minute * rates.stt
    elif name == "llm":
        quantity = (
            f"{measured.prompt_tokens_per_minute:.1f} prompt tokens, "
            f"{measured.completion_tokens_per_minute:.1f} completion tokens"
        )
        rate = (
            f"${rates.prompt:g} / ${rates.completion:g} per million"
        )
        usd = (measured.prompt_tokens_per_minute / 1_000_000.0) * rates.prompt
        usd += (measured.completion_tokens_per_minute / 1_000_000.0) * rates.completion
    elif name == "tts":
        quantity = f"{measured.characters_per_minute:.1f} characters"
        rate = f"${rates.tts:g} per million characters"
        usd = (measured.characters_per_minute / 1_000_000.0) * rates.tts
    else:
        quantity = "1 call minute"
        rate = f"${rates.server:.6f} per minute"
        usd = rates.server
    return quantity, rate, usd


# Raw vendor cost of one call minute, in rupees.
def raw_inr_per_minute(measured: Measured, rates: Rates) -> float:
    total_usd = 0.0
    for name in ("telephony", "stt", "llm", "tts", "server"):
        _quantity, _rate, usd = component_usd(name, measured, rates)
        total_usd += usd
    return total_usd * rates.usd_inr


# The vendor table for one configuration.
def raw_table(measured: Measured, rates: Rates) -> tuple[str, float]:
    lines = [
        "| component | quantity per minute | rate | USD per minute | INR per minute |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    total_usd = 0.0
    for name in ("telephony", "stt", "llm", "tts", "server"):
        quantity, rate, usd = component_usd(name, measured, rates)
        total_usd += usd
        lines.append(
            f"| {name} | {quantity} | {rate} | {usd:.6f} | {usd * rates.usd_inr:.4f} |"
        )
    total_inr = total_usd * rates.usd_inr
    lines.append(f"| total |  |  | {total_usd:.6f} | {total_inr:.4f} |")
    return "\n".join(lines), total_inr


# Scale a per-minute rupee cost up to one call, one day, and one month.
def scale_lines(inr_per_minute: float, volume: Volume) -> list[str]:
    per_call = inr_per_minute * volume.minutes_per_call
    per_day = inr_per_minute * volume.minutes_per_day()
    per_month = inr_per_minute * volume.minutes_per_month()
    return [
        f"Per minute: Rs {inr_per_minute:.4f}",
        f"Per call ({volume.minutes_per_call:g} min): Rs {per_call:.2f}",
        f"Per day ({volume.calls_per_day:g} calls): Rs {per_day:.2f}",
        f"Per {volume.days:g}-day month: Rs {per_month:.2f}",
    ]


# Add the hidden costs, each as its own row, on top of the raw per-minute total.
def realistic_table(raw_inr: float, rates: Rates, volume: Volume) -> tuple[str, float]:
    month_minutes = volume.minutes_per_month()
    failed = raw_inr * (ASSUMPTIONS["failedMinutesPct"] / 100.0)
    recording = ASSUMPTIONS["recordingObservabilityPerMinuteUsd"] * rates.usd_inr
    platform = (ASSUMPTIONS["platformFeeMonthlyUsd"] / month_minutes) * rates.usd_inr
    before_forex = raw_inr + failed + recording + platform
    forex = before_forex * (ASSUMPTIONS["forexMarkupPct"] / 100.0)
    before_gst = before_forex + forex
    gst = before_gst * (ASSUMPTIONS["gstPct"] / 100.0)
    total = before_gst + gst
    rows = [
        ("Raw vendor total", raw_inr),
        (f"Failed minutes ({ASSUMPTIONS['failedMinutesPct']:g}% extra)", failed),
        ("Recording and observability", recording),
        (
            f"Platform fee (USD {ASSUMPTIONS['platformFeeMonthlyUsd']:g} / month, spread over the minutes)",
            platform,
        ),
        (f"Forex markup ({ASSUMPTIONS['forexMarkupPct']:g}% before GST)", forex),
        (f"GST ({ASSUMPTIONS['gstPct']:g}%)", gst),
        ("Realistic total", total),
    ]
    lines = [
        "| cost | INR per minute | INR per call | INR per day | INR per month |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, per_minute in rows:
        lines.append(
            "| {label} | {minute:.4f} | {call:.2f} | {day:.2f} | {month:.2f} |".format(
                label=label,
                minute=per_minute,
                call=per_minute * volume.minutes_per_call,
                day=per_minute * volume.minutes_per_day(),
                month=per_minute * volume.minutes_per_month(),
            )
        )
    return "\n".join(lines), total


# One configuration: browser prices, or phone prices with a higher telephony rate.
def configuration_report(
    title: str,
    measured: Measured,
    rates: Rates,
    volume: Volume,
) -> str:
    table, total_inr = raw_table(measured, rates)
    realistic, _realistic_total = realistic_table(total_inr, rates, volume)
    parts = [
        f"## {title}",
        "",
        "### Raw cost",
        "",
        table,
        "",
        *scale_lines(total_inr, volume),
        "",
        "### Realistic cost",
        "",
        realistic,
        "",
    ]
    return "\n".join(parts)


# Raw per-minute rupees if one price or one usage number changes.
def sensitivity(measured: Measured, browser: Rates, phone: Rates) -> str:
    scale_tts = Rates(
        browser.telephony,
        browser.stt,
        browser.prompt,
        browser.completion,
        37.4,
        browser.server,
        browser.usd_inr,
        browser.notes,
    )
    phone_scale = Rates(
        phone.telephony,
        phone.stt,
        phone.prompt,
        phone.completion,
        37.4,
        phone.server,
        phone.usd_inr,
        phone.notes,
    )
    dear_stt = Rates(
        browser.telephony,
        0.0077,
        browser.prompt,
        browser.completion,
        browser.tts,
        browser.server,
        browser.usd_inr,
        browser.notes,
    )
    phone_dear_stt = Rates(
        phone.telephony,
        0.0077,
        phone.prompt,
        phone.completion,
        phone.tts,
        phone.server,
        phone.usd_inr,
        phone.notes,
    )
    busier = Measured(
        measured.calls,
        measured.ignored_short,
        measured.ignored_no_usage,
        measured.minutes,
        measured.stt_minutes_per_minute,
        measured.prompt_tokens_per_minute,
        measured.completion_tokens_per_minute,
        600.0,
    )
    cases = [
        ("Measured rates", measured, browser, phone),
        ("Cartesia Scale, $37.4 per million characters", measured, scale_tts, phone_scale),
        ("Deepgram streaming, $0.0077 per minute", measured, dear_stt, phone_dear_stt),
        ("600 TTS characters per minute", busier, browser, phone),
    ]
    lines = [
        "## Sensitivity",
        "",
        "Each row changes one thing and shows the new raw total per minute.",
        "",
        "| change | browser INR per minute | phone INR per minute |",
        "| --- | ---: | ---: |",
    ]
    for label, usage, browser_rates, phone_rates in cases:
        lines.append(
            f"| {label} | {raw_inr_per_minute(usage, browser_rates):.4f} | "
            f"{raw_inr_per_minute(usage, phone_rates):.4f} |"
        )
    lines.append("")
    return "\n".join(lines)


# The notes stored beside each price.
def notes_section(rates: Rates, file_fx: float) -> str:
    lines = ["## Pricing notes", ""]
    lines.append(f"USD to INR in the file: {file_fx:g}. Used for this report: {rates.usd_inr:g}.")
    lines.append("")
    for name in ("telephony", "stt", "llm", "tts", "server"):
        note = rates.notes.get(name) or "(no note)"
        lines.append(f"- {name}: {note}")
    lines.append("")
    return "\n".join(lines)


# How the measured calls were turned into per-minute usage.
def usage_section(measured: Measured) -> str:
    lines = [
        "## Measured usage",
        "",
        (
            f"Used {measured.calls} completed calls, {measured.minutes:.2f} minutes. "
            f"Ignored {measured.ignored_short} completed calls shorter than {MIN_CALL_SECONDS} seconds"
            f" and {measured.ignored_no_usage} completed calls with no saved usage or duration."
        ),
        "",
        "Averages below are per call minute (usage divided by those minutes).",
        "",
        "| measure | per call minute |",
        "| --- | ---: |",
        f"| stt audio minutes (sttAudioSeconds / 60) | {measured.stt_minutes_per_minute:.4f} |",
        f"| llm prompt tokens | {measured.prompt_tokens_per_minute:.2f} |",
        f"| llm completion tokens | {measured.completion_tokens_per_minute:.2f} |",
        f"| tts characters | {measured.characters_per_minute:.2f} |",
        "",
    ]
    return "\n".join(lines)


# The costs this sheet leaves out.
def excluded_section() -> str:
    lines = [
        "## Not included",
        "",
        "These hidden costs are not in the tables:",
        "",
    ]
    lines.extend(f"- {item}" for item in NOT_INCLUDED)
    lines.append("")
    return "\n".join(lines)


# Read the command-line options.
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Price 1,000 calls a day for browser and phone."
    )
    parser.add_argument("--calls-per-day", type=float, default=1000)
    parser.add_argument("--minutes-per-call", type=float, default=3)
    parser.add_argument("--days", type=float, default=30)
    parser.add_argument(
        "--telephony-per-minute",
        type=float,
        default=None,
        help="Phone SIP rate in USD per minute. Default 0.012. Browser stays on pricing.json.",
    )
    parser.add_argument("--usd-inr", type=float, default=None, help="Override pricing.json usdToInr.")
    return parser.parse_args(argv)


# Fetch usage, price browser and phone, and write data/cost-model.md.
def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.calls_per_day <= 0 or args.minutes_per_call <= 0 or args.days <= 0:
        print("--calls-per-day, --minutes-per-call, and --days must be greater than zero.")
        raise SystemExit(1)
    if args.telephony_per_minute is not None and args.telephony_per_minute < 0:
        print("--telephony-per-minute cannot be negative.")
        raise SystemExit(1)
    if args.usd_inr is not None and args.usd_inr <= 0:
        print("--usd-inr must be greater than zero.")
        raise SystemExit(1)
    browser, file_fx = load_pricing(args.usd_inr)
    phone_rate = (
        PHONE_TELEPHONY_PER_MINUTE
        if args.telephony_per_minute is None
        else args.telephony_per_minute
    )
    phone = Rates(
        phone_rate,
        browser.stt,
        browser.prompt,
        browser.completion,
        browser.tts,
        browser.server,
        browser.usd_inr,
        browser.notes,
    )
    volume = Volume(args.calls_per_day, args.minutes_per_call, args.days)
    base_url = require_env("API_BASE_URL").rstrip("/")
    api_key = require_env("API_KEY")
    try:
        with httpx.Client(headers={"X-API-Key": api_key}, timeout=30.0) as client:
            calls = load_completed_calls(client, base_url)
    except httpx.HTTPError as exc:
        print(f"Could not read calls from the API: {exc}")
        raise SystemExit(1) from exc
    measured = measure(calls)
    report = "\n".join(
        [
            "# Cost model",
            "",
            f"Date: {date.today().isoformat()}",
            "",
            (
                f"Scenario: {volume.calls_per_day:g} calls a day, "
                f"{volume.minutes_per_call:g} minutes each, for {volume.days:g} days."
            ),
            "",
            usage_section(measured).rstrip(),
            "",
            notes_section(browser, file_fx).rstrip(),
            "",
            configuration_report(
                "Browser (pricing.json telephony)",
                measured,
                browser,
                volume,
            ).rstrip(),
            "",
            configuration_report(
                f"Phone (telephony ${phone.telephony:.6f} per minute)",
                measured,
                phone,
                volume,
            ).rstrip(),
            "",
            excluded_section().rstrip(),
            "",
            sensitivity(measured, browser, phone).rstrip(),
            "",
        ]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
