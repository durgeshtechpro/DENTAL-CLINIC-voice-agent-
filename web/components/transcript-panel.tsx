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
    <section aria-label="Live transcript" className="flex min-h-64 flex-col gap-3">
      <h2 className="font-serif text-2xl text-stone-950">Transcript</h2>
      <div
        ref={panelRef}
        className="h-80 overflow-y-auto rounded-2xl border border-[#e4dccf] bg-[#f7f3ec] p-4"
      >
        {lines.length === 0 ? (
          <p className="text-sm text-stone-500">Waiting for someone to speak.</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {lines.map((line) => {
              const caller = line.participantInfo.identity === localParticipant.identity;
              return (
                <li key={line.streamInfo.id} className={caller ? "ml-6 sm:ml-10" : "mr-6 sm:mr-10"}>
                  <div
                    className={
                      caller
                        ? "rounded-2xl bg-white px-3 py-2 text-sm shadow-sm"
                        : "rounded-2xl border-l-2 border-amber-800 bg-[#fffdf8] px-3 py-2 text-sm"
                    }
                  >
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-xs uppercase tracking-wide text-stone-500">
                        {caller ? "Caller" : "Agent"}
                      </span>
                      <time className="text-xs text-stone-400" dateTime={String(line.streamInfo.timestamp)}>
                        {clockTime(line.streamInfo.timestamp)}
                      </time>
                    </div>
                    <p className="mt-1 text-stone-900">{line.text}</p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
