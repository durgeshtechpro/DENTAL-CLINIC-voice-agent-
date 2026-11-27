import { forwardCall } from "@/lib/forward-call";

// Return one saved call. The API key stays on the server.
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return forwardCall(`/calls/${encodeURIComponent(id)}`, undefined, "GET");
}
