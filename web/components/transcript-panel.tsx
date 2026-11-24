"use client";

import { useTranscriptions, useLocalParticipant } from "@livekit/components-react";
import { useEffect, useRef } from "react";

// Show a clock time for a transcription timestamp.
function clockTime(timestamp: number): string {
  const milliseconds = timestamp < 1_000_000_000_000 ? timestamp * 1000 : timestamp;
  return new Date(milliseconds).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

// Show caller and agent lines, and keep the newest line in view.
export function TranscriptPanel() {
  const streams = useTranscriptions();
  const { localParticipant } = useLocalParticipant();
  const panelRef = useRef<HTMLDivElement>(null);
  const lines = streams
    .filter((stream) => stream.text.trim().length > 0)
    .slice()
    .sort((left, right) => left.streamInfo.timestamp - right.streamInfo.timestamp);
  const scrollKey = lines.map((line) => `${line.streamInfo.id}:${line.text}`).join("\n");

  useEffect(() => {
    const panel = panelRef.current;
    if (panel) {
      panel.scrollTop = panel.scrollHeight;
    }
  }, [scrollKey]);

  return (
    <section aria-label="Live transcript" className="flex min-h-48 flex-col gap-2">
      <h2 className="text-sm font-medium text-slate-300">Transcript</h2>
      <div
        ref={panelRef}
        className="h-56 overflow-y-auto rounded-xl border border-slate-700 bg-slate-950 p-3"
      >
        {lines.length === 0 ? (
          <p className="text-sm text-slate-500">Waiting for someone to speak.</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {lines.map((line) => {
              const caller = line.participantInfo.identity === localParticipant.identity;
              return (
                <li key={line.streamInfo.id} className="text-sm">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className={caller ? "text-sky-300" : "text-emerald-300"}>
                      {caller ? "Caller" : "Agent"}
                    </span>
                    <time className="text-xs text-slate-500" dateTime={String(line.streamInfo.timestamp)}>
                      {clockTime(line.streamInfo.timestamp)}
                    </time>
                  </div>
                  <p className="mt-1 text-slate-100">{line.text}</p>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
