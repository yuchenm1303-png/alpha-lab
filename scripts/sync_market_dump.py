from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.db import Database
from app.providers.hithink import HiThinkClient
from app.services.market_dump import MarketDumpSyncService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync HiThink whole-market daily-K and adjustment-factor dumps"
    )
    parser.add_argument(
        "--mode",
        choices=("auto", "full", "incremental"),
        default="auto",
        help="auto: bootstrap full if needed, otherwise use recent-10d increment",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database = Database()
    database.initialize()
    summary = MarketDumpSyncService(HiThinkClient(), database).sync(args.mode)
    print(json.dumps(asdict(summary), ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
