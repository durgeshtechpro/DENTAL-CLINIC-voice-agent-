from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobProcess, TurnHandlingOptions
from livekit.plugins import cartesia, deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from tools import build_http_tool

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

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
GREETING = "Hi, this is Bright Smile Dental. How can I help?"


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
        "If a booking fails because the slot is taken, say so and offer the alternatives."
    )


# Load the Silero speech detector once, before a call starts.
def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


class Assistant(Agent):
    # Give this call today's instructions and the clinic tools.
    def __init__(self) -> None:
        super().__init__(instructions=front_desk_instructions(), tools=TOOLS)


# Open one voice session, then speak the greeting before the caller talks.
async def entrypoint(ctx: agents.JobContext) -> None:
    session = AgentSession(
        stt=deepgram.STT(model="nova-3", language="en"),
        llm=groq.LLM(model="openai/gpt-oss-20b", reasoning_effort="low"),
        tts=cartesia.TTS(),
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(turn_detection=MultilingualModel()),
    )
    await session.start(room=ctx.room, agent=Assistant())
    await session.say(GREETING)


server = AgentServer(setup_fnc=prewarm)
server.rtc_session(entrypoint)

if __name__ == "__main__":
    agents.cli.run_app(server)
