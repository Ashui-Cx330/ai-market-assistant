# 性能审计（v1.9.1 清单复验，当前基线 v1.10.3）

审计日期：2026-09-11。所有数字来自本机 Release 安装版或同一提交的本地生产构建；未用假接口替换公网请求。

## 结论

截图中的长时间 Skeleton 主要不是 Vue 渲染，而是搜索/Scanner 把公网 Provider 等待放在首屏链路。修复前已安装版 `/api/health` 为 10ms、Crypto 热门币搜索 22ms，但 A股代码/名称搜索为 1710/1765ms，美股搜索为 2107ms。搜索元数据与行情请求耦合是 P0。

本轮改成持久化本地 Symbol Registry 先返回，Binance、OKX、东方财富列表只在后台刷新。修复后同一台电脑冷启动后的要求样例为：600519 8ms、贵州茅台 3ms、000001 2ms、300750 4ms、AAPL 3ms、NVDA 68ms、TSLA 8ms；平均 13.7ms。搜索阶段不请求报价或 K线。

## 页面链路

| 项目 | 当前实现 | 复验结论 |
| --- | --- | --- |
| 导航 | 先更新路由和页面状态，下一个 animation frame 记录 `navigation_skeleton`，再加载数据 | Skeleton 目标 <300ms；浏览器 Performance API 可复测 |
| API | `Server-Timing`、`X-Request-ID`、最近 500 次 `/api/performance/recent` | 可定位真实 API 总耗时 |
| 搜索 | 120ms 防抖、旧请求 AbortController 取消、本地 SQLite Registry | P0 已修复 |
| 详情 | quote + candles 并发，统一 workspace 避免组件重复抓取 | 任何 quote 失败可用最后一根真实 K线显式降级 |
| Scanner | 3 个 Provider 并发槽、18 秒总预算、60/120 秒结果缓存 | 不会无限 Skeleton；慢源会作为错误返回 |
| 图表 | ECharts/K线与回测图按页面动态导入 | 首屏主 JS 197.50kB；ECharts 1126.64kB 不进入初始主包 |

## P0 / P1 / P2

- P0（已修）：搜索先等待 Yahoo/东方财富；同一详情重复 quote/Kline；无总超时的跨市场 Scanner。
- P1（已控）：免费 Provider 在当前网络可能 451、断连或 10–30 秒超时。真实慢请求中 Scanner/新闻/详情历史数据仍可能最慢，UI 会显示局部错误及真实延迟。
- P2：ECharts 懒加载块仍约 1.13MB，但仅进入图表页；继续拆它对首次首页帮助很小。

数据库 CRUD 为本地 SQLite，健康检查通常约 2–10ms。模型首次训练是 CPU 工作且按数据指纹缓存；已训练模型从磁盘载入。LLM 不是结构化预测的阻塞依赖，当前 Copilot 是确定性工具路由。

真实十标的冷启动矩阵进一步测得：完整 AI 首次训练/验证约 50 秒到 4 分钟（并发训练会争用 CPU，不能宣传为 <1500ms）。因此界面立即显示已加载详情中的真实结构信号，完整概率模型继续运行；二者有明确标签，结构评分不冒充预测概率。后续相同数据指纹可载入磁盘模型，但外部宏观、新闻和多周期数据仍会产生网络等待。
