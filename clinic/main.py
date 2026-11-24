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
PLACEHOLDER_WORDS = ("placeholder", "unknown", "n/a", "name", "test", "none", "null")


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


# List the free appointment times for one date.
@app.post("/slots")
async def list_slots(
    body: SlotsRequest,
    delay_ms: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await wait_if_requested(delay_ms)
    return {"date": body.date, "slots": free_slots(body.date)}


# Explain why a patient name cannot be booked, or return None when it is acceptable.
def name_problem(name: str) -> str | None:
    cleaned = name.strip()
    if len(cleaned) < 2:
        return "Name must be at least 2 characters."
    if not any(character.isalpha() for character in cleaned):
        return "Name must include letters."
    if any(character in "[]{}<>" for character in cleaned):
        return "Name looks like a placeholder."
    lowered = cleaned.casefold()
    if any(word in lowered for word in PLACEHOLDER_WORDS):
        return "Name looks like a placeholder."
    return None


# Explain why a phone number cannot be booked, or return None when it is acceptable.
def phone_problem(phone: str) -> str | None:
    cleaned = phone.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if re.fullmatch(r"\d{10,13}", cleaned) is None:
        return "Phone must be 10 to 13 digits."
    return None


# Book one slot, or say it is taken or missing.
@app.post("/book")
async def book(
    body: BookRequest,
    delay_ms: int = Query(default=0, ge=0),
) -> JSONResponse:
    name = body.name.strip()
    phone = body.phone.strip()
    name_message = name_problem(name)
    if name_message is not None:
        return JSONResponse(
            status_code=422,
            content={"status": "invalid_input", "field": "name", "message": name_message},
        )
    phone_message = phone_problem(phone)
    if phone_message is not None:
        return JSONResponse(
            status_code=422,
            content={"status": "invalid_input", "field": "phone", "message": phone_message},
        )
    await wait_if_requested(delay_ms)
    result = book_slot(body.date, body.time, name, phone)
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
