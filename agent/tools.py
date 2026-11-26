import json
import random
import time
from datetime import datetime
from typing import Any

import httpx
from livekit.agents import RunContext, function_tool
from livekit.agents.llm import RawFunctionTool

from http_client import get_http_client
from recorder import call_turns, recent_caller_lines, report_tool_call

FILLER_PHRASES = (
    "Let me check that for you.",
    "One moment while I look that up.",
    "I'll check the schedule now.",
)
TAKEN_NOTE = "Tell the caller this slot is taken and offer these alternatives."
TIMEOUT_NOTE = "The system is slow. Apologise briefly and offer to try again."
UNAVAILABLE_NOTE = (
    "The system is not responding. Apologise and offer to try again "
    "or have the clinic call back."
)
NAME_NOT_GIVEN = {
    "status": "name_not_given",
    "note": "The caller has not told you their name. Ask for their name. Do not guess.",
}
REPEATED_MISMATCH = {
    "status": "repeated_mismatch",
    "note": (
        "Stop retrying this number. Say one short sentence to the caller, "
        "then ask them to repeat the phone number slowly in groups of three or four digits."
    ),
}
# Name of the field on the call object that remembers the last wrong phone.
_REJECT_FIELD = "_rejected_phone"
# Caller words that accept the number the agent just read back.
_YES_PHRASES = (
    "that's right",
    "that is right",
    "go ahead",
    "confirmed",
    "exactly",
    "correct",
    "yeah",
    "yep",
    "yup",
    "yes",
    "sure",
    "okay",
    "right",
    "ok",
)
# Words that mean the caller did not accept the number.
_NO_WORDS = ("incorrect", "wrong", "not", "wait", "no")
_DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


# Turn spoken numbers into digits.
# "eight three seven four zero double one six three four" -> "8374011634"
# "triple two" -> "222"
# "oh one" -> "01"
# "call 8374" -> "8374"
def spoken_digits(text: str) -> str:
    words: list[str] = []
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))

    digits: list[str] = []
    repeat = 1
    for word in words:
        if word == "double":
            repeat = 2
            continue
        if word == "triple":
            repeat = 3
            continue
        piece = _DIGIT_WORDS.get(word)
        if piece is None and word.isdigit():
            piece = word
        if piece is None:
            repeat = 1
            continue
        digits.append(piece * repeat)
        repeat = 1
    return "".join(digits)


# Keep digits, then drop a leading 91 or 0 when that still leaves 10 digits.
def clean_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("91") and len(digits) - 2 == 10:
        return digits[2:]
    if digits.startswith("0") and len(digits) - 1 == 10:
        return digits[1:]
    return digits


# Every finished caller line in this call, oldest first.
def caller_lines(ctx: RunContext) -> list[str]:
    return recent_caller_lines(ctx.session, 10000)


# Digits from the caller's last 6 finished lines, joined in order.
def caller_digit_stream(ctx: RunContext) -> str:
    lines = recent_caller_lines(ctx.session, 6)
    return "".join(spoken_digits(line) for line in lines)


# How many caller lines exist, plus the latest line, so we can see a new utterance.
def caller_marker(ctx: RunContext) -> tuple[int, str]:
    lines = caller_lines(ctx)
    latest = lines[-1] if lines else ""
    return (len(lines), latest)


# Words made of letters only, so punctuation does not hide a name.
def letter_words(text: str) -> list[str]:
    words: list[str] = []
    current: list[str] = []
    for ch in text:
        if ch.isalpha():
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


# The newest 10 spoken digits, or None when the caller has not given 10 yet.
# Newest turn "yes", older turn "eight three seven four zero double one six three four" -> "8374011634"
# Split turns "eight three seven four" then "zero double one six three four" -> "8374011634"
def phone_candidate(lines: list[str]) -> str | None:
    chunks: list[str] = []
    total = 0
    for line in reversed(lines):
        chunk = spoken_digits(line)
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= 10:
            break
    if total < 10:
        return None
    ordered = "".join(reversed(chunks))
    return ordered[-10:]


# Print one rejected tool argument with the current time.
def log_reject(tool_name: str, status: str, argument: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} tool={tool_name} {status} argument={argument}")


