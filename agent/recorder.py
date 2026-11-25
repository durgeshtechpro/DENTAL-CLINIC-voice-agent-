import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from livekit import rtc

from http_client import get_http_client
from livekit.agents import AgentSession, ChatMessage
from livekit.agents.metrics import EOUMetrics, LLMMetrics, STTMetrics, TTSMetrics
from livekit.agents.inference.interruption import OverlappingSpeechEvent
from livekit.agents.voice.events import (
    AgentFalseInterruptionEvent,
    AgentStateChangedEvent,
    CloseEvent,
    CloseReason,
    ConversationItemAddedEvent,
    MetricsCollectedEvent,
    UserStateChangedEvent,
)

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "call-logs"
HANGUP_REASONS = {"goodbye", "inactivity", "max_duration"}


# The call API address, or the local API when the variable is empty.
def api_base_url() -> str:
    base = os.environ.get("API_BASE_URL", "").strip().rstrip("/")
    return base or "http://127.0.0.1:8000"


# Turn a SDK unix time into a UTC timestamp, or None when the SDK did not give one.
def unix_stamp(unix: object) -> str | None:
    if isinstance(unix, bool) or not isinstance(unix, (int, float)):
        return None
    return datetime.fromtimestamp(float(unix), timezone.utc).isoformat(timespec="milliseconds")


# Turn a seconds value from the SDK into whole milliseconds, or None when it is missing.
def milliseconds(seconds: object) -> int | None:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds < 0:
        return None
    return int(round(float(seconds) * 1000))


# Use a metric from this chat message when the SDK stored it, otherwise the fallback.
def metric_or(metrics: dict[str, Any], key: str, fallback: float | None) -> float | None:
    if key not in metrics:
        return fallback
    return None if milliseconds(metrics[key]) is None else float(metrics[key])


# Make one value safe to store as JSON.
def json_ready(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


# Print a save failure without including the API key.
def log_save_error(exc: Exception) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} call result save failed: {type(exc).__name__}: {exc}")


