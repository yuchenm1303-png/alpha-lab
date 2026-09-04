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
- 一个可以直接操作的简易 Web 页面；
- HiThink Financial-API 历史热股排名适配器；
- BaoStock 历史前复权 OHLC + 换手率适配器；
- 双数据源自动归一化与同步服务。

## 统计口径

事件日收盘价记为 `P0`，未来第 N 个交易日收盘价记为 `PN`：

```text
forward_return_N = (PN / P0 - 1) * 100%
```

`红盘率`定义为该周期 `forward_return_N > 0` 的有效样本占比。

这里使用的是**股票自己的后续有效交易记录顺序**，不是自然日，因此周末不会被错误算作持有期。BaoStock 返回 `tradestatus=0` 的停牌记录在数据适配层直接排除，也不会被算成一个交易日。

## 数据源设计

第一版真实数据链路不是强行让一个供应商提供全部字段，而是按字段来源拆开：

```text
HiThink Financial-API
  └─ 历史热股榜 rank
                 ┐
                 ├─> normalize(symbol, date) -> DuckDB -> EventStudyEngine
                 │
BaoStock         │
  └─ 前复权 OHLC + turn(换手率) + tradestatus
                 ┘
```

这样做的原因是 HiThink 当前历史 K 线提供 OHLC、成交量、成交额，但不直接提供历史换手率；历史热股榜则能直接提供历史排名。BaoStock 日频历史接口包含 `turn`，并能提供历史交易状态。

### 当前边界

- HiThink 历史热股榜与交易日历固定在服务器最近一年窗口，因此**当前组合研究的共同有效窗口按最近一年处理**。
- BaoStock 的 `turn` 本身就是百分比数值，例如 `0.31` 表示 `0.31%`，不要再乘 100。
- BaoStock 当前不支持北交所；`.BJ` 标的会被明确列入 `unsupported_symbols`，不会静默混入样本。
- 行情使用 BaoStock `adjustflag=2`（前复权），避免分红送转产生的机械价格跳变被误算成策略收益。
- HiThink API 成功必须同时满足 HTTP 200 和响应 `code == 0`。
- HiThink API Key 只允许从环境变量读取，禁止提交到 GitHub。

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

## 同步真实历史数据

真实数据同步额外安装 BaoStock：

```bash
pip install -e ".[data,dev]"
```

配置 HiThink API Key：

Windows PowerShell：

```powershell
$env:HITHINK_API_KEY="你的 API Key"
```

macOS / Linux：

```bash
export HITHINK_API_KEY="你的 API Key"
```

同步最近一段历史数据：

```bash
python scripts/sync_real_data.py --start 2026-08-01 --end 2026-09-01 --max-rank 100
```

同步过程会：

1. 从 HiThink 交易日历获取真实交易日；
2. 逐交易日拉取历史热股榜；
3. 收集榜单涉及的股票代码；
4. 用 BaoStock 一次登录会话拉取这些股票的前复权 OHLC 与换手率；
5. 排除停牌记录；
6. 按 `symbol + trade_date` 归一化写入 DuckDB；
7. 北交所等 BaoStock 不支持的代码单独返回，不伪造数据。

## CSV 数据格式

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

## 部署说明

Vercel 部署当前用于 Web MVP 演示。Vercel Serverless 的本地文件系统不是持久数据库，因此线上 DuckDB 使用 `/tmp` 并自动装载少量 demo 数据；`GET /api/health` 会返回 `persistent_storage: false`。

**不要把 Vercel 的临时 DuckDB 当成真实历史数据库。** 正式自动同步上线前，需要把数据同步任务与持久存储迁移到长期运行环境（例如 VPS 上的本地 DuckDB，或后续独立持久数据库）。

## 架构原则

```text
HiThink ──────┐
              ├─> Provider adapters -> normalized storage
BaoStock ─────┘                         |
                                        v
                                 EventStudyEngine
                                        |
                              FastAPI + Web UI
```

统计引擎只依赖规范化数据，不直接调用任何上游 API。上游数据源变化时只替换 adapter，不改历史收益计算逻辑。

## 下一阶段

1. 把真实同步任务部署到持久运行环境；
2. 让 Web 页面直接读取持久历史数据库，不再依赖手工 CSV；
3. 增加市值、当日涨幅、量比、ST/新股等复合筛选条件；
4. 增加逐年/逐月稳定性、分位数、最大回撤等统计；
5. 接入资金流、龙虎榜、公告、新闻等 a-stock-data 扩展信号；
6. 做信号组合保存、对比与策略研究工作台。
