"""One HTTP client shared by every tool call in this process."""

import asyncio
import atexit
import threading
from datetime import datetime

import httpx

_client: httpx.AsyncClient | None = None
_lock = threading.Lock()


# Print one line with the current time.
def _log(event: str) -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} {event}")


# Build the client. Creating it loads SSL, so this must not run on the call's event loop.
def _build_client() -> httpx.AsyncClient:
    # No default timeout here. Each call passes its own timeout.
    return httpx.AsyncClient(timeout=None)


# Open the shared client once. Safe to call again; it reuses the open client.
def open_http_client() -> httpx.AsyncClient:
    global _client
    with _lock:
        if _client is None or _client.is_closed:
            _client = _build_client()
            _log("http client ready")
        return _client


# Return the shared client. If it is missing, build it off the event loop.
async def get_http_client() -> httpx.AsyncClient:
    if _client is not None and not _client.is_closed:
        return _client
    return await asyncio.to_thread(open_http_client)


# Close the shared client. The next request opens a new one.
async def close_http_client() -> None:
    global _client
    with _lock:
        client = _client
        _client = None
    if client is None or client.is_closed:
        return
    await client.aclose()
    _log("http client closed")


# Close the client when the agent process exits.
def _close_on_exit() -> None:
    if _client is None or _client.is_closed:
        return
    try:
        asyncio.run(close_http_client())
    except Exception:
        return


atexit.register(_close_on_exit)
