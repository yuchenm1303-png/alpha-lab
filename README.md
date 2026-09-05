# Alpha Lab

Alpha Lab 是一个 A 股多因子历史事件研究系统，用真实历史时点条件回答：**某组信号同时出现后，股票未来 1 / 3 / 5 / 10 / 20 个交易日表现怎么样？**

## 当前能力

网页支持动态叠加因子条件，后端统一由 `ResearchEventStudyEngine` 计算，不为每个新指标复制一套统计代码。

当前可研究因子：

- 换手率、人气排名、人气值；
- 当日涨幅、振幅、日内涨幅；
- 成交量、成交额、5 日量比；
- ST 状态、上市天数；
- 估算流通市值；
- 是否涨停、连板天数、封单金额。

输出包括事件数、未来各周期红盘率、平均涨幅、中位涨幅、标准差、有效样本覆盖率和可钻取的历史样本明细。

## 数据架构

Alpha Lab 现在把“全市场价格宇宙”和“特色条件补充数据”分开存储，避免不同数据源互相覆盖。

```text
HiThink 全市场 dump
  ├─ daily-k / daily-k-10d（未复权 OHLCV + 成交额）
  └─ adjustment-factors（除权除息事件）
                ↓
market_daily_raw + market_adjustment_events
                ↓
market_adjust_factors
                ↓
research_daily_bars（前复权研究视图）
                ↑
BaoStock 补充：换手率 / ST / 上市日期
                ↑
HiThink 特色因子：人气排名 / 涨停池 / 连板 / 封单
                ↓
ResearchEventStudyEngine
```

全市场 dump 同步后，OHLC、成交量、成交额、涨跌幅、振幅、日内涨幅、5 日量比等价格/量价条件可以直接在全市场历史宇宙上研究。

换手率、ST、上市天数等字段当前仍由 BaoStock 补充；没有补充到的全市场股票对应字段保持为空，不会伪造。人气和涨停池本身也是稀疏时序数据，只有其有效历史覆盖窗口内才可用于筛选。

## 复权口径

HiThink 全市场 daily-k dump 是未复权行情，Alpha Lab **不会直接用它计算未来收益**。

系统先保存原始行情和除权除息事件，再按事件重建日频前复权因子：

```text
ratio = ((1 + bonus + rights) * previous_close)
        / (previous_close - cash_dividend + rights * rights_price)
```

随后：

```text
qfq_price = raw_price * forward_factor
```

因此现金分红、送股、配股不会被误判成真实价格暴跌。`research_daily_bars` 只暴露已经完成复权因子重建的全市场数据；若还没有全市场 dump，则自动回退到原有 BaoStock 前复权日线。

## 重要定义

- `5日量比` = 当日成交量 / **前 5 个有效交易日**平均成交量，当前日不进入分母；历史不足 5 日则为空。
- `是否ST` 来自历史交易日状态，而不是当前状态倒推。
- `上市天数` = 事件日距离 IPO 日期的自然日天数。系统不擅自规定“新股=多少天”，可自行筛 `<=30`、`<=60` 等。
- `是否涨停` 来自 HiThink 历史涨停池，不用固定 5%/10%/20% 阈值猜测板块规则。
- `估算流通市值（亿元）` = `成交额 / (换手率 / 100) / 1e8`。这是研究近似值，**不是官方历史时点精确市值**。
- 稀疏涨停因子中，未进入当日涨停池按 `0` 处理；进入涨停池才写入正值记录。

## 全市场同步

需要 Python 3.11+：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[data,dev]"
```

环境变量：

```bash
HITHINK_API_KEY=你的Key
ALPHALAB_ADMIN_TOKEN=你的管理令牌
```

第一次或日常推荐直接使用 `auto`：

```bash
python scripts/sync_market_dump.py --mode auto
```

`auto` 的行为：

- 本地还没有全市场数据：自动下载完整 daily-k；
- 本地数据与最近 10 个交易日增量窗口能衔接：只导入 daily-k-10d；
- 本地缺口已经超过增量窗口：自动回退完整 daily-k，避免数据库悄悄断档；
- 每次都会刷新 adjustment-factors 并重建前复权因子，因为新除权事件会改变历史前复权比例。

也可明确指定：

```bash
python scripts/sync_market_dump.py --mode full
python scripts/sync_market_dump.py --mode incremental
```

首轮完整同步数据量较大，正式环境建议直接在 VPS 上跑 CLI，而不是依赖浏览器请求长期保持连接。

## 人气 / 状态补充同步

现有同步入口继续保留，用于拉取历史人气、涨停池，以及人气股票的 BaoStock 换手率/ST/上市日期等补充字段：

```bash
python scripts/sync_real_data.py --start 2026-08-01 --end 2026-09-01 --max-rank 100
```

行情会向研究开始日前预留历史以支持滚动因子，并向结束日后预留最多 60 个交易日用于未来收益观察。

## CSV

旧 7 列 CSV 保持兼容：

```csv
symbol,trade_date,open,high,low,close,turnover_rate
000001.SZ,2026-01-05,9.8,10.2,9.7,10.0,8.0
```

也可增加可选列：

```text
volume, amount, is_st, ipo_date
```

缺少这些可选列时，对应高级因子保持为空，不伪造数据。

## API

基础与兼容接口：

- `GET /api/health`
- `GET /api/data/stats`
- `POST /api/import/bars`
- `POST /api/import/popularity`
- `POST /api/sync/historical`
- `POST /api/sync/market`：全市场 dump 同步，支持 `auto / full / incremental`
- `POST /api/analyze`
- `POST /api/analyze/samples`

通用研究接口：

- `GET /api/research/factors`
- `POST /api/research/event-study`
- `POST /api/research/event-study/samples`

示例：

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-09-01",
  "filters": [
    {"factor_id": "turnover_rate", "min_value": 5, "max_value": 15},
    {"factor_id": "popularity_rank", "min_value": 1, "max_value": 30},
    {"factor_id": "volume_ratio_5d", "min_value": 1.5, "max_value": 4},
    {"factor_id": "is_st", "min_value": 0, "max_value": 0}
  ],
  "horizons": [1, 3, 5, 10, 20]
}
```

## 部署

Vercel 只用于临时 Demo，因为 Serverless 本地文件系统不持久，且不适合存储/重建大规模全市场历史数据。正式版使用 VPS + Docker + 持久 DuckDB volume；`main` 更新后 GitHub Actions 会构建 GHCR 镜像。

## 下一步

1. 扩大全市场换手率、ST、上市日期等补充字段覆盖，不再只覆盖人气股票；
2. 增加数据覆盖率/新鲜度诊断，研究前明确提示每个因子的历史覆盖范围；
3. 增加资金流、龙虎榜、板块热度；
4. 增加逐年/逐月稳定性、收益分位数、最大回撤；
5. 保存和对比研究条件组合；
6. 增加 Research Agent：自然语言 → 结构化条件 → Event Study → 自动解释结果。
