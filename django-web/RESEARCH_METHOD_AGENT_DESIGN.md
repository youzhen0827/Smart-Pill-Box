# 研究方法與 Agent 設計

## 研究問題

1. 以排程與開盒感測事件，能否形成可追溯的服藥狀態判定流程？
2. 當長輩未在指定時間開盒時，Agent 能否分階段介入，而不是只靠單次鬧鐘？
3. 醫療衛教 QA 能否只使用可追溯的真實資料集，降低無依據回答？
4. 本機 STT/TTS 是否能在不使用付費 API 的條件下完成語音互動原型？

## 系統變項與可量化指標

| 類型 | 指標 |
|---|---|
| 排程遵從性 | 準時開盒率、超過 grace_minutes 比率、漏服率 |
| Agent 成效 | initial_reminder 後開盒率、sensor_missing 後開盒率、平均介入次數 |
| 感測可靠度 | heartbeat 可用率、事件延遲、未配對 opened 事件比例 |
| QA 可追溯性 | 有證據回答率、openFDA 自動同步成功率、evidence 文件數 |
| 語音可用性 | STT 成功率、端到端回應時間、TTS 完整播放率 |

## 狀態追蹤 Agent

### 輸入

- `MedicationSchedule`：星期、時間、格位、裝置、等待與漏服門檻
- `SensorEvent`：opened、closed、heartbeat
- 系統時間

### 狀態

| 狀態 | 定義 |
|---|---|
| pending | 尚未到預定時間 |
| waiting_sensor | 已到時，等待指定裝置與格位的 opened |
| intervened | 超過等待門檻，已建立未開盒介入 |
| taken | opened 已配對，或經 Android／網頁確認 |
| missed | 超過漏服門檻仍無 opened |

### 可追溯輸出

- `Reminder`：一次性任務與最終狀態
- `MedicationLog`：排程層級結果
- `AgentIntervention`：到時提醒、未開盒、漏服升級
- `SensorEvent.matched_reminder`：感測事件與任務配對關係

## QA 醫療衛教 Agent

### 資料取得

- openFDA NDC Directory API
- openFDA Drug Label API
- 使用者自行從 Kaggle 下載且附來源頁面網址的 CSV

### RAG 流程

1. 中文顯示名可透過 `Drug.generic_name` 對應 FDA 英文學名。
2. 依問題判斷需要的區段：用途、適應症、副作用、警告、交互作用。
3. 在本機 `DrugKnowledgeDocument` 以藥名、NDC、詞彙重疊與來源類型評分。
4. 選出有限數量證據段落。
5. 只截短與編排證據；選用自架 LibreTranslate 翻譯，不用生成式模型補寫事實。
6. 回傳 evidence ID、source_id、source_url 與檢索區段。

### 無資料策略

- 不建立假藥物內容。
- `auto_sync=true` 時以英文學名／品牌／NDC 查 openFDA。
- 仍找不到時明確回覆「知識庫沒有資料」，要求先同步或匯入真實 CSV。

## 語音 Agent

```text
Raspberry Pi 麥克風
       ↓
faster-whisper（本機 STT）
       ↓
Django QA API
       ↓
FDA/Kaggle RAG
       ↓
Piper 或 eSpeak NG（本機 TTS）
```

預設以淺顯繁體中文朗讀。真正台語 TTS 可透過合法授權的本機 Piper 台語模型替換，不需更改 Django API。

## 實驗設計建議

- 受測情境：準時開盒、延遲開盒、完全未開盒、錯格開盒、裝置離線。
- 每種情境至少重複多次，記錄 API 時間、感測時間、Agent 狀態轉換與介入時間。
- QA 測試以事先選定的真實藥物為題，人工核對 evidence 是否真的支持回答。
- 將網路中斷、openFDA 404、翻譯容器停機列入失敗情境，確認系統不會改用假資料。
