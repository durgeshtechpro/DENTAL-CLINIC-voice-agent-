// Send one call-API request from the server, so the API key stays off the browser.
export async function forwardCall(path: string, body?: unknown): Promise<Response> {
  const base = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  try {
    const response = await fetch(`${base}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": process.env.API_KEY ?? "",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    const text = await response.text();
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch {
    return Response.json({ error: "The call service is unreachable." }, { status: 502 });
  }
}