# Block a book_slot name the caller never said. None means the name is allowed.
def name_block(
    ctx: RunContext, tool_name: str, raw_arguments: dict[str, Any]
) -> dict[str, str] | None:
    if tool_name != "book_slot":
        return None
    argument = str(raw_arguments.get("name") or "")
    spoken = {
        word.lower()
        for line in caller_lines(ctx)
        for word in letter_words(line)
        if len(word) >= 3
    }
    given = [word.lower() for word in letter_words(argument) if len(word) >= 3]
    if any(word in spoken for word in given):
        return None
    log_reject(tool_name, "name_not_given", argument)
    return dict(NAME_NOT_GIVEN)


# The call object for this session, where the last wrong phone is kept.
def call_watch(ctx: RunContext) -> Any | None:
    try:
        return ctx.session.userdata
    except Exception:
        return None


# True when this book_slot phone was already rejected and the caller has not spoken since.
def repeated_phone(ctx: RunContext, cleaned: str) -> bool:
    watch = call_watch(ctx)
    state = getattr(watch, _REJECT_FIELD, None) if watch is not None else None
    if not state:
        return False
    if state.get("marker") != caller_marker(ctx):
        clear_rejected_phone(ctx)
        return False
    return state.get("phone") == cleaned


# Remember a rejected book_slot phone until the caller says something new.
def remember_rejected_phone(ctx: RunContext, cleaned: str) -> None:
    watch = call_watch(ctx)
    if watch is None:
        return
    try:
        setattr(watch, _REJECT_FIELD, {"phone": cleaned, "marker": caller_marker(ctx)})
    except Exception:
        return


# Forget a rejected phone after a number that matches the caller.
def clear_rejected_phone(ctx: RunContext) -> None:
    watch = call_watch(ctx)
    if watch is None:
        return
    try:
        if hasattr(watch, _REJECT_FIELD):
            delattr(watch, _REJECT_FIELD)
    except Exception:
        return


# Block a phone the caller did not say. None means send it. A match is not booked by itself.
def phone_block(
    ctx: RunContext, tool_name: str, raw_arguments: dict[str, Any]
) -> dict[str, str] | None:
    if "phone" not in raw_arguments:
        return None
    argument = str(raw_arguments.get("phone") or "")
    cleaned = clean_phone(argument)
    stream = caller_digit_stream(ctx)
    if cleaned and cleaned in stream:
        if tool_name == "book_slot":
            clear_rejected_phone(ctx)
        return None
    tail = stream[-15:]
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(
        f"{stamp} tool={tool_name} phone_mismatch argument={argument} stream_tail={tail}"
    )
    if tool_name == "book_slot":
        remember_rejected_phone(ctx, cleaned)
    candidate = phone_candidate(caller_lines(ctx))
    if candidate is None:
        return {
            "status": "phone_mismatch",
            "note": (
                "The phone number does not match what the caller said. "
                "Ask the caller to say the number again slowly in groups of "
                "three or four digits."
            ),
        }
    spaced = " ".join(candidate)
    return {
        "status": "phone_mismatch",
        "candidate": candidate,
        "note": (
            "You sent a phone number that does not match what the caller said. "
            f"The caller's number appears to be {spaced}. "
            "Read it back and wait for yes. "
            "Then call book_slot again using exactly these digits."
        ),
    }


# Lowercase the line and turn punctuation into spaces.
def _plain_words(text: str) -> str:
    cleaned = text.lower().replace("\u2019", "'").replace("`", "'")
    letters: list[str] = []
    for ch in cleaned:
        if ch.isalnum() or ch in {"'", " "}:
            letters.append(ch)
        else:
            letters.append(" ")
    return " ".join("".join(letters).split())


# True when the phrase is its own words inside the line.
def _has_phrase(spoken: str, phrase: str) -> bool:
    start = 0
    while True:
        index = spoken.find(phrase, start)
        if index < 0:
            return False
        before_ok = index == 0 or spoken[index - 1] == " "
        after = index + len(phrase)
        after_ok = after == len(spoken) or spoken[after] == " "
        if before_ok and after_ok:
            return True
        start = index + 1


# True when this caller line accepts a number and does not take it back.
def _caller_said_yes(text: str) -> bool:
    spoken = _plain_words(text)
    if not spoken or any(_has_phrase(spoken, word) for word in _NO_WORDS):
        return False
    return any(_has_phrase(spoken, phrase) for phrase in _YES_PHRASES)


# Print a booking-confirmation decision. Only the last 4 digits are logged.
def log_confirmation(decision: str, phone: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} book_slot {decision} phone_last4={phone[-4:]}")


