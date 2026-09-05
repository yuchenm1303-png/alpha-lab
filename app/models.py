from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


def _validate_horizons(horizons: list[int]) -> list[int]:
    normalized = sorted(set(horizons))
    if not normalized:
        raise ValueError("at least one horizon is required")
    if any(h < 1 or h > 60 for h in normalized):
        raise ValueError("horizons must be between 1 and 60 trading days")
    return normalized


class EventStudyRequest(BaseModel):
    start_date: date
    end_date: date
    turnover_min: float = Field(default=0.0, ge=0)
    turnover_max: float = Field(default=100.0, ge=0)
    popularity_rank_min: int = Field(default=1, ge=1)
    popularity_rank_max: int = Field(default=100, ge=1)
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20])

    @model_validator(mode="after")
    def validate_ranges(self) -> "EventStudyRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if self.turnover_min > self.turnover_max:
            raise ValueError("turnover_min must be <= turnover_max")
        if self.popularity_rank_min > self.popularity_rank_max:
            raise ValueError("popularity_rank_min must be <= popularity_rank_max")
        self.horizons = _validate_horizons(self.horizons)
        return self


class FactorFilter(BaseModel):
    factor_id: str = Field(min_length=1, max_length=64)
    min_value: float | None = None
    max_value: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "FactorFilter":
        if self.min_value is None and self.max_value is None:
            raise ValueError("factor filter requires min_value and/or max_value")
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValueError("factor filter min_value must be <= max_value")
        return self


class ResearchEventStudyRequest(BaseModel):
    start_date: date
    end_date: date
    filters: list[FactorFilter] = Field(default_factory=list, max_length=16)
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10, 20])

    @model_validator(mode="after")
    def validate_request(self) -> "ResearchEventStudyRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        factor_ids = [item.factor_id for item in self.filters]
        if len(factor_ids) != len(set(factor_ids)):
            raise ValueError("duplicate factor filters are not allowed")
        self.horizons = _validate_horizons(self.horizons)
        return self


class HistoricalSyncRequest(BaseModel):
    start_date: date
    end_date: date
    max_rank: int = Field(default=100, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_dates(self) -> "HistoricalSyncRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class HorizonStat(BaseModel):
    horizon: int
    sample_count: int
    coverage_rate: float | None
    positive_rate: float | None
    average_return: float | None
    median_return: float | None
    return_stddev: float | None


class EventStudyResult(BaseModel):
    event_count: int
    stats: list[HorizonStat]


class EventSample(BaseModel):
    symbol: str
    trade_date: date
    turnover_rate: float
    popularity_rank: int
    close: float
    forward_returns: dict[str, float | None]


class EventSamplePage(BaseModel):
    total_count: int
    limit: int
    offset: int
    samples: list[EventSample]


class ResearchEventSample(BaseModel):
    symbol: str
    trade_date: date
    close: float
    factors: dict[str, float | None]
    forward_returns: dict[str, float | None]


class ResearchEventSamplePage(BaseModel):
    total_count: int
    limit: int
    offset: int
    samples: list[ResearchEventSample]


class FactorInfo(BaseModel):
    id: str
    label: str
    group: str
    unit: str
    storage: str
    description: str


class HistoricalSyncResult(BaseModel):
    start_date: date
    end_date: date
    bar_start_date: date
    bar_end_date: date
    popularity_rows: int
    bar_rows: int
    factor_rows: int
    unique_symbols: int
    unsupported_symbols: list[str]


class ImportResult(BaseModel):
    imported_rows: int


class DataStats(BaseModel):
    bars: int
    popularity_rows: int
    first_trade_date: date | None
    last_trade_date: date | None
