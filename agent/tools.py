import json
import random
import time
from datetime import datetime
from typing import Any

import httpx
from livekit.agents import RunContext, function_tool
from livekit.agents.llm import RawFunctionTool

FILLER_PHRASES = (
    "Let me check that for you.",
    "One moment while I look that up.",
    "I'll check the schedule now.",
)
TAKEN_NOTE = "Tell the caller this slot is taken and offer these alternatives."
TIMEOUT_NOTE = "The system is slow. Apologise briefly and offer to try again."
UNAVAILABLE_NOTE = (
    "The system is not responding. Apologise and offer to try again "
    "or have the clinic call back."
)


# Turn one config dict into a LiveKit tool that POSTs the model's arguments.
def build_http_tool(config: dict[str, Any]) -> RawFunctionTool:
    schema = {
        "name": config["name"],
        "description": config["description"],
        "parameters": config["parameters"],
    }

    # Say a short filler, call the URL, and hand the model plain JSON text.
    async def call_tool(ctx: RunContext, raw_arguments: dict[str, Any]) -> str:
        started = time.perf_counter()
        try:
            await ctx.session.say(random.choice(FILLER_PHRASES))
            started = time.perf_counter()
            timeout_seconds = config["http"]["timeoutMs"] / 1000
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
                response = await client.request(
                    config["http"]["method"],
                    config["http"]["url"],
                    json=raw_arguments,
                )
            if response.status_code == 200:
                payload: Any = response.json()
            elif response.status_code == 409:
                payload = response.json()
                if isinstance(payload, dict):
                    payload["note"] = TAKEN_NOTE
                else:
                    payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
            else:
                payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}
        except httpx.TimeoutException:
            payload = {"error": "timeout", "note": TIMEOUT_NOTE}
        except Exception:
            payload = {"error": "unavailable", "note": UNAVAILABLE_NOTE}

        text = json.dumps(payload)
        duration_ms = int((time.perf_counter() - started) * 1000)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(
            f"{stamp} tool={config['name']} args={json.dumps(raw_arguments)} "
            f"result={text} duration_ms={duration_ms}"
        )
        return text

    return function_tool(call_tool, raw_schema=schema)
