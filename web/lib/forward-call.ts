// Send one call-API request from the server, so the API key stays off the browser.
export async function forwardCall(
  path: string,
  body?: unknown,
  method: "GET" | "POST" = "POST",
): Promise<Response> {
  const base = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
  const headers: Record<string, string> = {
    "X-API-Key": process.env.API_KEY ?? "",
  };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
  }
  try {
    const response = await fetch(`${base}${path}`, {
      method,
      headers,
      body: method === "GET" || body === undefined ? undefined : JSON.stringify(body),
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
