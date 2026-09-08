# 修改摘要：流程化介面 v6

- AI Agent 追蹤加入日期、照護對象篩選與各階段數量。
- 語音衛教依問題分成用途、副作用、服用方法、交互作用與警告。
- Agent 只回答有來源的內容，並提供長輩可理解的下一步。
- Android 與 Django 以 `ui_revision=6` 驗證連線版本。

- 保留原本七個頁面、排版骨架、資料庫與三格藥盒 API。
- 將排程、今日任務、Agent 追蹤與服藥結果的名稱和責任分開。
- 「AI Agent／語音」改為「AI Agent 追蹤」，語音衛教維持獨立頁面。
- 臨時服藥改為選擇照護對象，建立時不再預先選擇服藥結果。
- 星期改為複選，裝置與 Agent 門檻收進進階設定。
- 五種參考色分開使用，不使用顏色漸層。

## 保留的 v4 三格規格

- Django/Web/Android/Raspberry Pi 全部統一為 3 格：1=早、2=中、3=晚。
- 監控中心右側固定只顯示早、中、晚 3 張感測卡。
- Web 與 API 不接受 slot 4～7；Reminder / SensorEvent 亦加入資料庫 constraint。
- 新 migration `0013_strict_three_slot_constraints.py` 會再次正規化舊格位資料並加限制。
- 固定排程的 period 由 slot 自動推導：早=morning、中=noon、晚=evening。
- Android 會驗證 Django `/api/v1/health/` 是否確實為三格版，避免誤連舊後端。
- Raspberry Pi 預設腳位為 `1:5,2:6,3:13`。

輸出檔：`6_workflow_smart_medicine_box_Django_re.zip`
