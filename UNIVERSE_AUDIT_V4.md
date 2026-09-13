# Universe Audit V4

生成自 `C:\Users\汪文斌\AppData\Roaming\AI行情助手\database\trading_ai.db`；生成时间 `2026-09-13T11:19:01.253527+00:00`。不使用 Mock，不删除失败样本。

持久化 Universe：`[{"market": "CRYPTO", "member_count": 100, "universe_version": "CRYPTO-2026-09-13-8f4529ce07234ee6", "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"}, {"market": "US", "member_count": 500, "universe_version": "US-2026-09-13-0cbf0807fecd7bb5", "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"}, {"market": "CN", "member_count": 5, "universe_version": "CN-2026-09-13-d581b4a58f5a7fc6", "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"}]`。最低门槛 CN=300、US=100、CRYPTO=50。

仅当前成员列表无法解决退市/IPO 历史归属，因此 survivorship 状态必须保持 `UNRESOLVED`。未达到规模时不得声称横截面验收完成。
