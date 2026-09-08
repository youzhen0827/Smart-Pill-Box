# 早／中／晚三格修改確認

本 Android 版本已和 Django 三格 API 對齊：

- `SlotLabels.SLOT_COUNT = 3`
- 今日首頁只有 `tvSlot1`、`tvSlot2`、`tvSlot3`
- 新增單次任務、固定排程、感測器測試都只顯示「早／中／晚」
- App 傳給 Django 的 JSON 仍使用 `slot=1/2/3`
- App 讀取 Django 回傳的 `slot_label`，因此列表會顯示早／中／晚
- 感測器測試 Spinner 由 `SlotLabels.optionLabels()` 產生，只會有三個選項

建議連線設定：Android 模擬器使用 `http://10.0.2.2:8000/api/v1/`；實體手機改填電腦區網 IP。
