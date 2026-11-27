"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DeskShell } from "@/components/desk-shell";

type CallRow = {
  id: string;
  status: string;
  createdAt: string;
  durationSeconds: number | null;
  hangupReason?: string | null;
};

// Keep a list item only when it has the fields the table needs.
function callRow(value: unknown): CallRow | null {
  if (!value || typeof value !== "object") {
    return null;
  }
  const row = value as Record<string, unknown>;
  if (typeof row.id !== "string" || typeof row.status !== "string") {
    return null;
  }
  const duration = row.durationSeconds;
  return {
    id: row.id,
    status: row.status,
    createdAt: typeof row.createdAt === "string" ? row.createdAt : "",
    durationSeconds: typeof duration === "number" ? duration : null,
  };
}

// Show one short duration, or a dash when the call has not ended.
function durationLabel(seconds: number | null): string {
  if (seconds === null) {
    return "—";
  }
  return `${Math.round(seconds)}s`;
}

// Load the call list and link each row to its detail page.
export function CallHistory() {
  const [rows, setRows] = useState<CallRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch("/api/calls", { cache: "no-store" });
        const payload: unknown = await response.json().catch(() => null);
        if (!response.ok) {
          if (!cancelled) {
            setError("Could not load the call list.");
          }
          return;
        }
        if (!Array.isArray(payload)) {
          if (!cancelled) {
            setError("The call list was not a list.");
          }
          return;
        }
        if (!cancelled) {
          setRows(payload.map(callRow).filter((row): row is CallRow => row !== null));
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
  }, []);

  return (
    <DeskShell
      title="Call register"
      lede="Every saved browser call. Open one for the transcript, the tools, and the cost."
      status={error ? "Unavailable" : rows === null ? "Loading" : `${rows.length} saved`}
    >
      {error ? (
        <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">
          {error}
        </p>
      ) : null}

      {rows === null && !error ? (
        <p className="rounded-2xl border border-[#e4dccf] bg-[#fffdf8] px-4 py-6 text-sm text-stone-500">
          Loading calls...
        </p>
      ) : null}

      {rows && rows.length === 0 ? (
        <div className="rounded-3xl border border-dashed border-stone-300 bg-[#fffdf8] px-6 py-10">
          <p className="font-serif text-2xl text-stone-950">No calls yet.</p>
          <p className="mt-2 text-sm text-stone-600">Start one from the live desk. It will appear here after it is saved.</p>
          <Link
            href="/"
            className="mt-5 inline-flex h-11 items-center rounded-full bg-stone-950 px-5 text-sm text-stone-50"
          >
            Go to the live desk
          </Link>
        </div>
      ) : null}

      {rows && rows.length > 0 ? (
        <ul className="overflow-hidden rounded-3xl border border-[#e4dccf] bg-[#fffdf8]">
          {rows.map((row) => (
            <li key={row.id} className="border-b border-[#efe7db] last:border-b-0">
              <Link
                href={`/calls/${encodeURIComponent(row.id)}`}
                className="flex flex-col gap-2 px-4 py-4 hover:bg-[#f7f3ec] sm:flex-row sm:items-center sm:justify-between"
              >
                <span className="font-mono text-sm text-stone-950">{row.id}</span>
                <span className="text-sm text-stone-600">
                  <span className="mr-2 inline-flex rounded-full border border-stone-300 px-2 py-0.5 text-xs uppercase tracking-wide text-stone-700">
                    {row.status}
                  </span>
                  {durationLabel(row.durationSeconds)} · {row.createdAt || "—"}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </DeskShell>
  );
}
