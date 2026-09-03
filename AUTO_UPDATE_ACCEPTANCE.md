# 自动更新验收记录

## GitHub

- Owner：Ashui-Cx330
- Repository：ai-market-assistant
- Remote：https://github.com/Ashui-Cx330/ai-market-assistant.git
- 当前发布阶段：v1.0.0 构建及发布前检查已通过，等待上传 Release。

## 客户端

- 当前正式构建：v1.0.0
- 安装目录：`%LOCALAPPDATA%\Programs\AI行情助手`
- 用户数据：`%APPDATA%\AI行情助手`

## v1.0.0 发布文件

- `AI-Market-Assistant-Setup-v1.0.0.exe`
- `AI-Market-Assistant-Setup-v1.0.0.exe.blockmap`
- `latest.yml`

三个文件由同一次 electron-builder 构建生成。发布前检查已验证版本、路径、SHA512、安装包大小、blockmap 内部映射大小及内置 GitHub provider。

## 已通过

- 前端构建、真实联网后端测试、Electron 端到端测试
- 启动健康检查
- GitHub 网络失败保护
- 固定安装目录和独立用户数据
- 更新失败状态持久化
- 健康超时恢复旧版文件
- 问题版本阻止循环升级

v1.0.0 → v1.0.1 的真实 GitHub 下载、安装、重启和数据保留结果将在第二个 Release 发布后写入。
