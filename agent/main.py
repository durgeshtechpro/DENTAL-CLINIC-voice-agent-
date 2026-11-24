from pathlib import Path

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, JobProcess, TurnHandlingOptions
from livekit.plugins import cartesia, deepgram, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

INSTRUCTIONS = (
    "You are the front desk of Bright Smile Dental. "
    "Keep replies to one or two short sentences. You are on a phone call."
)
GREETING = "Hi, this is Bright Smile Dental. How can I help?"


# Load the Silero speech detector once, before a call starts.
def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


class Assistant(Agent):
    # Store the front-desk instructions the model follows on every reply.
    def __init__(self) -> None:
        super().__init__(instructions=INSTRUCTIONS)


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
