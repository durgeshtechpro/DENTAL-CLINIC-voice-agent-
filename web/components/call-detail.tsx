"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DeskShell } from "@/components/desk-shell";

type CallDetailProps = {
  id: string;
};

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

// Show a missing value as a dash.
function text(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return JSON.stringify(value);
}

// Count items when the field is a list.
function count(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

const COST_PARTS = [
  ["telephony", "Telephony"],
  ["stt", "Speech to text"],
  ["llm", "Model"],
  ["tts", "Voice"],
  ["server", "Server"],
] as const;

// Read one cost part amount, or null when that part was not saved.
function partAmount(cost: Record<string, unknown>, key: string): number | null {
  const part = cost[key];
  if (!part || typeof part !== "object") {
    return null;
  }
  const amount = (part as { amount?: unknown }).amount;
  if (typeof amount !== "number" || Number.isNaN(amount)) {
    return null;
  }
  return amount;
}

// Caller lines sit on the right. Agent lines keep the amber edge.
function callerTurn(role: unknown): boolean {
  const name = typeof role === "string" ? role.toLowerCase() : "";
  return name === "user" || name === "caller";
}

// Read the call id from the page address. Must sit inside Suspense.
export function CallDetailFromRoute() {
  const params = useParams();
  const raw = params.id;
  const id = typeof raw === "string" ? raw : "";
  if (!id) {
    return null;
  }
  return <CallDetail id={id} />;
}

// Load one call and show the transcript, tools, interruptions, and cost.
export function CallDetail({ id }: CallDetailProps) {
  const [call, setCall] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(`/api/calls/${encodeURIComponent(id)}`, { cache: "no-store" });
        const payload: unknown = await response.json().catch(() => null);
        if (!response.ok) {
          if (!cancelled) {
            setError(errorMessage(payload, "Could not load this call."));
          }
          return;
        }
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
          if (!cancelled) {
            setError("This call came back in an unexpected shape.");
          }
          return;
        }
        if (!cancelled) {
          setCall(payload as Record<string, unknown>);
        }
      } catch {
        if (!cancelled) {
          setError("The call service is unreachable.");
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  const transcript = Array.isArray(call?.transcript) ? call.transcript : [];
  const tools = Array.isArray(call?.toolCalls) ? call.toolCalls : [];
  const interruptions = Array.isArray(call?.interruptions) ? call.interruptions : [];
  const cost = call?.cost && typeof call.cost === "object" ? (call.cost as Record<string, unknown>) : null;
  const total = typeof cost?.total === "number" ? cost.total : 0;
  const status = error ? "Unavailable" : call ? text(call.status) : "Loading";

  return (
    <DeskShell title="Call record" lede={id} status={status}>
      <p className="mb-6 text-sm text-stone-600">
        <Link href="/calls" className="underline decoration-stone-400 underline-offset-4">
          Back to the dashboard
        </Link>
      </p>

      {error ? (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {error}
        </p>
      ) : null}

      {!call && !error ? (
        <p className="rounded-2xl border border-[#e4dccf] bg-[#fffdf8] px-4 py-6 text-sm text-stone-500">
          Loading call...
        </p>
      ) : null}

      {call ? (
        <div className="space-y-8">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {[
              ["Status", call.status],
              ["Created", call.createdAt],
              ["Duration", call.durationSeconds],
              ["Hang-up", call.hangupReason],
              ["Turns", count(call.transcript)],
              ["Tools", count(call.toolCalls)],
            ].map(([label, value]) => (
              <div key={String(label)} className="rounded-2xl border border-[#e4dccf] bg-[#fffdf8] px-3 py-3">
                <dt className="text-xs uppercase tracking-wide text-stone-500">{label}</dt>
                <dd className="mt-1 text-sm text-stone-950">{text(value)}</dd>
              </div>
            ))}
          </dl>

          <section className="rounded-3xl border border-[#e4dccf] bg-[#fffdf8] p-5">
            <h2 className="font-serif text-2xl text-stone-950">Cost</h2>
            {cost ? (
              <div className="mt-4 space-y-3">
                {COST_PARTS.map(([key, label]) => {
                  const amount = partAmount(cost, key);
                  if (amount === null) {
                    return null;
                  }
                  const width = total > 0 ? Math.min(100, (amount / total) * 100) : 0;
                  return (
                    <div key={key}>
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span>{label}</span>
                        <span className="font-mono text-stone-600">{amount.toFixed(6)}</span>
                      </div>
                      <div className="mt-1 h-1.5 rounded-full bg-[#efe7db]">
                        <div className="h-1.5 rounded-full bg-amber-800" style={{ width: `${width}%` }} />
                      </div>
                    </div>
                  );
                })}
                <p className="pt-2 text-sm text-stone-800">
                  Total {text(cost.total)} {typeof cost.currency === "string" ? cost.currency : ""}
                  {cost.estimated === true ? " (estimated)" : ""}
                </p>
              </div>
            ) : (
              <p className="mt-3 text-sm text-stone-500">No cost saved for this call.</p>
            )}
          </section>

          <section>
            <h2 className="font-serif text-2xl text-stone-950">Transcript</h2>
            {transcript.length === 0 ? (
              <p className="mt-3 text-sm text-stone-500">No transcript yet.</p>
            ) : (
              <ol className="mt-4 space-y-3">
                {transcript.map((turn, index) => {
                  const row = turn && typeof turn === "object" ? (turn as Record<string, unknown>) : {};
                  const caller = callerTurn(row.role);
                  return (
                    <li key={index} className={caller ? "ml-6 sm:ml-16" : "mr-6 sm:mr-16"}>
                      <div
                        className={
                          caller
                            ? "rounded-2xl bg-white px-3 py-2 text-sm shadow-sm"
                            : "rounded-2xl border-l-2 border-amber-800 bg-[#fffdf8] px-3 py-2 text-sm"
                        }
                      >
                        <p className="text-xs uppercase tracking-wide text-stone-500">
                          {caller ? "Caller" : "Agent"} · {text(row.timestamp)}
                        </p>
                        <p className="mt-1 whitespace-pre-wrap text-stone-950">{text(row.text)}</p>
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <section>
            <h2 className="font-serif text-2xl text-stone-950">Tools</h2>
            {tools.length === 0 ? (
              <p className="mt-3 text-sm text-stone-500">No tools ran.</p>
            ) : (
              <ol className="mt-4 border-l border-stone-300 pl-4">
                {tools.map((tool, index) => {
                  const row = tool && typeof tool === "object" ? (tool as Record<string, unknown>) : {};
                  return (
                    <li key={index} className="relative mb-4 last:mb-0">
                      <span className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-amber-800" />
                      <p className="text-sm text-stone-950">
                        {text(row.name)} · {text(row.outcome)} · {text(row.durationMs)} ms
                      </p>
                      <p className="mt-1 break-all text-sm text-stone-500">{text(row.arguments)}</p>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <section>
            <h2 className="font-serif text-2xl text-stone-950">Interruptions</h2>
            {interruptions.length === 0 ? (
              <p className="mt-3 text-sm text-stone-500">None recorded.</p>
            ) : (
              <ul className="mt-4 space-y-2">
                {interruptions.map((item, index) => {
                  const row = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
                  return (
                    <li key={index} className="rounded-2xl border border-[#e4dccf] bg-[#fffdf8] px-3 py-2 text-sm">
                      {text(row.kind)} · quiet in {text(row.timeToQuietMs)} ms
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <p className="text-sm leading-6 text-stone-500">
            This call does not store an audio file. The session audio is in LiveKit Agent Insights.
          </p>
        </div>
      ) : null}
    </DeskShell>
  );
}
