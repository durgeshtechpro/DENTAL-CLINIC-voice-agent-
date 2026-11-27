"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";

type DeskShellProps = {
  title: string;
  lede?: string;
  status?: string;
  children: ReactNode;
};

// Highlight the room the person is in.
function navClass(active: boolean): string {
  if (active) {
    return "rounded-full bg-stone-950 px-4 py-2 text-sm text-stone-50";
  }
  return "rounded-full px-4 py-2 text-sm text-stone-700 hover:bg-white";
}

// Mark Live or Dashboard. This hook has to sit inside Suspense.
function DeskNav() {
  const path = usePathname();
  const onLive = path === "/";
  const onRegister = path.startsWith("/calls");

  return (
    <nav aria-label="Desk" className="flex items-center gap-1">
      <Link href="/" className={navClass(onLive)} aria-current={onLive ? "page" : undefined}>
        Live
      </Link>
            <Link href="/calls" className={navClass(onRegister)} aria-current={onRegister ? "page" : undefined}>
              Dashboard
            </Link>
    </nav>
  );
}

// Frame every desk page with the clinic name, the two rooms, and the call state.
export function DeskShell({ title, lede, status = "Ready", children }: DeskShellProps) {
  return (
    <div className="min-h-full flex-1 bg-[#f4efe6] text-[#1c1915]">
      <header className="sticky top-0 z-10 border-b border-[#e4dccf] bg-[#f7f3ec]/95 backdrop-blur">
        <div className="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-[0.22em] text-amber-900">Bright Smile Dental</p>
            <p className="font-serif text-xl leading-none text-stone-950">Front desk</p>
          </div>
          <Suspense fallback={<nav aria-label="Desk" className="h-9 w-36" />}>
            <DeskNav />
          </Suspense>
          <p className="inline-flex items-center gap-2 text-sm text-stone-700">
            <span className="h-2 w-2 rounded-full bg-amber-700" aria-hidden />
            <span>{status}</span>
          </p>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:py-10">
        <h1 className="font-serif text-4xl tracking-tight text-stone-950 sm:text-5xl">{title}</h1>
        {lede ? <p className="mt-3 max-w-2xl text-sm leading-6 text-stone-600">{lede}</p> : null}
        <div className="mt-8">{children}</div>
      </main>
    </div>
  );
}
