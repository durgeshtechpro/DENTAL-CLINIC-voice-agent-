import { Suspense } from "react";
import { CallDetailFromRoute } from "@/components/call-detail";
import { DeskShell } from "@/components/desk-shell";

// One saved call. Suspense is required because the id is only known in the browser.
export default function CallDetailPage() {
  return (
    <Suspense
      fallback={
        <DeskShell title="Call record" status="Loading">
          <p className="text-sm text-stone-500">Loading call...</p>
        </DeskShell>
      }
    >
      <CallDetailFromRoute />
    </Suspense>
  );
}
