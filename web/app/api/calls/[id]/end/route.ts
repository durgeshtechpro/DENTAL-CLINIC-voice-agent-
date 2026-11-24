import { forwardCall } from "@/lib/forward-call";

// Ask the call API to end this call.
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return forwardCall(`/calls/${encodeURIComponent(id)}/end`);
}
