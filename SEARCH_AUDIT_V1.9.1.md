# 搜索引擎审计

## 架构

Search API 只确认证券身份；Quote、Kline、News 在选择后独立加载。持久化 Registry 字段包括 symbol、asset_type、market、exchange、name、aliases、base/quote asset、status、source 和 updated_at。内置可验证核心索引保证离线可搜，启动后后台增量写入 Binance、OKX 和东方财富列表；某一源失败不阻塞搜索。

前端有 120ms 输入防抖、AbortController 取消旧查询、并行 stock/crypto 本地查询、Exact/Symbol/Name 排序，以及 ↑/↓/Enter/Esc 键盘操作。

## 本机复验

| 查询 | 结果 | 耗时 |
| --- | --- | ---: |
| 600519 / 贵州茅台 | 600519 贵州茅台 | 8ms / 3ms |
| 000001 / pingan | 000001 平安银行 | 2ms / 单元测试 PASS |
| 300750 | 宁德时代 | 4ms |
| AAPL / NVDA / TSLA | 正确美股 | 3ms / 68ms / 8ms |
| BTCUSDT / ETHUSDT / SOLUSDT / BNBUSDT | 正确 USDT 交易对 | 4–19ms |

本轮同时修复 `000001` 身份冲突：无后缀的股票搜索按 `000001.SZ`（平安银行），上证指数必须用 `000001.SH`；两者缓存键也已分离，避免名称与价格串线。

