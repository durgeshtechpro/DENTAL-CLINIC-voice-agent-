"""Turn one call's usage into a cost breakdown from api/pricing.json."""

import json
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().parent / "pricing.json"


# Read the price file. A broken file becomes empty rates so costing still returns numbers.
def load_pricing() -> dict[str, Any]:
    try:
        loaded = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"currency": "USD", "rates": {}}
    if not isinstance(loaded, dict):
        return {"currency": "USD", "rates": {}}
    return loaded


# Read a usage or duration number. The second value is True when it was missing.
def _usage_number(source: Any, key: str) -> tuple[float, bool]:
    if not isinstance(source, dict) or key not in source or source[key] is None:
        return 0.0, True
    value = source[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return 0.0, True
    return float(value), False


# Read one rate. The second value is True when the rate is missing or still zero.
def _rate(block: Any, key: str) -> tuple[float, bool]:
    if not isinstance(block, dict) or key not in block or block[key] is None:
        return 0.0, True
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0, True
    number = float(value)
    return number, number == 0.0


# One cost line: the money and the quantity that produced it.
def _part(amount: float, quantity: float | dict[str, int]) -> dict[str, Any]:
    return {"amount": round(amount, 6), "quantity": quantity}


# Price one saved call result. Missing usage or a zero rate is still a number, marked estimated.
def compute_cost(result_json: dict[str, Any] | None, pricing: dict[str, Any] | None = None) -> dict[str, Any]:
    file_data = pricing if pricing is not None else load_pricing()
    rates = file_data.get("rates") if isinstance(file_data, dict) else {}
    if not isinstance(rates, dict):
        rates = {}
    currency = file_data.get("currency") if isinstance(file_data, dict) else None
    if not isinstance(currency, str) or not currency.strip():
        currency = "USD"

    result = result_json if isinstance(result_json, dict) else {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    estimated = not isinstance(result.get("usage"), dict)

    duration, duration_missing = _usage_number(result, "durationSeconds")
    audio, audio_missing = _usage_number(usage, "sttAudioSeconds")
    prompt_tokens, prompt_missing = _usage_number(usage, "llmPromptTokens")
    completion_tokens, completion_missing = _usage_number(usage, "llmCompletionTokens")
    characters, character_missing = _usage_number(usage, "ttsCharacters")
    if duration_missing or audio_missing or prompt_missing or completion_missing or character_missing:
        estimated = True

    phone_rate, phone_estimated = _rate(rates.get("telephony"), "perMinute")
    stt_rate, stt_estimated = _rate(rates.get("stt"), "perAudioMinute")
    prompt_rate, prompt_rate_estimated = _rate(rates.get("llm"), "perMillionPromptTokens")
    completion_rate, completion_rate_estimated = _rate(rates.get("llm"), "perMillionCompletionTokens")
    tts_rate, tts_estimated = _rate(rates.get("tts"), "perMillionCharacters")
    server_rate, server_estimated = _rate(rates.get("server"), "perMinute")
    if any(
        (
            phone_estimated,
            stt_estimated,
            prompt_rate_estimated,
            completion_rate_estimated,
            tts_estimated,
            server_estimated,
        )
    ):
        estimated = True

    phone_minutes = duration / 60.0
    audio_minutes = audio / 60.0
    telephony_amount = phone_minutes * phone_rate
    stt_amount = audio_minutes * stt_rate
    llm_amount = (prompt_tokens / 1_000_000.0) * prompt_rate + (
        completion_tokens / 1_000_000.0
    ) * completion_rate
    tts_amount = (characters / 1_000_000.0) * tts_rate
    server_amount = phone_minutes * server_rate
    total = telephony_amount + stt_amount + llm_amount + tts_amount + server_amount

    return {
        "telephony": _part(telephony_amount, round(phone_minutes, 6)),
        "stt": _part(stt_amount, round(audio_minutes, 6)),
        "llm": _part(
            llm_amount,
            {"promptTokens": int(prompt_tokens), "completionTokens": int(completion_tokens)},
        ),
        "tts": _part(tts_amount, int(characters)),
        "server": _part(server_amount, round(phone_minutes, 6)),
        "total": round(total, 6),
        "currency": currency,
        "ratesUsed": rates,
        "estimated": estimated,
    }
