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
    root = Path(__file__).resolve().parents[1]
    bars_path = root / "sample_data" / "bars.csv"
    popularity_path = root / "sample_data" / "popularity.csv"
    if bars_path.exists() and popularity_path.exists():
        repository.upsert_bars(parse_bars_csv(bars_path.read_bytes()))
        repository.upsert_popularity(parse_popularity_csv(popularity_path.read_bytes()))


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
