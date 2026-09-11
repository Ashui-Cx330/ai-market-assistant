# 数据源审计

| 领域 | 主源 | 备用/降级 | 真实性与限制 |
| --- | --- | --- | --- |
| A股 | 东方财富公开行情/历史行情 | 腾讯证券；部分周期新浪 | 真实公开数据，非授权逐笔；休市时不会伪造跳动 |
| 美股 | Yahoo Finance public chart API | 最新真实 K线可作为明确的 delayed quote | 免费公开源可能延迟或限流 |
| Crypto | OKX | Coinbase；通用报价层也尝试 Binance | 交易所公开数据；Binance 在本机网络返回 HTTP 451 |
| 证券字典 | 本地 SQLite Registry | 后台刷新 Binance exchangeInfo、OKX instruments、东方财富证券列表 | 搜索和行情解耦；当前网络 OKX 成功，Binance/Eastmoney 状态如实标为 Degraded |
| 新闻 | 东方财富公告、CoinDesk、Cointelegraph、CNBC、BBC、Yahoo 等 | SQLite 已采集缓存 | 缓存明确，不生成替代新闻 |
| 用户数据 | SQLite | 更新前备份/迁移 | 位于 `%APPDATA%\AI行情助手`，不在安装目录 |

可靠性优先级不是固定“某网站永远最好”，而是按市场选择主源并保留独立 fallback。当前本机最稳定的 Crypto 元数据源是 OKX；Binance 因地区/网络 HTTP 451 不可用。A股/美股 Provider 可发生断连，产品必须显示 Source、Updated At、Realtime/Delayed 和错误，而不是填随机值。

