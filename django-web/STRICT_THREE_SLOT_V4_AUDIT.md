# 早／中／晚三格嚴格檢查（v4）

- 唯一格位：1=早、2=中、3=晚。
- Dashboard 右側只由 `slot_payload()` 產生三張卡片，且只查詢 slot 1~3 的感測事件。
- Web 表單 slot choices 只有早／中／晚；排程 period 由 slot 自動推導，不再讓使用者建立互相矛盾的時段。
- API create/update 對 slot 4~7 回 400。
- API health 明確回傳 slot_count=3、slots=早/中/晚、pillbox_layout=early-noon-evening-3-slot、ui_revision=4。
- Reminder / SensorEvent 新增資料庫 constraint，只允許 null 或 1~3。
- migration 0013 再次把舊資料 slot >3 正規化為 3，並加入 constraint。
- Raspberry Pi 預設 SLOT_PINS=1:5,2:6,3:13。
- Android 只有 3 個首頁格位 View，Spinner 只有 早/中/晚，建立單次任務、週期排程與感測事件只送 1~3。
- Android 週期排程同時送 period=morning/noon/evening，與 slot 1/2/3 對齊。
- Android 測試連線會驗證後端三格 health contract，避免誤連舊七格 Django。

注意：星期（weekdays）仍然是 1~7，這是週一到週日，不是藥盒格位。歷史 migration 0007 的 7 格 schema 是舊版遷移歷史，現行 schema 由 0011~0013 收斂為三格。
