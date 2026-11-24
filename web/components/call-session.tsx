"use client";

import {
  BarVisualizer,
  RoomAudioRenderer,
  useConnectionState,
  useRoomContext,
  useTrackToggle,
  useVoiceAssistant,
  type AgentState,
} from "@livekit/components-react";
import { ConnectionState, Track } from "livekit-client";
import { useEffect, useState } from "react";
import { TranscriptPanel } from "@/components/transcript-panel";

// Turn the agent state into one of the four labels shown on the card.
function statusLabel(state: AgentState, connection: ConnectionState): string {
  if (connection !== ConnectionState.Connected) {
    return "Connecting";
  }
  if (state === "listening") return "Listening";
  if (state === "thinking") return "Thinking";
  if (state === "speaking") return "Speaking";
  return "Connecting";
}

// Show minutes and seconds since the room connected.
function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

type CallSessionProps = {
  callId: string;
  onLeave: (message: string | null) => void;
};

// Draw the connected call: status, visualizer, controls, timer, and transcript.
export function CallSession({ callId, onLeave }: CallSessionProps) {
  const room = useRoomContext();
  const connection = useConnectionState();
  const { state, audioTrack, agent } = useVoiceAssistant();
  const { enabled, buttonProps } = useTrackToggle({ source: Track.Source.Microphone });
  const [seconds, setSeconds] = useState(0);
  const [agentLate, setAgentLate] = useState(false);
  const [seenAgent, setSeenAgent] = useState(false);
  const [ending, setEnding] = useState(false);

  useEffect(() => {
    if (connection !== ConnectionState.Connected) {
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setSeconds(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [connection]);

  useEffect(() => {
    if (agent) {
      const markSeen = window.setTimeout(() => setSeenAgent(true), 0);
      return () => window.clearTimeout(markSeen);
    }
    if (seenAgent) {
      return;
    }
    const timer = window.setTimeout(() => setAgentLate(true), 15000);
    return () => window.clearTimeout(timer);
  }, [agent, seenAgent]);

  // Tell the API the call is over, then leave the room.
  async function endCall() {
    setEnding(true);
    let message: string | null = null;
    try {
      const response = await fetch(`/api/calls/${encodeURIComponent(callId)}/end`, {
        method: "POST",
      });
      if (!response.ok) {
        message =
          response.status === 502
            ? "The call service is unreachable."
            : "The call could not be ended on the server.";
      }
    } catch {
      message = "The call service is unreachable.";
    }
    onLeave(message);
    await room.disconnect();
  }

  const label = statusLabel(state, connection);
  const agentMissing = agentLate && !seenAgent && !agent;

  return (
    <div className="flex flex-col gap-5">
      <RoomAudioRenderer />
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-slate-300" aria-live="polite">
          Status: <span className="font-medium text-white">{label}</span>
        </p>
        <p className="font-mono text-sm text-slate-300" aria-label="Call duration">
          {formatDuration(seconds)}
        </p>
      </div>
      <div data-lk-theme="default" className="h-16 rounded-xl bg-slate-950 px-3">
        <BarVisualizer
          state={state}
          track={audioTrack}
          barCount={7}
          aria-label="Agent audio"
          className="h-16"
        />
      </div>
      {agentMissing ? (
        <p role="alert" className="rounded-lg bg-amber-950 px-3 py-2 text-sm text-amber-100">
          Agent did not join, check that the agent worker is running
        </p>
      ) : null}
      <div className="flex flex-col gap-3 sm:flex-row">
        <button
          {...buttonProps}
          type="button"
          aria-label={enabled ? "Mute microphone" : "Unmute microphone"}
          className="h-11 flex-1 rounded-full border border-slate-600 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {enabled ? "Mute" : "Unmute"}
        </button>
        <button
          type="button"
          onClick={() => {
            void endCall();
          }}
          disabled={ending}
          aria-label="End call"
          className="h-11 flex-1 rounded-full bg-rose-600 text-sm font-medium text-white hover:bg-rose-500 disabled:opacity-50"
        >
          End call
        </button>
      </div>
      <TranscriptPanel />
    </div>
  );
}
