import { forwardCall } from "@/lib/forward-call";

// Return the saved call list. The API key stays on the server.
export async function GET() {
  return forwardCall("/calls", undefined, "GET");
}

// Start a browser call and return the room details from the call API.
export async function POST(request: Request) {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = await request.json();
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      body = parsed as Record<string, unknown>;
    }
  } catch {
    body = {};
  }
  body.channel = "browser";
  return forwardCall("/calls", body);
}
