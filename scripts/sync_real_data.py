from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date, timedelta

from app.db import Database
from app.providers.baostock import BaoStockClient
from app.providers.hithink import HiThinkClient
from app.repository import MarketRepository
from app.services.sync import HistoricalSignalSyncService


def parse_args() -> argparse.Namespace:
    today = date.today()
    parser = argparse.ArgumentParser(description="Sync Alpha Lab historical signal data")
    parser.add_argument("--start", type=date.fromisoformat, default=today - timedelta(days=30))
    parser.add_argument("--end", type=date.fromisoformat, default=today)
    parser.add_argument("--max-rank", type=int, default=100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = Database()
    database.initialize()
    hithink = HiThinkClient()
    service = HistoricalSignalSyncService(
        hithink,
        BaoStockClient(),
        MarketRepository(database),
        factor_provider=hithink,
    )
    summary = service.sync(args.start, args.end, max_rank=args.max_rank)
    print(json.dumps(asdict(summary), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
