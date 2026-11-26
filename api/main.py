import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from livekit import api
from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.cost import compute_cost
from api.db import (
    delete_call,
    get_call,
    init_db,
    insert_call,
    list_calls,
    mark_ended,
    room_name_for,
    save_result,
)
from api.webhook import (
    close_webhook_client,
    deliver_webhook,
    log_webhook,
    open_webhook_client,
    webhook_url_from,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class ToolHttp(BaseModel):
    method: str = Field(min_length=1)
    url: str = Field(min_length=1)
    timeoutMs: int = Field(ge=0)


class ToolConfig(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    http: ToolHttp


class InactivityConfig(BaseModel):
    afterSeconds: float = Field(gt=0)
    message: str = Field(min_length=1)
    hangUpAfterSeconds: float = Field(gt=0)

    # Require the hang-up to be at or after the check-in prompt.
    @model_validator(mode="after")
    def hang_up_not_before_prompt(self) -> "InactivityConfig":
        if self.hangUpAfterSeconds < self.afterSeconds:
            raise ValueError("hangUpAfterSeconds must be greater than or equal to afterSeconds")
        return self


class UsageResult(BaseModel):
    sttAudioSeconds: float = Field(ge=0)
    llmPromptTokens: int = Field(ge=0)
    llmCompletionTokens: int = Field(ge=0)
    ttsCharacters: int = Field(ge=0)


class TranscriptTurn(BaseModel):
    role: Literal["user", "agent"]
    text: str
    timestamp: str
    offsetSeconds: float = Field(ge=0)


# One tool call. Any outcome string is accepted, and extra keys are kept.
class ToolCallResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: Any = None
    arguments: Any = None
    result: Any = None
    durationMs: Any = None
    timestamp: Any = None
    httpCalled: Any = None
    outcome: str | None = None


class CallResultRequest(BaseModel):
    transcript: list[TranscriptTurn]
    toolCalls: list[ToolCallResult]
    turnMetrics: list[dict[str, Any]]
    usage: UsageResult
    startedAt: str = Field(min_length=1)
    endedAt: str = Field(min_length=1)
    durationSeconds: float = Field(ge=0)
    hangupReason: Literal[
        "goodbye", "inactivity", "max_duration", "caller_disconnected", "api_end"
    ] | None = None
    interruptions: list[dict[str, Any]] = Field(default_factory=list)


class CreateCallRequest(BaseModel):
    systemPrompt: str | None = None
    voice: str | None = None
    language: str | None = None
    firstSpeaker: str | None = None
    greeting: str | None = None
    maxDurationSeconds: float | None = Field(default=None, gt=0)
    inactivity: InactivityConfig | None = None
    tools: list[ToolConfig] | None = None
    knowledgeBase: str | None = None
    direction: Literal["inbound", "outbound"] | None = None
    to: str | None = None
    webhookUrl: str | None = None
    channel: Literal["browser", "phone"] = "browser"

    # A phone call must say whether it is inbound or outbound.
    @model_validator(mode="after")
    def phone_needs_direction(self) -> "CreateCallRequest":
        if self.channel == "phone" and self.direction is None:
            raise ValueError("phone calls need direction inbound or outbound")
        return self


class ApiError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message


# Turn an API error into a JSON body that contains no secrets.
async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


# Reject requests that do not send the shared API key.
async def require_api_key(x_api_key: str = Header(default="")) -> None:
    expected = os.environ.get("API_KEY", "")
    if not expected or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise ApiError(401, "unauthorized")


# Build a JSON error response without including secrets.
def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


# Create the database before the API accepts requests.
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    await asyncio.to_thread(open_webhook_client)
    yield
    await close_webhook_client()


# Browser origins from CORS_ORIGINS, or the local web app when it is empty.
def allowed_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    if not origins:
        return ["http://localhost:3000"]
    return origins


# The listen port from PORT, or 8000 when it is missing or not a valid port.
def listen_port() -> int:
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return 8000
    try:
        port = int(raw)
    except ValueError:
        print(f"PORT={raw} is not a number. Using 8000.")
        return 8000
    if port < 1 or port > 65535:
        print(f"PORT={port} is out of range. Using 8000.")
        return 8000
    return port


app = FastAPI(title="Call API", lifespan=lifespan)
app.add_exception_handler(ApiError, api_error_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Tell the caller the API process is running.
@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


# Make a short id that is not already stored.
def new_call_id() -> str:
    for _ in range(5):
        call_id = secrets.token_hex(4)
        if get_call(call_id) is None:
            return call_id
    raise RuntimeError("could not allocate a call id")


# Build a one-hour token that lets one browser join one room.
def participant_token(room_name: str, identity: str) -> str:
    token = api.AccessToken()
    token.with_identity(identity)
    token.with_ttl(timedelta(hours=1))
    token.with_grants(api.VideoGrants(room_join=True, room=room_name))
    return token.to_jwt()


# Create the LiveKit room and store this call's config in its metadata.
async def create_livekit_room(room_name: str, metadata: str) -> None:
    async with api.LiveKitAPI() as livekit_api:
        await livekit_api.room.create_room(
            api.CreateRoomRequest(name=room_name, metadata=metadata)
        )


# Delete the LiveKit room. A missing room is not an error.
async def delete_livekit_room(room_name: str) -> None:
    try:
        async with api.LiveKitAPI() as livekit_api:
            await livekit_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except api.TwirpError as exc:
        if exc.code == api.TwirpErrorCode.NOT_FOUND:
            return
        raise


# Save a call, and for a browser call also open the LiveKit room.
@app.post("/calls", dependencies=[Depends(require_api_key)])
async def create_call(body: CreateCallRequest) -> JSONResponse:
    if body.channel == "phone" and body.direction == "outbound":
        return _error(501, "outbound phone not configured yet")

    config = body.model_dump()
    call_id = new_call_id()
    room_name = f"call-{call_id}" if body.channel == "browser" else None
    record = insert_call(call_id, config, room_name)

    if body.channel == "phone":
        return JSONResponse(status_code=200, content={"id": record["id"], "status": record["status"]})

    metadata = json.dumps({"id": call_id, "config": config})
    server_url = os.environ.get("LIVEKIT_URL", "")
    room_created = False
    try:
        if not server_url:
            raise RuntimeError("livekit url is not configured")
        await create_livekit_room(room_name or "", metadata)
        room_created = True
        token = participant_token(room_name or "", f"web-{call_id}")
    except Exception:
        if room_created and room_name:
            try:
                await delete_livekit_room(room_name)
            except Exception:
                pass
        delete_call(call_id)
        return _error(502, "could not create the room")

    return JSONResponse(
        status_code=200,
        content={
            "id": call_id,
            "status": "created",
            "roomName": room_name,
            "serverUrl": server_url,
            "participantToken": token,
        },
    )


# Return one saved call.
@app.get("/calls/{call_id}", dependencies=[Depends(require_api_key)])
async def read_call(call_id: str) -> JSONResponse:
    record = get_call(call_id)
    if record is None:
        return _error(404, "not found")
    return JSONResponse(status_code=200, content=record)


# Delete the LiveKit room and mark the call ended.
@app.post("/calls/{call_id}/end", dependencies=[Depends(require_api_key)])
async def end_call(call_id: str) -> JSONResponse:
    record = get_call(call_id)
    if record is None:
        return _error(404, "not found")
    if record["status"] == "ended":
        return JSONResponse(status_code=200, content=record)

    room_name = room_name_for(call_id)
    if room_name:
        try:
            await delete_livekit_room(room_name)
        except Exception:
            return _error(502, "could not delete the room")

    if record["status"] == "completed":
        return JSONResponse(status_code=200, content=record)

    updated = mark_ended(call_id)
    if updated is None:
        return _error(404, "not found")
    return JSONResponse(status_code=200, content=updated)


# Save the transcript and metrics, then send the webhook after the response.
@app.post("/calls/{call_id}/result", dependencies=[Depends(require_api_key)])
async def save_call_result(
    call_id: str, body: CallResultRequest, background: BackgroundTasks
) -> JSONResponse:
    result = body.model_dump()
    try:
        cost = compute_cost(result)
    except Exception:
        cost = compute_cost({})
    updated = save_result(call_id, result, cost)
    if updated is None:
        return _error(404, "not found")
    url = webhook_url_from(updated.get("config"))
    if url:
        background.add_task(deliver_webhook, call_id, url, result, cost)
        log_webhook(f"webhook scheduled call_id={call_id}")
    return JSONResponse(status_code=200, content=updated)


# Return every call, newest first.
@app.get("/calls", dependencies=[Depends(require_api_key)])
async def read_calls() -> list[dict[str, Any]]:
    return list_calls()


# Start the API. The uvicorn command still defaults to port 8000 on its own.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=listen_port())