# Block book_slot until the agent read these digits and the caller later said yes.
def confirmation_gate(ctx: RunContext, phone: str) -> dict[str, str] | None:
    turns = call_turns(ctx.session) if phone else []
    read_at: int | None = None
    for index, (role, text) in enumerate(turns):
        if role == "agent" and phone in spoken_digits(text):
            read_at = index
    if read_at is not None:
        later = [text for role, text in turns[read_at + 1 :] if role == "user"]
        if any(_caller_said_yes(text) for text in later):
            newest = _plain_words(later[-1]) if later else ""
            taken_back = any(_has_phrase(newest, word) for word in _NO_WORDS)
            if not taken_back:
                log_confirmation("confirmed", phone)
                return None
    log_confirmation("confirmation_required", phone)
    spaced = " ".join(phone)
    return {
        "status": "confirmation_required",
        "phone": phone,
        "note": (
            "Read this phone number back to the caller digit by digit right now: "
            f"{spaced}. Wait for the caller to say yes. Then call book_slot again "
            "with exactly these digits. If the caller says no, ask them to repeat "
            "the number slowly."
        ),
    }


# Stop a bad booking before the clinic is called.
# Order: name, then the same rejected phone, then the phone check, then read-back confirmation.
def booking_block(
    ctx: RunContext, tool_name: str, raw_arguments: dict[str, Any]
) -> dict[str, str] | None:
    blocked = name_block(ctx, tool_name, raw_arguments)
    if blocked is not None:
        return blocked
    if tool_name == "book_slot" and "phone" in raw_arguments:
        cleaned = clean_phone(str(raw_arguments.get("phone") or ""))
        if repeated_phone(ctx, cleaned):
            log_reject(tool_name, "repeated_mismatch", str(raw_arguments.get("phone") or ""))
            return dict(REPEATED_MISMATCH)
    blocked = phone_block(ctx, tool_name, raw_arguments)
    if blocked is not None:
        return blocked
    if tool_name != "book_slot" or "phone" not in raw_arguments:
        return None
    return confirmation_gate(ctx, clean_phone(str(raw_arguments.get("phone") or "")))


# Turn one config dict into a LiveKit tool that POSTs the model's arguments.
def build_http_tool(config: dict[str, Any]) -> RawFunctionTool:
    schema = {
        "name": config["name"],
        "description": config["description"],
        "parameters": config["parameters"],
    }

    # Say a short filler, call the URL, and hand the model plain JSON text.
    async def call_tool(ctx: RunContext, raw_arguments: dict[str, Any]) -> str:
        started = time.perf_counter()
        blocked = booking_block(ctx, config["name"], raw_arguments)
        http_called = False
        if blocked is not None:
            payload: Any = blocked
            outcome = "guard_blocked"
        else:
            outcome = "unavailable"
            http_called = True
            try:
                await ctx.session.say(random.choice(FILLER_PHRASES))
                started = time.perf_counter()
                timeout_seconds = config["http"]["timeoutMs"] / 1000
                client = await get_http_client()
                response = await client.request(
                    config["http"]["method"],
                    config["http"]["url"],
                    json=raw_arguments,
                    timeout=httpx.Timeout(timeout_seconds),
                )
                if response.status_code == 200:
                    payload = response.json()
                    outcome = "ok"
                elif response.status_code == 409:
                    payload = response.json()
                    if isinstance(payload, dict):
                        payload["note"] = TAKEN_NOTE
                    else:
                        payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
                    outcome = "unavailable"
                elif response.status_code == 422:
                    payload = response.json()
                    if isinstance(payload, dict) and payload.get("status") == "invalid_input":
                        field = payload.get("field") or "detail"
                        payload["note"] = (
                            "Do not retry with made-up values. "
                            f"Ask the caller for the correct {field}."
                        )
                    else:
                        payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
                    outcome = "http_error"
                else:
                    payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
                    outcome = "http_error"
            except httpx.TimeoutException:
                payload = {"error": "timeout", "note": TIMEOUT_NOTE}
                outcome = "timeout"
            except Exception:
                payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
                outcome = "unavailable"

        text = json.dumps(payload)
        duration_ms = int((time.perf_counter() - started) * 1000)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(
            f"{stamp} tool={config['name']} args={json.dumps(raw_arguments)} "
            f"result={text} duration_ms={duration_ms}"
        )
        report_tool_call(
            ctx.session,
            config["name"],
            raw_arguments,
            payload,
            duration_ms,
            http_called,
            outcome,
        )
        return text

    return function_tool(call_tool, raw_schema=schema)
