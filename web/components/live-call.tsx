"use client";

import { LiveKitRoom } from "@livekit/components-react";
import { MediaDeviceFailure } from "livekit-client";
import { useCallback, useRef, useState } from "react";
import { CallSession } from "@/components/call-session";
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

  return (
    <main className="flex min-h-full flex-1 items-center justify-center bg-slate-950 px-4 py-10 text-slate-100">
      <section className="w-full max-w-xl rounded-3xl border border-slate-800 bg-slate-900 p-6 shadow-2xl sm:p-8">
        <p className="text-sm text-sky-300">Bright Smile Dental</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white sm:text-3xl">
          Bright Smile Voice Console
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          Start a browser call and talk with the front desk agent.
        </p>

        {error ? (
          <p role="alert" className="mt-5 rounded-xl bg-rose-950 px-3 py-2 text-sm text-rose-100">
            {error}
          </p>
        ) : null}

        {call ? (
          <div className="mt-6">
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
          </div>
        ) : (
          <button
            type="button"
            onClick={() => {
              void startCall();
            }}
            disabled={connecting}
            aria-label="Start call"
            className="mt-6 h-12 w-full rounded-full bg-sky-500 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto sm:px-8"
          >
            {connecting ? "Connecting..." : "Start call"}
          </button>
        )}
      </section>
    </main>
  );
}
