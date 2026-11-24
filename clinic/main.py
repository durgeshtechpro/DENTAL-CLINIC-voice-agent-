import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from clinic.db import book_slot, free_slots, init_db

WEBHOOK_LOG = Path(__file__).resolve().parent / "webhooks.log"
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")


# Create the database before the server accepts requests, then close nothing extra.
@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Clinic", lifespan=lifespan)


# Pause the response when a test asks for an artificial delay.
async def wait_if_requested(delay_ms: int) -> None:
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000)


class SlotsRequest(BaseModel):
    date: str

    # Reject anything that is not a real calendar date written as YYYY-MM-DD.
    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if DATE_PATTERN.fullmatch(value) is None:
            raise ValueError("date must be YYYY-MM-DD")
        datetime.strptime(value, "%Y-%m-%d")
        return value


class BookRequest(BaseModel):
    date: str
    time: str
    name: str
    phone: str

    # Reject anything that is not a real calendar date written as YYYY-MM-DD.
    @field_validator("date")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if DATE_PATTERN.fullmatch(value) is None:
            raise ValueError("date must be YYYY-MM-DD")
        datetime.strptime(value, "%Y-%m-%d")
        return value

    # Reject anything that is not a real clock time written as HH:MM.
    @field_validator("time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        if TIME_PATTERN.fullmatch(value) is None:
            raise ValueError("time must be HH:MM")
        datetime.strptime(value, "%H:%M")
        return value

    # Reject a blank patient name or phone number.
    @field_validator("name", "phone")
    @classmethod
    def not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be blank")
        return cleaned


# List the free appointment times for one date.
@app.post("/slots")
async def list_slots(
    body: SlotsRequest,
    delay_ms: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await wait_if_requested(delay_ms)
    return {"date": body.date, "slots": free_slots(body.date)}


# Book one slot, or say it is taken or missing.
@app.post("/book")
async def book(
    body: BookRequest,
    delay_ms: int = Query(default=0, ge=0),
) -> JSONResponse:
    await wait_if_requested(delay_ms)
    result = book_slot(body.date, body.time, body.name, body.phone)
    status = result["status"]
    if status == "booked":
        return JSONResponse(
            status_code=200,
            content={"status": "booked", "date": body.date, "time": body.time},
        )
    if status == "not_found":
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return JSONResponse(
        status_code=409,
        content={
            "status": "already_booked",
            "alternatives": result["alternatives"],
        },
    )


# Save a call-ended webhook to the log and confirm it arrived.
@app.post("/call-ended")
async def call_ended(request: Request) -> dict[str, bool]:
    payload = await request.json()
    line = json.dumps(payload, ensure_ascii=False)
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    print(f"{stamp} {line}")
    with WEBHOOK_LOG.open("a", encoding="utf-8") as log_file:
        log_file.write(line + "\n")
    return {"ok": True}


# Tell the caller the clinic service is running.
@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}
