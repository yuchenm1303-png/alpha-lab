from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.models import DataStats, EventStudyRequest, EventStudyResult, ImportResult
from app.repository import MarketRepository
from app.services.csv_import import parse_bars_csv, parse_popularity_csv
from app.services.event_study import EventStudyEngine


database = Database()
repository = MarketRepository(database)
engine = EventStudyEngine(database)

app = FastAPI(title="Alpha Lab", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    database.initialize()
    if os.getenv("VERCEL"):
        _seed_demo_data_if_empty()


def _seed_demo_data_if_empty() -> None:
    if repository.stats()["bars"]:
        return

    bars = [
        ("000001.SZ", "2026-01-05", 9.8, 10.2, 9.7, 10.0, 8.0),
        ("000001.SZ", "2026-01-06", 10.1, 11.2, 10.0, 11.0, 8.0),
        ("000001.SZ", "2026-01-07", 10.8, 11.0, 8.8, 9.0, 20.0),
        ("000001.SZ", "2026-01-08", 9.2, 12.1, 9.1, 12.0, 8.0),
        ("000001.SZ", "2026-01-09", 12.0, 13.2, 11.9, 13.0, 8.0),
        ("000001.SZ", "2026-01-12", 13.0, 13.7, 12.9, 13.5, 8.0),
        ("000001.SZ", "2026-01-13", 13.5, 14.1, 13.4, 14.0, 8.0),
        ("000001.SZ", "2026-01-14", 14.0, 14.3, 13.8, 14.2, 8.0),
    ]
    popularity = [
        ("000001.SZ", "2026-01-05", 10, 9000.0),
        ("000001.SZ", "2026-01-06", 15, 8500.0),
        ("000001.SZ", "2026-01-07", 5, 9500.0),
        ("000001.SZ", "2026-01-08", 50, 6000.0),
        ("000001.SZ", "2026-01-09", 50, 5900.0),
        ("000001.SZ", "2026-01-12", 50, 5800.0),
        ("000001.SZ", "2026-01-13", 50, 5700.0),
        ("000001.SZ", "2026-01-14", 50, 5600.0),
    ]
    repository.upsert_bars(bars)
    repository.upsert_popularity(popularity)


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "runtime": "vercel" if os.getenv("VERCEL") else "local",
        "persistent_storage": not bool(os.getenv("VERCEL")),
    }


@app.get("/api/data/stats", response_model=DataStats)
def data_stats() -> DataStats:
    return DataStats(**repository.stats())


@app.post("/api/import/bars", response_model=ImportResult)
async def import_bars(file: UploadFile = File(...)) -> ImportResult:
    try:
        rows = parse_bars_csv(await file.read())
        return ImportResult(imported_rows=repository.upsert_bars(rows))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/import/popularity", response_model=ImportResult)
async def import_popularity(file: UploadFile = File(...)) -> ImportResult:
    try:
        rows = parse_popularity_csv(await file.read())
        return ImportResult(imported_rows=repository.upsert_popularity(rows))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/analyze", response_model=EventStudyResult)
def analyze(request: EventStudyRequest) -> EventStudyResult:
    return engine.run(request)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
