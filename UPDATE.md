# AI行情助手自动更新与发布

当前代码版本：**v1.3.0**。更新仓库：`Ashui-Cx330/ai-market-assistant`。只有在本地构建通过并向 GitHub Release 上传安装包、`.blockmap` 和 `latest.yml` 后，才会成为用户可检测的正式更新；未发布版本不会伪装成线上更新。

## 当前实现

- Electron 使用 `electron-updater`，启动后异步检查更新；设置页也提供“检查更新”。
- GitHub Publisher 从构建环境变量 `GH_OWNER`、`GH_REPO` 读取，不在源码、前端或安装包中保存 Token。
- 配置真实仓库后，electron-builder 同一次构建生成安装包、`.blockmap`、`latest.yml` 和客户端内置的 `app-update.yml`。
- 下载由 electron-updater 校验；下载失败不会修改旧程序。
- 安装前将当前稳定程序完整备份至 `%APPDATA%\AI行情助手\update-backups`，并启动独立的隐藏回滚守护。
- 新版启动后验证 Electron、Renderer、本地后端、SQLite、核心健康 API 和首页。成功后确认新版并清理备份。
- 超时或启动失败会恢复旧程序、重新启动旧版、记录 `update.log`，并把失败版本加入阻止列表。
- 更新状态持久化在 `%APPDATA%\AI行情助手\update-state.json`。
- 用户数据库与程序分离，位于 `%APPDATA%\AI行情助手\database`。

## 一键发布

GitHub CLI 登录一次后，直接运行：

```powershell
.\release.bat
```

脚本会自动读取当前 GitHub 用户和 origin 仓库。不指定版本时自动增加 PATCH 版本，并依次统一版本号、构建、校验三个发布资产、提交代码、推送 GitHub、创建 Release、复核线上资产。任何检查失败都会停止并指出失败步骤。

`scripts\release-check.ps1` 验证版本、Tag、安装包、latest.yml 必需字段、SHA512、blockmap 内部块总大小、内置 updater 仓库、GitHub Release、桌面快捷方式和数据目录分离。

GitHub CLI 使用系统凭据库登录。Token 仅由 GitHub CLI/运行环境使用，不会进入源码、客户端或 Release。正式发布资产统一采用 ASCII 文件名，避免 GitHub 更新元数据与实际资产名称不一致。
