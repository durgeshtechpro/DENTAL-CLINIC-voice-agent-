"use client";

import { LiveKitRoom } from "@livekit/components-react";
import { MediaDeviceFailure } from "livekit-client";
import { useCallback, useRef, useState } from "react";
import { CallSession } from "@/components/call-session";
import { DeskShell } from "@/components/desk-shell";
import "@livekit/components-styles";

type StartedCall = {
  id: string;
  serverUrl: string;
  participantToken: string;
};

// Read the room details only when the API returned a usable browser call.
function startedCall(value: unknown): StartedCall | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.id !== "string" ||
    typeof record.serverUrl !== "string" ||
    typeof record.participantToken !== "string"
  ) {
    return null;
  }
  return {
    id: record.id,
    serverUrl: record.serverUrl,
    participantToken: record.participantToken,
  };
}

// Read a short error string from a JSON body.
function errorMessage(value: unknown, fallback: string): string {
  if (value && typeof value === "object" && "error" in value) {
    const message = (value as { error?: unknown }).error;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return fallback;
}

// Start a browser call, then show the live room inside the card.
export function LiveCall() {
  const [call, setCall] = useState<StartedCall | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const leaving = useRef(false);

  // Ask our server proxy for a room, then connect with the returned token.
  async function startCall() {
    setConnecting(true);
    setError(null);
    leaving.current = false;
    try {
      const response = await fetch("/api/calls", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      if (!response.ok) {
        setError(
          errorMessage(
            payload,
            response.status === 502
              ? "The call service is unreachable."
              : "Could not start the call.",
          ),
        );
        return;
      }
      const started = startedCall(payload);
      if (!started) {
        setError("The call service returned an unexpected response.");
        return;
      }
      setCall(started);
    } catch {
      setError("The call service is unreachable.");
    } finally {
      setConnecting(false);
    }
  }

  // Leave the card after the room closes. Show a message only for a surprise disconnect.
  const handleDisconnected = useCallback(() => {
    const surprise = !leaving.current;
    leaving.current = false;
    setCall(null);
    if (surprise) {
      setError("The call disconnected unexpectedly.");
    }
  }, []);

  // Explain a microphone failure in plain language.
  const handleMediaFailure = useCallback((failure?: MediaDeviceFailure) => {
    if (failure === MediaDeviceFailure.PermissionDenied) {
      setError("Microphone permission was denied. Allow the microphone and try again.");
      return;
    }
    if (failure) {
      setError("The microphone could not be opened.");
    }
  }, []);

  // Show a connection problem without treating a denied microphone as a dropped call.
  const handleRoomError = useCallback((error: Error) => {
    const failure = MediaDeviceFailure.getFailure(error);
    if (failure === MediaDeviceFailure.PermissionDenied) {
      setError("Microphone permission was denied. Allow the microphone and try again.");
      return;
    }
    if (failure) {
      setError("The microphone could not be opened.");
      return;
    }
    leaving.current = true;
    setCall(null);
    setError("Could not connect to the call.");
  }, []);

  const status = call ? "On a call" : connecting ? "Connecting" : "Ready";

  return (
    <DeskShell
      title="Live desk"
      lede="Talk with the front desk from this browser. The phone trial is not required for this console."
      status={status}
    >
      <section className="rounded-3xl border border-[#e4dccf] bg-[#fffdf8] p-6 shadow-sm sm:p-8">
        {error ? (
          <p role="alert" className="mb-5 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
            {error}
          </p>
        ) : null}

        {call ? (
          <LiveKitRoom
            serverUrl={call.serverUrl}
            token={call.participantToken}
            connect
            audio
            video={false}
            onDisconnected={handleDisconnected}
            onMediaDeviceFailure={handleMediaFailure}
            onError={handleRoomError}
            className="flex flex-col"
          >
            <CallSession
              callId={call.id}
              onLeave={(message) => {
                leaving.current = true;
                if (message) {
                  setError(message);
                }
              }}
            />
          </LiveKitRoom>
        ) : (
          <div className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
            <p className="max-w-md text-sm leading-6 text-stone-600">
              The agent greets first, checks the clinic book, and can hang up when the conversation is done.
            </p>
            <button
              type="button"
              onClick={() => {
                void startCall();
              }}
              disabled={connecting}
              aria-label="Start call"
              className="h-12 rounded-full bg-amber-800 px-8 text-sm font-semibold text-[#fffdf8] hover:bg-amber-900 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {connecting ? "Connecting..." : "Start call"}
            </button>
          </div>
        )}
      </section>
    </DeskShell>
  );
}
