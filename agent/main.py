import json
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobProcess, TurnHandlingOptions
from livekit.plugins import cartesia, deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from lifecycle import CallLifecycle, end_call, log_call
from recorder import CallRecorder
from tools import build_http_tool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

CALL_CONFIG = {
    "greeting": "Hi, this is Bright Smile Dental. How can I help?",
    "maxDurationSeconds": 600,
    "inactivity": {
        "afterSeconds": 8,
        "message": "Are you still there?",
        "hangUpAfterSeconds": 20,
    },
}

TOOL_CONFIGS = [
    {
        "name": "check_slots",
        "description": "Find free appointment slots for a date",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Calendar date in YYYY-MM-DD",
                },
            },
            "required": ["date"],
        },
        "http": {
            "method": "POST",
            "url": "http://127.0.0.1:8001/slots",
            "timeoutMs": 4000,
        },
    },
    {
        "name": "book_slot",
        "description": "Book an appointment slot",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Calendar date in YYYY-MM-DD",
                },
                "time": {
                    "type": "string",
                    "description": "Appointment time in HH:MM",
                },
                "name": {"type": "string", "description": "Patient name"},
                "phone": {"type": "string", "description": "Patient phone number"},
            },
            "required": ["date", "time", "name", "phone"],
        },
        "http": {
            "method": "POST",
            "url": "http://127.0.0.1:8001/book",
            "timeoutMs": 4000,
        },
    },
]
TOOLS = [build_http_tool(config) for config in TOOL_CONFIGS]


# Build the front-desk instructions with today's real date and weekday.
def front_desk_instructions() -> str:
    today = date.today()
    return (
        "You are the front desk of Bright Smile Dental. "
        "Keep replies to one or two short sentences. You are on a phone call. "
        f"Today is {today.strftime('%A')}, {today.isoformat()}. "
        "Convert words like tomorrow or Friday to YYYY-MM-DD yourself. "
        "Before booking, ask for the patient's name and phone number. "
        "Say times like 'ten AM', not '10:00'. "
        "Never read raw JSON or error codes to the caller. "
        "If a booking fails because the slot is taken, say so and offer the alternatives. "
        "When the caller says goodbye or has nothing more to ask, say a short goodbye and call end_call."
    )


# Load the Silero speech detector once, before a call starts.
def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


# Read the room metadata string, or an empty string when the room has none.
def room_metadata(ctx: agents.JobContext) -> str:
    try:
        live = getattr(ctx.room, "metadata", "") or ""
    except Exception:
        live = ""
    if isinstance(live, str) and live.strip():
        return live
    try:
        stored = getattr(ctx.job.room, "metadata", "") or ""
    except Exception:
        return ""
    return stored if isinstance(stored, str) else ""


# Read the call id from room metadata, or None for a console call.
def call_id_from_room(ctx: agents.JobContext) -> str | None:
    try:
        raw = room_metadata(ctx).strip()
        if not raw:
            return None
        parsed = json.loads(raw)
        call_id = parsed.get("id") if isinstance(parsed, dict) else None
        if isinstance(call_id, str) and call_id.strip():
            return call_id.strip()
    except Exception:
        return None
    return None


# Keep a positive number from metadata, or None when the value is unusable.
def positive_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)


# Keep a tool config only when it has the fields the HTTP tool builder needs.
def usable_tool(item: object) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    http = item.get("http")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(item.get("description"), str) or not isinstance(item.get("parameters"), dict):
        return None
    if not isinstance(http, dict):
        return None
    method = http.get("method")
    url = http.get("url")
    timeout = http.get("timeoutMs")
    if not isinstance(method, str) or not method.strip() or not isinstance(url, str) or not url.strip():
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
        return None
    return item


# Use the room config when it is valid, and the built-in defaults otherwise.
def settings_from_room(ctx: agents.JobContext) -> tuple[str, str, dict[str, Any], list[Any]]:
    instructions = front_desk_instructions()
    greeting = str(CALL_CONFIG["greeting"])
    lifecycle = {
        "maxDurationSeconds": CALL_CONFIG["maxDurationSeconds"],
        "inactivity": dict(CALL_CONFIG["inactivity"]),
    }
    tools: list[Any] = [*TOOLS, end_call]
    try:
        raw = room_metadata(ctx).strip()
        if not raw:
            return instructions, greeting, lifecycle, tools
        parsed = json.loads(raw)
        config = parsed.get("config") if isinstance(parsed, dict) else None
        if not isinstance(config, dict):
            return instructions, greeting, lifecycle, tools
        prompt = config.get("systemPrompt")
        if isinstance(prompt, str) and prompt.strip():
            instructions = prompt
        greet = config.get("greeting")
        if isinstance(greet, str) and greet.strip():
            greeting = greet
        max_seconds = positive_number(config.get("maxDurationSeconds"))
        if max_seconds is not None:
            lifecycle["maxDurationSeconds"] = max_seconds
        inactivity = config.get("inactivity")
        if isinstance(inactivity, dict):
            merged = dict(CALL_CONFIG["inactivity"])
            after = positive_number(inactivity.get("afterSeconds"))
            hang_after = positive_number(inactivity.get("hangUpAfterSeconds"))
            message = inactivity.get("message")
            if after is not None:
                merged["afterSeconds"] = after
            if hang_after is not None:
                merged["hangUpAfterSeconds"] = hang_after
            if isinstance(message, str) and message.strip():
                merged["message"] = message
            if float(merged["hangUpAfterSeconds"]) >= float(merged["afterSeconds"]):
                lifecycle["inactivity"] = merged
        if isinstance(config.get("tools"), list):
            built: list[Any] = []
            for item in config["tools"]:
                tool_config = usable_tool(item)
                if tool_config is None:
                    continue
                try:
                    built.append(build_http_tool(tool_config))
                except Exception:
                    continue
            tools = [*built, end_call]
    except Exception:
        return (
            front_desk_instructions(),
            str(CALL_CONFIG["greeting"]),
            {
                "maxDurationSeconds": CALL_CONFIG["maxDurationSeconds"],
                "inactivity": dict(CALL_CONFIG["inactivity"]),
            },
            [*TOOLS, end_call],
        )
    return instructions, greeting, lifecycle, tools


class Assistant(Agent):
    # Give this call its instructions and tools.
    def __init__(self, instructions: str, tools: list[Any]) -> None:
        super().__init__(instructions=instructions, tools=tools)


# Open one voice session, then speak the greeting before the caller talks.
async def entrypoint(ctx: agents.JobContext) -> None:
    instructions, greeting, lifecycle_config, tools = settings_from_room(ctx)
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=groq.LLM(model="openai/gpt-oss-20b", reasoning_effort="low"),
        tts=cartesia.TTS(),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
        user_away_timeout=None,
    )
    watch = CallLifecycle(session, lifecycle_config)
    recorder = CallRecorder(call_id_from_room(ctx))
    watch.recorder = recorder
    session.userdata = watch
    recorder.attach(session)
    recorder.watch_room(ctx.room)

    # Save the transcript after the session closes, even if the close event was missed.
    async def save_call_result(_reason: str = "") -> None:
        await recorder.wait_saved()

    ctx.add_shutdown_callback(save_call_result)
    await session.start(room=ctx.room, agent=Assistant(instructions, tools))
    watch.start()
    log_call("greeting")
    await session.say(greeting)


server = AgentServer(setup_fnc=prewarm)
server.rtc_session(entrypoint)

if __name__ == "__main__":
    agents.cli.run_app(server)
