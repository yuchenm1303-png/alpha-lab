from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


FactorStorage = Literal["bar", "timeseries", "derived"]


@dataclass(frozen=True)
class FactorSpec:
    id: str
    label: str
    group: str
    unit: str
    storage: FactorStorage
    column: str | None = None
    description: str = ""
    missing_value: float | None = None


FACTOR_REGISTRY: dict[str, FactorSpec] = {
    "turnover_rate": FactorSpec(
        id="turnover_rate",
        label="换手率",
        group="量价",
        unit="%",
        storage="bar",
        column="turnover_rate",
        description="历史日线换手率，百分数值。",
    ),
    "volume": FactorSpec(
        id="volume",
        label="成交量",
        group="量价",
        unit="股",
        storage="bar",
        column="volume",
        description="历史日线成交量。",
    ),
    "amount": FactorSpec(
        id="amount",
        label="成交额",
        group="量价",
        unit="元",
        storage="bar",
        column="amount",
        description="历史日线成交额。",
    ),
    "change_pct": FactorSpec(
        id="change_pct",
        label="当日涨幅",
        group="量价",
        unit="%",
        storage="derived",
        description="当日收盘价相对上一有效交易日收盘价的涨跌幅。",
    ),
    "amplitude": FactorSpec(
        id="amplitude",
        label="当日振幅",
        group="量价",
        unit="%",
        storage="derived",
        description="当日最高/最低价差相对上一有效交易日收盘价。",
    ),
    "intraday_return": FactorSpec(
        id="intraday_return",
        label="日内涨幅",
        group="量价",
        unit="%",
        storage="derived",
        description="当日收盘价相对当日开盘价的涨跌幅。",
    ),
    "volume_ratio_5d": FactorSpec(
        id="volume_ratio_5d",
        label="5日量比",
        group="量价",
        unit="倍",
        storage="derived",
        description="当日成交量 / 前5个有效交易日平均成交量；不足5日时为空。",
    ),
    "float_market_cap_est": FactorSpec(
        id="float_market_cap_est",
        label="估算流通市值",
        group="规模",
        unit="亿元",
        storage="derived",
        description="按当日成交额/换手率反推的VWAP口径估算流通市值，不是官方收盘时点市值。",
    ),
    "is_st": FactorSpec(
        id="is_st",
        label="是否ST",
        group="状态",
        unit="0/1",
        storage="derived",
        description="历史交易日 ST 状态：1=是，0=否。",
    ),
    "listing_age_days": FactorSpec(
        id="listing_age_days",
        label="上市天数",
        group="状态",
        unit="天",
        storage="derived",
        description="事件日距上市日期的自然日天数，可用于定义新股/次新股条件。",
    ),
    "popularity_rank": FactorSpec(
        id="popularity_rank",
        label="人气排名",
        group="人气",
        unit="rank",
        storage="timeseries",
        description="历史时点人气排名，数字越小排名越靠前。",
    ),
    "popularity_score": FactorSpec(
        id="popularity_score",
        label="人气值",
        group="人气",
        unit="score",
        storage="timeseries",
        description="上游提供时保存的历史人气值；缺失日期不会伪造。",
    ),
    "is_limit_up": FactorSpec(
        id="is_limit_up",
        label="是否涨停",
        group="涨停",
        unit="0/1",
        storage="timeseries",
        description="HiThink 历史涨停池：1=当日进入涨停池，缺失视为0。",
        missing_value=0.0,
    ),
    "limit_up_streak": FactorSpec(
        id="limit_up_streak",
        label="连板天数",
        group="涨停",
        unit="天",
        storage="timeseries",
        description="HiThink 涨停池 continue_day_cnt；非涨停日视为0。",
        missing_value=0.0,
    ),
    "limit_up_seal_money": FactorSpec(
        id="limit_up_seal_money",
        label="封单金额",
        group="涨停",
        unit="元",
        storage="timeseries",
        description="HiThink 历史涨停池封单金额；非涨停日视为0。",
        missing_value=0.0,
    ),
}


def list_factor_specs() -> list[FactorSpec]:
    return list(FACTOR_REGISTRY.values())


def get_factor_spec(factor_id: str) -> FactorSpec:
    try:
        return FACTOR_REGISTRY[factor_id]
    except KeyError as exc:
        raise ValueError(f"unsupported factor: {factor_id}") from exc
