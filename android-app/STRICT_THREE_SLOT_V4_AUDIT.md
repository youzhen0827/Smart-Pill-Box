# Android 早／中／晚三格嚴格檢查（v4）

- `SlotLabels.SLOT_COUNT = 3`。
- `activity_main.xml` 只有 tvSlot1、tvSlot2、tvSlot3，文字為早、中、晚。
- 新增提醒 / 固定排程選擇器只顯示早、中、晚。
- 感測事件 Spinner 只顯示早、中、晚，送出的 slot 只能為 1~3。
- 舊 App 偏好若曾保存 slot 4~7，啟動時會 coerce 到 1~3。
- API 回傳若出現非法 slot 4~7，App 不會顯示該筆格位資料。
- 固定排程會送出與 slot 對應的 period：1=morning、2=noon、3=evening。
- 測試連線會驗證 Django health：slot_count=3、labels=早/中/晚、layout=early-noon-evening-3-slot。
- 星期 1~7 是週一到週日，不是藥盒格數。
