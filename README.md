# Alpha Lab

Alpha Lab 是一个轻量级 A 股多因子历史事件研究系统。核心问题是：**历史上同时满足某组条件的股票，后续 1 / 3 / 5 / 10 / 20 个交易日表现到底怎么样？**

当前版本已经从固定的“换手率 + 人气排名”统计器升级为通用因子研究架构，同时保留旧 API 兼容。

## 当前能力

- 动态因子条件构建器，可同时组合多个条件；
- 当前因子：`换手率`、`人气排名`、`人气值`、`当日涨幅`、`当日振幅`、`日内涨幅`；
- 统计未来 1 / 3 / 5 / 10 / 20 个交易日累计收益；
- 输出红盘率、平均涨幅、中位涨幅、收益标准差、有效样本数和覆盖率；
- 样本明细钻取，可核查具体日期、股票、事件时点因子值和后续收益；
- DuckDB 持久存储；
- `factor_values` 通用时序因子表；
- 因子注册表，新增因子后研究 API 与 Web 下拉框自动识别；
- FastAPI + 简易 Web UI；
- HiThink Financial-API 历史热股排名适配器；
- BaoStock 历史前复权 OHLC + 换手率适配器；
- 双数据源自动归一化与同步；
- Docker / GHCR 生产镜像；
- 写操作管理令牌保护。

## 统计口径

事件日收盘价记为 `P0`，未来第 N 个交易日收盘价记为 `PN`：

```text
forward_return_N = (PN / P0 - 1) * 100%
```

`红盘率`定义为该周期 `forward_return_N > 0` 的有效样本占比。

持有期使用**股票自己的后续有效交易记录顺序**，不是自然日。周末不会被算入，BaoStock `tradestatus=0` 的停牌记录也会在数据适配层排除。

为了避免研究区间末端样本缺少未来行情，同步服务会在研究结束日期之后额外拉取未来观察窗口所需的交易日数据。

## 因子架构

Alpha Lab 不再为每个新指标建立一套专用研究代码。

```text
Provider / Derived data
        |
        v
normalized daily_bars + factor_values
        |
        v
Factor Registry
        |
        v
ResearchEventStudyEngine
        |
        +--> statistics
        +--> sample drilldown
        |
        v
FastAPI + dynamic Web condition builder
```

### 存储型因子

`daily_bars` 保存行情基础字段，例如历史换手率。

`factor_values` 保存任意按 `symbol + trade_date` 对齐的时序因子：

```text
symbol | trade_date | factor_id | value | source
```

当前历史人气会同时保持旧 `popularity` 表兼容，并自动镜像到：

- `popularity_rank`
- `popularity_score`

已有旧数据库启动时也会自动回填，不需要手工迁移。

### 派生因子

无需额外数据源、直接基于历史 OHLC 动态计算：

- `change_pct`：当日收盘相对上一交易日收盘涨幅；
- `amplitude`：当日高低价差 / 上一交易日收盘；
- `intraday_return`：当日收盘 / 当日开盘 - 1。

所有百分比因子在 Alpha Lab 研究接口里使用百分数值，例如 `5` 表示 `5%`。

## 数据源设计

当前真实链路：

```text
HiThink Financial-API
  └─ 历史热股榜 rank / score(若上游提供)
                 ┐
                 ├─> normalize(symbol, date) -> factor_values
                 │
BaoStock         │
  └─ 前复权 OHLC + turn(换手率) + tradestatus
                 └─> daily_bars
```

### 当前边界

- HiThink 历史热股榜与交易日历当前是服务器最近一年窗口，因此组合研究的共同有效窗口主要受这一限制；
- BaoStock `turn` 已经是百分比值，例如 `0.31` 表示 `0.31%`，不能再乘 100；
- BaoStock 当前不支持北交所，`.BJ` 标的会明确进入 `unsupported_symbols`；
- 行情使用 BaoStock `adjustflag=2` 前复权，降低分红送转造成的机械价格跳变；
- HiThink 成功必须同时满足 HTTP 200 与业务响应 `code == 0`；
- HiThink API Key 只从环境变量读取，禁止写入仓库。

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

真实同步额外安装 BaoStock：

```bash
pip install -e ".[data,dev]"
```

配置：

```bash
HITHINK_API_KEY=你的Key
ALPHALAB_ADMIN_TOKEN=你的管理令牌
```

同步示例：

```bash
python scripts/sync_real_data.py --start 2026-08-01 --end 2026-09-01 --max-rank 100
```

同步会：

1. 读取真实交易日；
2. 拉取每个交易日的人气榜；
3. 收集榜单涉及的股票；
4. 拉取这些股票的历史 OHLC 与换手率；
5. 排除停牌；
6. 自动延长行情窗口以覆盖未来收益周期；
7. 统一写入 DuckDB；
8. 将人气数据同步成正式时序因子。

## CSV 数据格式

日线：

```csv
symbol,trade_date,open,high,low,close,turnover_rate
000001.SZ,2026-01-05,9.8,10.2,9.7,10.0,8.0
```

历史人气：

```csv
symbol,trade_date,popularity_rank,popularity_score
000001.SZ,2026-01-05,10,9000
```

`popularity_score` 可以为空。

## API

基础与兼容接口：

- `GET /api/health`
- `GET /api/data/stats`
- `POST /api/import/bars`
- `POST /api/import/popularity`
- `POST /api/sync/historical`
- `POST /api/analyze`：旧版“换手率 + 人气排名”兼容入口
- `POST /api/analyze/samples`

通用研究接口：

- `GET /api/research/factors`：因子目录
- `POST /api/research/event-study`
- `POST /api/research/event-study/samples`

通用请求示例：

```json
{
  "start_date": "2025-09-01",
  "end_date": "2026-09-01",
  "filters": [
    {"factor_id": "turnover_rate", "min_value": 5, "max_value": 15},
    {"factor_id": "popularity_rank", "min_value": 1, "max_value": 30},
    {"factor_id": "change_pct", "min_value": 2, "max_value": 6}
  ],
  "horizons": [1, 3, 5, 10, 20]
}
```

## 部署

Vercel 当前只适合作为 Web demo：Serverless 本地文件系统不是持久盘，因此 DuckDB 使用 `/tmp`，真实同步被禁用。

正式版使用腾讯云 VPS / Docker 运行，并挂载持久 DuckDB volume。`main` 推送后 GitHub Actions 会构建并推送 GHCR 镜像。

**不要把 Vercel 临时 DuckDB 当成真实历史数据库。**

## 开发原则

- 统计引擎只消费规范化历史数据，不直接依赖具体上游 API；
- 新数据源通过 provider 适配，不复制第二套统计逻辑；
- 新时序指标优先进入 `factor_values`，再注册到 Factor Registry；
- 不猜金融数据单位和缺失值；无法可靠计算时保持为空；
- 任何后续收益必须只使用事件发生之后的数据，不能产生未来数据泄露；
- 历史时点指标必须使用历史时点口径，不能拿当前状态倒推过去。

## 下一阶段

1. 增加市值、成交额、量比、涨停/ST/新股状态等因子；
2. 接入资金流、龙虎榜、板块热度等扩展时序信号；
3. 增加逐年/逐月稳定性、收益分位数、最大回撤等统计；
4. 保存与对比研究条件组合；
5. 增加自然语言 Research Agent：自然语言 -> 结构化条件 -> Event Study -> 结果解释；
6. 后续再接完整策略回测与因子 IC/IR 研究，不在 Alpha Lab 内重复造多个数据引擎。
