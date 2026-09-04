# Alpha Lab

Alpha Lab 是一个轻量级 A 股历史条件事件统计系统。第一版专门解决一个问题：**历史上满足某组条件的股票，后续表现到底怎么样？**

当前 MVP 支持：

- 按历史 `换手率` 区间筛选；
- 按历史 `人气排名` 区间筛选；
- 统计未来 1 / 3 / 5 / 10 / 20 个交易日累计收益；
- 输出红盘率、平均涨幅、中位涨幅、收益标准差和有效样本数；
- DuckDB 本地存储；
- CSV 导入；
- FastAPI API；
- 一个可以直接操作的简易 Web 页面。

## 统计口径

事件日收盘价记为 `P0`，未来第 N 个交易日收盘价记为 `PN`：

```text
forward_return_N = (PN / P0 - 1) * 100%
```

`红盘率`定义为该周期 `forward_return_N > 0` 的有效样本占比。

这里使用的是**股票自己的后续交易记录顺序**，不是自然日，因此周末不会被错误算作持有期。停牌日如果没有行情记录，也不会人为增加一个交易日。

## 快速运行

需要 Python 3.11+。

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -e ".[dev]"
uvicorn app.main:app --reload
```

打开：`http://127.0.0.1:8000`

运行测试：

```bash
pytest
```

## 数据格式

日线 CSV：

```csv
symbol,trade_date,open,high,low,close,turnover_rate
000001.SZ,2026-01-05,9.8,10.2,9.7,10.0,8.0
```

历史人气 CSV：

```csv
symbol,trade_date,popularity_rank,popularity_score
000001.SZ,2026-01-05,10,9000
```

`popularity_score` 可为空；当前筛选使用 `popularity_rank`。

仓库中的 `sample_data/` 可以直接上传测试。

## API

- `GET /api/health`：健康检查
- `GET /api/data/stats`：当前数据量与日期覆盖
- `POST /api/import/bars`：导入日线 CSV
- `POST /api/import/popularity`：导入历史人气 CSV
- `POST /api/analyze`：运行历史事件统计

分析请求示例：

```json
{
  "start_date": "2025-09-01",
  "end_date": "2026-09-01",
  "turnover_min": 5,
  "turnover_max": 15,
  "popularity_rank_min": 1,
  "popularity_rank_max": 30,
  "horizons": [1, 3, 5, 10, 20]
}
```

## 架构方向

```text
HiThink Financial-API ─┐
                       ├─> Provider adapters -> normalized DuckDB data
A-stock-data ──────────┘                         |
                                                v
                                         EventStudyEngine
                                                |
                                      FastAPI + Web UI
```

统计引擎只依赖规范化后的本地数据，不直接依赖任何上游 API。这样后续可以把 HiThink 作为主数据源、a-stock-data 作为补充/备用源，而不需要改动回测和统计逻辑。

## 下一阶段

1. 接 HiThink Financial-API 自动同步日线、换手率和历史热榜；
2. 接 a-stock-data 补充人气、资金流、龙虎榜等信号；
3. 增加市值、当日涨幅、量比等复合筛选条件；
4. 增加逐年/逐月稳定性、分位数、最大回撤等统计；
5. 做信号组合保存与结果对比。
