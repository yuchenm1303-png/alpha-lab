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


_FACTOR_SPECS = (
    FactorSpec(
        id="turnover_rate",
        label="换手率",
        group="量价",
        unit="percent",
        storage="bar",
        column="turnover_rate",
        description="历史交易日换手率，数值 8.5 表示 8.5%。",
    ),
    FactorSpec(
        id="change_pct",
        label="当日涨幅",
        group="价格",
        unit="percent",
        storage="derived",
        description="当日收盘价相对上一有效交易日收盘价的涨跌幅。",
    ),
    FactorSpec(
        id="amplitude",
        label="当日振幅",
        group="价格",
        unit="percent",
        storage="derived",
        description="(当日最高价 - 最低价) / 上一有效交易日收盘价。",
    ),
    FactorSpec(
        id="intraday_return",
        label="日内涨幅",
        group="价格",
        unit="percent",
        storage="derived",
        description="当日收盘价相对当日开盘价的涨跌幅。",
    ),
    FactorSpec(
        id="popularity_rank",
        label="人气排名",
        group="人气",
        unit="rank",
        storage="timeseries",
        description="历史交易日人气榜排名，数值越小排名越靠前。",
    ),
    FactorSpec(
        id="popularity_score",
        label="人气值",
        group="人气",
        unit="score",
        storage="timeseries",
        description="上游存在时保存的历史人气绝对值；缺失时保持为空，不猜测。",
    ),
)

FACTOR_REGISTRY: dict[str, FactorSpec] = {spec.id: spec for spec in _FACTOR_SPECS}


def get_factor_spec(factor_id: str) -> FactorSpec:
    try:
        return FACTOR_REGISTRY[factor_id]
    except KeyError as exc:
        raise ValueError(f"unsupported factor: {factor_id}") from exc


def list_factor_specs() -> list[FactorSpec]:
    return list(_FACTOR_SPECS)
