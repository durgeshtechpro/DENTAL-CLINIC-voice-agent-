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
    <div className="grid gap-8 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <RoomAudioRenderer />
      <div className="flex flex-col gap-5">
        <div className="flex items-end justify-between gap-3">
          <p className="font-serif text-3xl text-stone-950" aria-live="polite">
            {label}
          </p>
          <p className="font-mono text-sm text-stone-600" aria-label="Call duration">
            {formatDuration(seconds)}
          </p>
        </div>
        <div className="desk-meter h-20 rounded-2xl border border-[#e4dccf] bg-[#f7f3ec] px-3">
          <BarVisualizer
            state={state}
            track={audioTrack}
            barCount={9}
            aria-label="Agent audio"
            className="h-20"
          />
        </div>
        {agentMissing ? (
          <p role="alert" className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            Agent did not join, check that the agent worker is running
          </p>
        ) : null}
        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            {...buttonProps}
            type="button"
            aria-label={enabled ? "Mute microphone" : "Unmute microphone"}
            className="h-11 flex-1 rounded-full border border-stone-300 bg-white text-sm font-medium text-stone-900 hover:bg-stone-50 disabled:opacity-50"
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
            className="h-11 flex-1 rounded-full bg-[#7f2d2d] text-sm font-medium text-[#fffdf8] hover:bg-[#6a2424] disabled:opacity-50"
          >
            End call
          </button>
        </div>
        <p className="font-mono text-xs text-stone-500">Call {callId}</p>
      </div>
      <TranscriptPanel />
    </div>
  );
}
