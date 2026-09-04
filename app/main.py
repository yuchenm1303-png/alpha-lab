from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.models import (
    DataStats,
    EventSamplePage,
    EventStudyRequest,
    EventStudyResult,
    FactorInfo,
    HistoricalSyncRequest,
    HistoricalSyncResult,
    ImportResult,
    ResearchEventSamplePage,
    ResearchEventStudyRequest,
)
from app.repository import MarketRepository
from app.research.factors import list_factor_specs
from app.services.csv_import import parse_bars_csv, parse_popularity_csv
from app.services.event_study import EventStudyEngine
from app.services.research import ResearchEventStudyEngine


database = Database()
repository = MarketRepository(database)
engine = EventStudyEngine(database)
research_engine = ResearchEventStudyEngine(database)

app = FastAPI(title="Alpha Lab", version="0.5.0")


def require_write_access(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    expected = os.getenv("ALPHALAB_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Write operations are disabled until ALPHALAB_ADMIN_TOKEN is configured.",
        )
    if x_admin_token is None or not secrets.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


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
    is_vercel = bool(os.getenv("VERCEL"))
    hithink_configured = bool(os.getenv("HITHINK_API_KEY"))
    write_auth_configured = bool(os.getenv("ALPHALAB_ADMIN_TOKEN"))
    return {
        "status": "ok",
        "runtime": "vercel" if is_vercel else "local",
        "persistent_storage": not is_vercel,
        "write_auth_configured": write_auth_configured,
        "real_sync_configured": hithink_configured,
        "real_sync_enabled": (not is_vercel) and hithink_configured and write_auth_configured,
    }


@app.get("/api/data/stats", response_model=DataStats)
def data_stats() -> DataStats:
    return DataStats(**repository.stats())


@app.get("/api/research/factors", response_model=list[FactorInfo])
def research_factors() -> list[FactorInfo]:
    return [
        FactorInfo(
            id=spec.id,
            label=spec.label,
            group=spec.group,
            unit=spec.unit,
            storage=spec.storage,
            description=spec.description,
        )
        for spec in list_factor_specs()
    ]


@app.post("/api/import/bars", response_model=ImportResult, dependencies=[Depends(require_write_access)])
async def import_bars(file: UploadFile = File(...)) -> ImportResult:
    try:
        rows = parse_bars_csv(await file.read())
        return ImportResult(imported_rows=repository.upsert_bars(rows))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/import/popularity", response_model=ImportResult, dependencies=[Depends(require_write_access)])
async def import_popularity(file: UploadFile = File(...)) -> ImportResult:
    try:
        rows = parse_popularity_csv(await file.read())
        return ImportResult(imported_rows=repository.upsert_popularity(rows))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sync/historical", response_model=HistoricalSyncResult, dependencies=[Depends(require_write_access)])
def sync_historical(request: HistoricalSyncRequest) -> HistoricalSyncResult:
    if os.getenv("VERCEL"):
        raise HTTPException(status_code=409, detail="Real-data sync is disabled on ephemeral Vercel storage; deploy to persistent storage first.")

    from app.providers.baostock import BaoStockClient, BaoStockError
    from app.providers.hithink import HiThinkClient, HiThinkError
    from app.services.sync import HistoricalSignalSyncService

    try:
        summary = HistoricalSignalSyncService(HiThinkClient(), BaoStockClient(), repository).sync(
            request.start_date,
            request.end_date,
            max_rank=request.max_rank,
        )
    except (HiThinkError, BaoStockError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return HistoricalSyncResult(
        start_date=summary.start_date,
        end_date=summary.end_date,
        bar_end_date=summary.bar_end_date,
        popularity_rows=summary.popularity_rows,
        bar_rows=summary.bar_rows,
        unique_symbols=summary.unique_symbols,
        unsupported_symbols=list(summary.unsupported_symbols),
    )


@app.post("/api/analyze", response_model=EventStudyResult)
def analyze(request: EventStudyRequest) -> EventStudyResult:
    return engine.run(request)


@app.post("/api/analyze/samples", response_model=EventSamplePage)
def analyze_samples(
    request: EventStudyRequest,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> EventSamplePage:
    return engine.samples(request, limit=limit, offset=offset)


@app.post("/api/research/event-study", response_model=EventStudyResult)
def research_event_study(request: ResearchEventStudyRequest) -> EventStudyResult:
    try:
        return research_engine.run(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/research/event-study/samples", response_model=ResearchEventSamplePage)
def research_event_samples(
    request: ResearchEventStudyRequest,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ResearchEventSamplePage:
    try:
        return research_engine.samples(request, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
