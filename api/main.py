from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import settings
from .storage import fetch_events, init_db, insert_events, stats_by_type

app = FastAPI(title="WarControl API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.web_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


class EventIn(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str
    message: str
    actor: str | None = None
    target: str | None = None
    server: str | None = None
    source: str | None = None
    raw: str | None = None


class IngestPayload(BaseModel):
    events: list[EventIn]


def _require_api_key(api_key: str | None) -> None:
    if settings.allow_open_ingest:
        return
    if not settings.ingest_key:
        raise HTTPException(
            status_code=503,
            detail="Ingest key not configured. Set WARCONTROL_INGEST_KEY or enable WARCONTROL_ALLOW_OPEN_INGEST=1.",
        )
    if api_key != settings.ingest_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.post("/ingest")
def ingest(
    payload: IngestPayload,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    _require_api_key(x_api_key)
    inserted = insert_events([event.model_dump() for event in payload.events])
    return {"inserted": inserted}


@app.get("/events")
def events(
    limit: int = Query(default=200, ge=1, le=1000),
    since: str | None = Query(default=None),
    event_type: str | None = Query(default=None, alias="type"),
) -> dict[str, Any]:
    rows = fetch_events(limit=limit, since=since, event_type=event_type)
    return {"events": rows}


@app.get("/stats")
def stats() -> dict[str, Any]:
    return {"by_type": stats_by_type()}
