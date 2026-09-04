from __future__ import annotations

from app.db import Database
from app.models import (
    EventSample,
    EventSamplePage,
    EventStudyRequest,
    EventStudyResult,
    FactorFilter,
    ResearchEventStudyRequest,
)
from app.services.research import ResearchEventStudyEngine


class EventStudyEngine:
    """Backward-compatible adapter for the original turnover + popularity study."""

    def __init__(self, database: Database) -> None:
        self.research = ResearchEventStudyEngine(database)

    @staticmethod
    def _research_request(request: EventStudyRequest) -> ResearchEventStudyRequest:
        return ResearchEventStudyRequest(
            start_date=request.start_date,
            end_date=request.end_date,
            filters=[
                FactorFilter(
                    factor_id="turnover_rate",
                    min_value=request.turnover_min,
                    max_value=request.turnover_max,
                ),
                FactorFilter(
                    factor_id="popularity_rank",
                    min_value=float(request.popularity_rank_min),
                    max_value=float(request.popularity_rank_max),
                ),
            ],
            horizons=request.horizons,
        )

    def run(self, request: EventStudyRequest) -> EventStudyResult:
        return self.research.run(self._research_request(request))

    def samples(
        self,
        request: EventStudyRequest,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> EventSamplePage:
        page = self.research.samples(
            self._research_request(request),
            limit=limit,
            offset=offset,
        )
        samples = [
            EventSample(
                symbol=item.symbol,
                trade_date=item.trade_date,
                turnover_rate=float(item.factors["turnover_rate"]),
                popularity_rank=int(item.factors["popularity_rank"]),
                close=item.close,
                forward_returns=item.forward_returns,
            )
            for item in page.samples
        ]
        return EventSamplePage(
            total_count=page.total_count,
            limit=page.limit,
            offset=page.offset,
            samples=samples,
        )
