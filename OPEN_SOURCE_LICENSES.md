# 开源软件与许可证记录

核查日期：2026-09-03。完整传递依赖及许可证文本以安装包内各依赖的许可文件为准。

| 项目 | 使用版本 | License | 用途 |
|---|---:|---|---|
| Vue | 3.5.x | MIT | Web 前端 |
| Element Plus | 2.10.x | MIT | UI 组件 |
| Apache ECharts | 6.x | Apache-2.0 | K 线与净值图 |
| FastAPI | 0.116.x | MIT | HTTP API |
| Uvicorn | 0.35.x | BSD-3-Clause | 本地服务 |
| HTTPX | 0.28.x | BSD-3-Clause | 行情 HTTP 客户端 |
| NumPy | 2.5.2 | BSD-3-Clause | 数值计算 |
| pandas | 2.3.3 | BSD-3-Clause | 时间序列与指标计算 |
| scikit-learn | 1.9.0 | BSD-3-Clause | RandomForest 预测模型 |
| Electron | 44.1.1 | MIT | Windows 桌面外壳 |
| electron-builder | 26.15.3 | MIT | NSIS 安装包构建 |
| electron-updater | 6.8.9 | MIT | 版本检查与更新安装 |
| PyInstaller | 6.22.2 | GPL-2.0-or-later，含 bootloader 例外 | Python 后端封装 |
| Playwright | 1.62.1 | Apache-2.0 | 仅开发阶段桌面端自动化测试 |

此前调研过 Freqtrade/FreqAI、Microsoft Qlib 和 FinRL，但当前 v0.3.0 未复制、链接或打包这些项目的代码。

## V7 新闻情报调研（未打包、未复制）

| 项目 | License 核查 | 处理决定 |
|---|---|---|
| ProsusAI/finBERT | Apache-2.0 | 仅参考金融情感三分类设计；旧依赖且主要面向英文，本版未引入 |
| zhaymn/StockIntel | MIT | 仅参考校准门、拒绝预测、PIT 验证与新闻/价格影响分离 |
| PandOvo/FinNews-Sentiment2Signal | GitHub API 未识别许可证 | 不复制代码或合成示例数据，仅参考 IC/时间对齐研究方向 |
| overlandflight/PokieTicker_A-main | GitHub API 未识别许可证 | 不复制代码 |
| valuesimplex/FinBERT | MIT | 中文金融 NLP 候选，当前未引入模型权重或代码 |