# Collect the transcript, tool calls, and SDK metrics for one call.
class CallRecorder:
    def __init__(self, call_id: str | None) -> None:
        self.call_id = call_id
        self._started_wall = time.time()
        self._started_mono = time.monotonic()
        self._started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._ended_at: str | None = None
        self._duration_seconds: float | None = None
        self._hangup_reason: str | None = None
        self._transcript: list[dict[str, Any]] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._turn_metrics: list[dict[str, Any]] = []
        self._interruptions: list[dict[str, Any]] = []
        self._open_interruption: dict[str, Any] | None = None
        self._stt_audio_seconds = 0.0
        self._llm_prompt_tokens = 0
        self._llm_completion_tokens = 0
        self._tts_characters = 0
        self._pending_eou: float | None = None
        self._pending_ttft: float | None = None
        self._pending_ttfb: float | None = None
        self._user_end_of_turn: float | None = None
        self._used_tool = False
        self._room_deleted = False
        self._session: AgentSession | None = None
        self._finished = False
        self._saved = False
        self._save_task: asyncio.Task[None] | None = None

    # Listen for transcript lines, SDK metrics, and the session closing.
    def attach(self, session: AgentSession) -> None:
        self._session = session
        session.on("conversation_item_added", self._on_conversation_item)
        session.on("metrics_collected", self._on_metrics)
        session.on("user_state_changed", self._on_user_state)
        session.on("agent_state_changed", self._on_agent_state)
        session.on("overlapping_speech", self._on_overlap)
        session.on("agent_false_interruption", self._on_false_interruption)
        session.on("close", self._on_close)

    # Remember when the LiveKit room itself is deleted, which means the API ended the call.
    def watch_room(self, room: rtc.Room) -> None:
        try:
            room.on("participant_disconnected", self._on_participant_left)
        except Exception:
            return

    # Note a room deletion. A caller hanging up uses a different disconnect reason.
    def _on_participant_left(self, participant: rtc.RemoteParticipant) -> None:
        if participant.disconnect_reason == rtc.DisconnectReason.ROOM_DELETED:
            self._room_deleted = True

    # Store one spoken line and, for an agent line, the latency of that reply.
    def _on_conversation_item(self, ev: ConversationItemAddedEvent) -> None:
        item = ev.item
        if not isinstance(item, ChatMessage):
            return
        text = (item.text_content or "").strip()
        if not text:
            return
        if item.role == "user":
            self._transcript.append(self._turn("user", text, item.created_at))
            self._mark_real_interruption()
            if "end_of_turn_delay" in item.metrics:
                delay = item.metrics["end_of_turn_delay"]
                if milliseconds(delay) is not None:
                    self._user_end_of_turn = float(delay)
            return
        if item.role == "assistant":
            self._transcript.append(self._turn("agent", text, item.created_at))
            self._add_turn_metric(item.metrics)

    # The caller started speaking. Remember it only when the agent is also speaking.
    def _on_user_state(self, ev: UserStateChangedEvent) -> None:
        if ev.new_state != "speaking":
            if (
                ev.new_state == "listening"
                and self._open_interruption is not None
                and self._open_interruption["agentStoppedAt"] is None
            ):
                self._open_interruption = None
            return
        if self._session is None or self._session.agent_state != "speaking":
            return
        if self._open_interruption is not None:
            return
        self._begin_interruption(ev.created_at)

    # The adaptive detector says this overlap is a real interruption.
    def _on_overlap(self, ev: OverlappingSpeechEvent) -> None:
        if ev.is_interruption is not True:
            return
        if self._session is None or self._session.agent_state != "speaking":
            return
        if self._open_interruption is not None:
            return
        self._begin_interruption(ev.overlap_started_at)

    # Start one interruption from a SDK timestamp. None stays null.
    def _begin_interruption(self, started_at: object) -> None:
        started = unix_stamp(started_at)
        self._open_interruption = {
            "callerStartedAt": started,
            "agentStoppedAt": None,
            "timeToQuietMs": None,
            "kind": None,
            "_caller_unix": None if started is None else float(started_at),
            "_stopped_unix": None,
        }

    # The agent left speaking. That event time is when the SDK stopped the audio.
    def _on_agent_state(self, ev: AgentStateChangedEvent) -> None:
        open_row = self._open_interruption
        if open_row is None:
            return
        if ev.old_state != "speaking" or ev.new_state == "speaking":
            return
        if open_row["_stopped_unix"] is not None:
            return
        stopped = unix_stamp(ev.created_at)
        open_row["agentStoppedAt"] = stopped
        if stopped is None:
            return
        open_row["_stopped_unix"] = float(ev.created_at)
        if open_row["_caller_unix"] is None:
            return
        open_row["timeToQuietMs"] = milliseconds(
            float(ev.created_at) - open_row["_caller_unix"]
        )

    # The SDK says the pause was a false interruption. resumed=True means the agent continued.
    def _on_false_interruption(self, ev: AgentFalseInterruptionEvent) -> None:
        open_row = self._open_interruption
        if open_row is None:
            return
        if ev.resumed is True:
            open_row["kind"] = "false_resumed"
        self._finish_interruption()

    # A saved caller line means the agent stayed quiet and the interruption was real.
    def _mark_real_interruption(self) -> None:
        open_row = self._open_interruption
        if open_row is None or open_row["agentStoppedAt"] is None or open_row["kind"] is not None:
            return
        open_row["kind"] = "real"
        self._finish_interruption()

    # Store the open interruption and print it. Drop private timing fields first.
    def _finish_interruption(self) -> None:
        open_row = self._open_interruption
        self._open_interruption = None
        if open_row is None:
            return
        row = {
            "callerStartedAt": open_row["callerStartedAt"],
            "agentStoppedAt": open_row["agentStoppedAt"],
            "timeToQuietMs": open_row["timeToQuietMs"],
            "kind": open_row["kind"],
        }
        self._interruptions.append(row)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(
            f"{stamp} interruption kind={row['kind']} "
            f"callerStartedAt={row['callerStartedAt']} "
            f"agentStoppedAt={row['agentStoppedAt']} "
            f"timeToQuietMs={row['timeToQuietMs']}"
        )

    # Close an interruption that was still open when the call ended.
    def _flush_open_interruption(self) -> None:
        open_row = self._open_interruption
        if open_row is None:
            return
        if open_row["agentStoppedAt"] is None and open_row["kind"] is None:
            self._open_interruption = None
            return
        if open_row["kind"] is None and open_row["agentStoppedAt"] is not None:
            open_row["kind"] = "real"
        self._finish_interruption()

    # Build one transcript row with the time and how far into the call it happened.
    def _turn(self, role: str, text: str, created_at: float) -> dict[str, Any]:
        offset = max(0.0, round(created_at - self._started_wall, 3))
        stamp = datetime.fromtimestamp(created_at, timezone.utc).isoformat(timespec="seconds")
        return {"role": role, "text": text, "timestamp": stamp, "offsetSeconds": offset}

    # Keep one latency row for this agent reply, using only numbers the SDK reported.
    def _add_turn_metric(self, metrics: dict[str, Any]) -> None:
        end_delay = self._pending_eou if self._pending_eou is not None else self._user_end_of_turn
        llm_ttft = metric_or(metrics, "llm_node_ttft", self._pending_ttft)
        tts_ttfb = metric_or(metrics, "tts_node_ttfb", self._pending_ttfb)
        total = metric_or(metrics, "e2e_latency", None)
        self._turn_metrics.append(
            {
                "turnIndex": len(self._turn_metrics),
                "endOfTurnDelayMs": milliseconds(end_delay),
                "llmTtftMs": milliseconds(llm_ttft),
                "ttsTtfbMs": milliseconds(tts_ttfb),
                "totalMs": milliseconds(total),
                "usedTool": self._used_tool,
            }
        )
        self._pending_eou = None
        self._pending_ttft = None
        self._pending_ttfb = None
        self._user_end_of_turn = None
        self._used_tool = False

    # Add usage totals and the latency numbers from one SDK metrics event.
    def _on_metrics(self, ev: MetricsCollectedEvent) -> None:
        metric = ev.metrics
        if isinstance(metric, EOUMetrics):
            if milliseconds(metric.end_of_utterance_delay) is not None:
                self._pending_eou = metric.end_of_utterance_delay
            return
        if isinstance(metric, LLMMetrics):
            self._llm_prompt_tokens += metric.prompt_tokens
            self._llm_completion_tokens += metric.completion_tokens
            if milliseconds(metric.ttft) is not None:
                self._pending_ttft = metric.ttft
            return
        if isinstance(metric, TTSMetrics):
            self._tts_characters += metric.characters_count
            if milliseconds(metric.ttfb) is not None:
                self._pending_ttfb = metric.ttfb
            return
        if isinstance(metric, STTMetrics):
            if milliseconds(metric.audio_duration) is not None:
                self._stt_audio_seconds += metric.audio_duration

    # Record one HTTP tool call reported by the tool itself.
    def add_tool_call(
        self,
        name: str,
        arguments: Any,
        result: Any,
        duration_ms: int,
    ) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._tool_calls.append(
            {
                "name": name,
                "arguments": json_ready(arguments),
                "result": json_ready(result),
                "durationMs": duration_ms,
                "timestamp": stamp,
            }
        )
        self._used_tool = True

    # The caller's last few finished lines, oldest first.
    def recent_caller_lines(self, limit: int = 6) -> list[str]:
        lines = [
            str(row.get("text") or "").strip()
            for row in self._transcript
            if row.get("role") == "user" and str(row.get("text") or "").strip()
        ]
        return lines[-limit:]

    # Stop the clock and choose why the call ended.
    def finish(self, ev: CloseEvent | None) -> None:
        if self._finished:
            return
        self._flush_open_interruption()
        self._finished = True
        self._ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._duration_seconds = round(time.monotonic() - self._started_mono, 3)
        self._hangup_reason = self._hangup_from(ev)

    # Prefer the agent's own goodbye reason, then a deleted room, then the caller leaving.
    def _hangup_from(self, ev: CloseEvent | None) -> str | None:
        watch = None
        if self._session is not None:
            try:
                watch = self._session.userdata
            except Exception:
                watch = None
        reason = getattr(watch, "hangup_reason", None)
        if reason in HANGUP_REASONS:
            return str(reason)
        if self._room_deleted:
            return "api_end"
        if ev is not None and ev.reason in {
            CloseReason.PARTICIPANT_DISCONNECTED,
            CloseReason.JOB_SHUTDOWN,
        }:
            return "caller_disconnected"
        return None

    # Build the JSON object saved for this call.
    def to_result(self) -> dict[str, Any]:
        if not self._finished:
            self.finish(None)
        return {
            "transcript": self._transcript,
            "toolCalls": self._tool_calls,
            "turnMetrics": self._turn_metrics,
            "usage": {
                "sttAudioSeconds": round(self._stt_audio_seconds, 3),
                "llmPromptTokens": self._llm_prompt_tokens,
                "llmCompletionTokens": self._llm_completion_tokens,
                "ttsCharacters": self._tts_characters,
            },
            "startedAt": self._started_at,
            "endedAt": self._ended_at,
            "durationSeconds": self._duration_seconds,
            "hangupReason": self._hangup_reason,
            "interruptions": self._interruptions,
        }

    # Start saving when the session closes. The job shutdown waits for this task.
    def _on_close(self, ev: CloseEvent) -> None:
        self.finish(ev)
        if self._save_task is None:
            self._save_task = asyncio.create_task(self.save())

    # Wait until the session has closed and the result has been posted or written.
    async def wait_saved(self) -> None:
        for _ in range(300):
            if self._save_task is not None:
                await self._save_task
                return
            await asyncio.sleep(0.1)
        if self._save_task is None:
            self._save_task = asyncio.create_task(self.save())
        await self._save_task

    # Post the result when this call has an id, otherwise write a console log file.
    async def save(self) -> None:
        if self._saved:
            return
        self._saved = True
        try:
            payload = self.to_result()
            if self.call_id:
                try:
                    await self._post(payload)
                except Exception as exc:
                    log_save_error(exc)
                    self._write(payload, f"{self.call_id}.json")
                return
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            self._write(payload, f"console-{stamp}.json")
        except Exception as exc:
            log_save_error(exc)

    # Send the result to the call API. Raises when the API does not accept it.
    async def _post(self, payload: dict[str, Any]) -> None:
        url = f"{api_base_url()}/calls/{self.call_id}/result"
        headers = {"X-API-Key": os.environ.get("API_KEY", "")}
        client = await get_http_client()
        response = await client.post(
            url, headers=headers, json=payload, timeout=httpx.Timeout(5.0)
        )
        response.raise_for_status()

    # Write the result JSON into data/call-logs.
    def _write(self, payload: dict[str, Any], name: str) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / name
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime("%H%M%S%f")
            path = LOG_DIR / f"{path.stem}-{stamp}{path.suffix}"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# The caller's recent finished lines from the recorder on this session.
def recent_caller_lines(session: AgentSession, limit: int = 6) -> list[str]:
    try:
        watch = session.userdata
    except Exception:
        return []
    recorder = getattr(watch, "recorder", None)
    if not isinstance(recorder, CallRecorder):
        return []
    try:
        return recorder.recent_caller_lines(limit)
    except Exception:
        return []


# Hand one finished tool call to the recorder attached to this session.
def report_tool_call(
    session: AgentSession,
    name: str,
    arguments: Any,
    result: Any,
    duration_ms: int,
) -> None:
    try:
        watch = session.userdata
    except Exception:
        return
    recorder = getattr(watch, "recorder", None)
    if not isinstance(recorder, CallRecorder):
        return
    try:
        recorder.add_tool_call(name, arguments, result, duration_ms)
    except Exception:
        return
