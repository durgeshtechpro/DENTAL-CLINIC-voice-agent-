import asyncio
import time
from datetime import datetime

from livekit.agents import (
    RunContext,
    ToolExecutionUpdatedEvent,
    function_tool,
    get_job_context,
)
from livekit.agents.voice.agent_session import AgentSession
from livekit.agents.voice.speech_handle import SpeechHandle

MAX_DURATION_GOODBYE = (
    "I'm sorry, we have reached the time limit for this call. Goodbye."
)
INACTIVITY_GOODBYE = "Goodbye."
FALLBACK_GOODBYE = "Thanks for calling. Goodbye."
NOT_GOODBYE_NOTE = (
    "The caller has not said goodbye. Do not end the call. Continue the conversation."
)
# Phrases that mean the caller is done. Checked on the last finished caller line only.
_GOODBYE_PHRASES = (
    "goodbye",
    "bye",
    "that's all",
    "that is all",
    "nothing else",
    "no thanks",
    "see you",
    "have a good day",
)


# Print one call event with the current time.
def log_call(event: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} {event}")


# Watch silence and the call time limit, then end the call when either runs out.
class CallLifecycle:
    def __init__(self, session: AgentSession, config: dict) -> None:
        self._session = session
        self._after = float(config["inactivity"]["afterSeconds"])
        self._hang_after = float(config["inactivity"]["hangUpAfterSeconds"])
        self._message = str(config["inactivity"]["message"])
        self._max_seconds = float(config["maxDurationSeconds"])
        self._started = time.monotonic()
        self._silence_at: float | None = None
        self._prompted = False
        self._tools = 0
        self._in_prompt = False
        self.closing = False
        self.hangup_reason: str | None = None
        self.recorder: object | None = None
        self._task: asyncio.Task[None] | None = None

    # Start the background watch and listen for tool calls.
    def start(self) -> None:
        self._session.on("tool_execution_updated", self._on_tool)
        self._session.on("close", self._on_close)
        self._task = asyncio.create_task(self._run(), name="call_lifecycle")

    # Remember when a tool starts and when it finishes.
    def _on_tool(self, ev: ToolExecutionUpdatedEvent) -> None:
        kind = ev.update.type
        if kind == "tool_call_started":
            self._tools += 1
        elif kind == "tool_call_ended":
            self._tools = max(0, self._tools - 1)

    # Stop the watch when the session closes.
    def _on_close(self, _ev: object) -> None:
        self.closing = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    # True when nobody is talking and no tool is running.
    def _quiet(self) -> bool:
        return (
            not self.closing
            and not self._in_prompt
            and self._tools == 0
            and self._session.user_state == "listening"
            and self._session.agent_state == "listening"
        )

    # Check the silence clock and the max call length until the call ends.
    async def _run(self) -> None:
        try:
            while not self.closing:
                await asyncio.sleep(0.2)
                if self.closing:
                    return
                if time.monotonic() - self._started >= self._max_seconds:
                    if await self._say_and_hang(
                        MAX_DURATION_GOODBYE,
                        "max_duration",
                        interruptible=False,
                    ):
                        return
                if not self._quiet():
                    if not self._in_prompt:
                        self._silence_at = None
                        self._prompted = False
                    continue
                now = time.monotonic()
                if self._silence_at is None:
                    self._silence_at = now
                    self._prompted = False
                    continue
                elapsed = now - self._silence_at
                if not self._prompted and elapsed >= self._after:
                    self._prompted = True
                    log_call("inactivity prompt")
                    self._in_prompt = True
                    try:
                        await self._session.say(self._message)
                    finally:
                        self._in_prompt = False
                    if self._session.user_state == "speaking":
                        self._silence_at = None
                        self._prompted = False
                    continue
                if self._prompted and elapsed >= self._hang_after:
                    if await self._say_and_hang(
                        INACTIVITY_GOODBYE,
                        "inactivity",
                        interruptible=False,
                    ):
                        return
        except asyncio.CancelledError:
            return

    # Say one final line, wait until it finishes, then hang up.
    async def _say_and_hang(self, text: str, reason: str, *, interruptible: bool) -> bool:
        if self.closing:
            return True
        await self._wait_until_clear()
        if self.closing:
            return True
        self._in_prompt = True
        try:
            await self._session.say(text, allow_interruptions=interruptible)
        finally:
            self._in_prompt = False
        if reason != "max_duration" and self._session.user_state == "speaking":
            self._silence_at = None
            self._prompted = False
            return False
        self.hang_up(reason)
        return True

    # Wait until a tool is finished and the caller is not talking.
    async def _wait_until_clear(self) -> None:
        while not self.closing and (
            self._tools > 0 or self._session.user_state == "speaking"
        ):
            await asyncio.sleep(0.1)

    # Close the session, and on a real call delete the room.
    def hang_up(self, reason: str) -> None:
        if self.closing:
            return
        self.hangup_reason = reason
        self.closing = True
        duration = time.monotonic() - self._started
        log_call(f"hang-up reason={reason} duration_s={duration:.1f}")

        def _on_close(_ev: object) -> None:
            try:
                job_ctx = get_job_context()
            except RuntimeError:
                return
            if not job_ctx.is_fake_job():

                async def _delete(_shutdown_reason: str) -> None:
                    await job_ctx.delete_room()

                job_ctx.add_shutdown_callback(_delete)
            job_ctx.shutdown(reason=reason)

        self._session.once("close", _on_close)
        self._session.shutdown(drain=True)


