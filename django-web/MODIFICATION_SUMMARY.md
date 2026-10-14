# 修改摘要：MiniCPM5-2B＋ESP32 USB 第 8 版

- 回答 Agent 會判斷問題、選擇資料、產生精簡回答，再獨立核對藥名、問題範圍、來源、中文、長度與安全性。
- 合理性檢查會顯示 0～100 分；關鍵檢查失敗時不顯示可能錯誤的醫療內容。
- 新增台灣食藥署未註銷藥品許可證，保留繁體中文品名、適應症、用法用量、成分與來源。

- AI Agent 追蹤加入日期、照護對象篩選與各階段數量。
- 語音衛教依問題分成用途、副作用、服用方法、交互作用與警告。
- Agent 只回答有來源的內容，並提供長輩可理解的下一步。
- Android 與 Django 以 `ui_revision=8`、`hardware_transport=usb_serial` 驗證連線版本。
- 加入 ESP32 USB 韌體與電腦橋接器；實體左／中／右固定為早／中／晚。
- 硬體腳位為幹簧管 18／19／21、LED 13／14／27、PIR 22、蜂鳴器 26。

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

第 8 版使用程式內 `MiniCPM5-2B` 混合 Agent，並整合照片中的 ESP32 USB 藥盒；不使用 Ollama。
Agent 會主動建立到時提醒、再次提醒與漏服通知，時間沿用原排程設定。

輸出檔：`8_aiagent_smart_medicine_box_Django_re.zip`
