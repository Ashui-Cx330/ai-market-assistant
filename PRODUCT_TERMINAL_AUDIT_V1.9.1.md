# 产品终端验收（v1.9.1 清单，续版复验）

当前代码版本高于任务原始基线 v1.8.0，本轮不降级版本。既有 Market Intelligence、Market Scanner、Watchlist、AI Screener、AI Outlook、Model Lab、Event Impact、Strategy/Backtest、Paper Trading、Copilot、Data Health、Realtime 和 Updater 全部保留。

UI 是紧凑深色金融终端：左侧按 MARKET / AI / STRATEGY / TRADING / SYSTEM 分组；首页用于 5 秒市场概览；资产详情以 K线为视觉中心；预测显示概率、证据、模型状态和限制；新闻名称为 Event Impact；模拟交易有持仓、K线、订单票据和确认弹窗。关键页面提供 Skeleton、Empty、Error/Retry；数据源失败不导致整页空白。

AI Copilot 是系统工具路由层，不会在未取得行情/指标/新闻时自行编造答案。AI Screener 对真实取得的资产行做筛选，资产池范围会披露。Paper Trading 使用真实当前公开报价、持久化账户/订单/持仓，但仅为模拟交易。

## 仍受外部条件限制

- Binance 在当前网络返回 HTTP 451，自动使用 OKX 元数据/行情链路；这不是代码能够绕过的地区服务限制。
- FinBERT 未安装，新闻标注明确为 `financial-event-rules-v2` 规则引擎，不冒充模型准确率。
- 免费公开行情不是交易所授权逐笔数据；美股可能延迟。
- Windows 安装包尚无用户主体的 Authenticode 证书，可能显示“未知发布者”。
- 预测和新闻影响尚无足够长期 OOS 样本证明稳定交易优势。

生产代码未发现 `Math.random()` 行情、随机新闻、随机预测或随机回测收益。所有不可用状态必须为空值、`INSUFFICIENT_DATA`、`DEGRADED` 或错误，不以演示数字补齐。

## 2026-09-11 最终复验

- Python 全量：69 passed；随后针对搜索、模型文件并发、终端和真实后端链路再跑 12 passed。
- 前端 TypeScript + Vite production build：PASS；首屏主 JS 198.00kB，图表库保持异步块。
- 十标的真实矩阵：10 assets × 搜索/报价/K线指标/新闻/AI = 50 检查。首轮 43/50、缓存/网络重试 46/50；将两轮及修复后的定向复验合并后，每项能力至少成功一次。瞬时失败原样记录为 Provider 断连/451/超时，不能解释为每次网络都保证成功。
- `000001` 与 `300750` 修复后分别用腾讯真实日线备用源完成三周期 `PerformanceWeightedEnsemble` 预测，约 49.96 秒和 63.46 秒。
- Packaged Electron E2E：路由、Scanner、搜索、详情 K线、Tooltip、Model Lab、策略、模拟下单确认、Copilot、新闻、Data Health 全部 PASS。
- NSIS、`latest.yml`、`.blockmap`、SHA512：PASS。安装包 Authenticode 状态仍为 `NotSigned`，未伪称已有可信发布者证书。