# End the call only after the caller has said goodbye and the goodbye has finished.
@function_tool(
    name="end_call",
    description=(
        "End the call only after the caller clearly says goodbye or that they need nothing else. "
        "Say a short goodbye in this same reply, then call this tool. "
        "Never call it while you are waiting for information or while the caller is still speaking."
    ),
)
async def end_call(ctx: RunContext) -> str | None:
    watch: CallLifecycle | None = ctx.session.userdata
    if not isinstance(watch, CallLifecycle):
        return "The call cannot be ended right now."
    if watch.closing or ctx.session.user_state == "speaking":
        return "The caller is still speaking. Do not end the call."
    if not _caller_said_goodbye(ctx.session):
        log_call("end_call blocked: caller has not said goodbye")
        return NOT_GOODBYE_NOTE
    try:
        ctx.speech_handle.allow_interruptions = False
    except RuntimeError:
        return "The caller is still speaking. Do not end the call."

    def _on_done(handle: SpeechHandle) -> None:
        asyncio.create_task(_finish_end_call(ctx, watch, handle))

    ctx.speech_handle.add_done_callback(_on_done)
    return None


# True when the caller's last finished line contains a goodbye phrase.
def _caller_said_goodbye(session: AgentSession) -> bool:
    text = _latest_user_text(session)
    spoken = _normalize_speech(text)
    if not spoken:
        return False
    return any(phrase in spoken for phrase in _GOODBYE_PHRASES)


# The caller's most recent finished sentence, or an empty string.
def _latest_user_text(session: AgentSession) -> str:
    for message in reversed(session.history.messages()):
        if getattr(message, "role", None) != "user":
            continue
        text = (message.text_content or "").strip()
        if text:
            return text
    return ""


# Lowercase the line and turn punctuation into spaces so phrase checks stay simple.
def _normalize_speech(text: str) -> str:
    cleaned = text.lower().replace("\u2019", "'").replace("`", "'")
    letters = []
    for ch in cleaned:
        if ch.isalnum() or ch in {"'", " "}:
            letters.append(ch)
        else:
            letters.append(" ")
    return " ".join("".join(letters).split())


# Hang up after this turn's goodbye, or say one if the model stayed silent.
async def _finish_end_call(
    ctx: RunContext, watch: CallLifecycle, handle: SpeechHandle
) -> None:
    if watch.closing or handle.interrupted or ctx.session.user_state == "speaking":
        return
    if not _assistant_spoke(handle):
        try:
            await ctx.session.say(FALLBACK_GOODBYE, allow_interruptions=False)
        except Exception:
            return
        if ctx.session.user_state == "speaking":
            return
    watch.hang_up("goodbye")


# True when this turn already included a spoken agent line.
def _assistant_spoke(handle: SpeechHandle) -> bool:
    for item in handle.chat_items:
        if getattr(item, "type", None) != "message":
            continue
        if getattr(item, "role", None) != "assistant":
            continue
        text = item.text_content or ""
        if text.strip():
            return True
    return False
