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

## 数据与口径

真实同步链路：

```text
HiThink Financial-API
  ├─ 历史人气排名
  └─ 历史涨停池（涨停/连板/封单）

BaoStock
  └─ 前复权 OHLC + 换手率 + 成交量/额 + ST + 上市日期

              ↓
daily_bars + factor_values
              ↓
Factor Registry
              ↓
ResearchEventStudyEngine
```

同步研究区间时，行情会同时向前拉取一段历史以支持滚动/滞后因子，并向后预留最多 60 个交易日的观察窗口。事件收益使用股票自己的后续有效交易记录，不按自然日计算；停牌记录不会被当作一个交易日。

### 重要定义

- `5日量比` = 当日成交量 / **前 5 个有效交易日**平均成交量，当前日不进入分母；历史不足 5 日则为空。
- `是否ST` 来自历史交易日状态，而不是当前状态倒推。
- `上市天数` = 事件日距离 IPO 日期的自然日天数。系统不擅自规定“新股=多少天”，可自行筛 `<=30`、`<=60` 等。
- `是否涨停` 来自 HiThink 历史涨停池，不用固定 5%/10%/20% 阈值猜测板块规则。
- `估算流通市值（亿元）` = `成交额 / (换手率 / 100) / 1e8`。这是按当日成交均价近似反推的研究因子，**不是官方收盘时点精确市值**。在没有可靠历史市值源之前，系统不会拿当前市值倒推历史。
- 稀疏涨停因子中，未进入当日涨停池按 `0` 处理；进入涨停池才写入正值记录。

### 研究宇宙限制

当前自动同步仍以历史人气榜 Top N 涉及的股票作为行情下载宇宙。因此，如果研究条件完全不包含人气因子，结果仍然代表“已同步的人气股票宇宙”，不是全 A 股无偏全市场样本。后续接全市场日线 dump 后会解除这一限制。

## 快速运行

需要 Python 3.11+：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

真实数据同步额外安装：

```bash
pip install -e ".[data,dev]"
```

环境变量：

```bash
HITHINK_API_KEY=你的Key
ALPHALAB_ADMIN_TOKEN=你的管理令牌
```

同步示例：

```bash
python scripts/sync_real_data.py --start 2026-08-01 --end 2026-09-01 --max-rank 100
```

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

兼容接口：

- `GET /api/health`
- `GET /api/data/stats`
- `POST /api/import/bars`
- `POST /api/import/popularity`
- `POST /api/sync/historical`
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

Vercel 只用于临时 Demo，因为 Serverless 本地文件系统不持久。正式版使用 VPS + Docker + 持久 DuckDB volume；`main` 更新后 GitHub Actions 会构建 GHCR 镜像。

## 下一步

1. 接 HiThink 全市场 daily-k dump，解除 Top N 人气宇宙限制；
2. 增加资金流、龙虎榜、板块热度；
3. 增加逐年/逐月稳定性、收益分位数、最大回撤；
4. 保存和对比研究条件组合；
5. 增加 Research Agent：自然语言 → 结构化条件 → Event Study → 自动解释结果。
