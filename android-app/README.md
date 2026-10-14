# v2.1_Android_8_aiagent — 智慧藥盒 Android App

本版本保留智慧藥盒原有架構，升級為第 8 版 Hybrid AI Agent：

- 深藍色頂部列 `#142B7A`
- 淺灰頁面背景 `#EEF1F5`
- 白色圓角卡片
- 今日排程／已服藥／待確認／漏服統計卡
- 七個分頁：臨時服藥、服藥狀況、吃藥時間、提醒追蹤、語音問藥、藥物資料、手機姓名設定
- 綠／橘／紅狀態色與早／中／晚三格藥盒狀態

## 已實作功能

### Django API 串接

App 直接使用 `HttpURLConnection` 呼叫 `smart_medicine_box_Django_re_1`：

- `GET /api/v1/health/`
- `GET /api/v1/reminders/`
- `POST /api/v1/reminders/`
- `POST /api/v1/reminders/<id>/taken/`
- `POST /api/v1/reminders/<id>/delete/`
- `POST /api/v1/sensors/events/`
- `POST /api/v1/qa/ask/`

所有受保護 API 會送出 `X-Device-Token`。

### 今日提醒

Django Agent 產生的個人化提醒會同步到 Android。若 Django 暫時離線或只提供安全備援，APP 會直接呼叫手機內的 MiniCPM5-2B，依輸入姓名、藥名、劑量、時間與逾時狀況重新產生自然提醒。通知標題顯示「訓練 AI」代表內容確實由 Django 或手機內的訓練模型生成；兩端模型都無法使用或內容未通過安全檢查時，才顯示「安全提醒」。

- 讀取指定長輩當日 Django 紀錄
- 顯示狀態統計與早／中／晚三格排程狀態
- 確認已服藥
- 補登漏服紀錄為已服藥
- 刪除 Django 紀錄
- 顯示 Agent 狀態與提醒次數
- 顯示 MiniCPM5-2B 或固定安全規則的判斷來源、信心、依據與合理性檢查
- 背景每 15 分鐘同步 Agent，並依每筆原有時間排定到時、再次提醒與漏服系統通知
- APP 關閉畫面後仍可收到提醒；確認已服藥會取消該筆後續通知

### 新增任務

新增單次提醒時會把姓名、年齡、藥品、日期時間、劑量、提醒內容、早／中／晚時段與裝置 ID 寫入 Django。

固定、週期性的服藥排程應在 Django 網站的「排程管理」建立，由後端 Agent 定時展開成每日任務。

### 獨立語音問藥 AI Agent

- 手機語音輸入：Android `RecognizerIntent`
- APP 內建台灣食藥署未註銷藥品繁體中文索引，不需開啟網頁即可查用途與用法
- 需要副作用、警告或交互作用時，由 APP 直接查 openFDA，不經 Django
- 已訓練的 MiniCPM5-2B 直接在手機內整理答案與翻譯繁體中文，不依賴網頁或 Ollama
- 模型不放入 APK；先在儲存庫根目錄執行 `models\assemble_trained_model.ps1`，安裝並開啟一次 APP 後，再以 USB 執行 `install_trained_model.ps1`，之後可完全離線推論與產生提醒

Android 13 以上第一次開啟時請允許通知；Android 12 以上若未允許精準鬧鐘，系統仍會提醒，但可能依省電設定稍微延後。
- Agent 先判斷問題，再檢查藥名、回答範圍、資料來源、中文、長度與安全性
- 檢查通過才顯示回答，並顯示分數與可追溯資料來源
- 手機 TTS 朗讀繁體中文；選擇台語偏好時會先嘗試 `nan-TW`，裝置未安裝台語語音則回退為繁體中文
- Raspberry Pi 版本另使用本機 `faster-whisper` 與 Piper／eSpeak NG，不需付費 STT/TTS API

## 連線設定

### Android 模擬器

```text
http://10.0.2.2:8000/api/v1/
```

### 實體手機

手機與 Django 電腦需在同一個區域網路。將網址改為電腦的 IPv4，例如：

```text
http://192.168.1.50:8000/api/v1/
```

Django 必須監聽外部介面：

```bash
python manage.py runserver 0.0.0.0:8000
```

預設開發 token：

```text
smartpill-dev-token
```

正式部署請在 Django `.env` 修改 `DEVICE_API_TOKEN`，並在 App 連線設定輸入相同值。

## 編譯

使用 Android Studio 開啟本資料夾並等待 Gradle 同步，然後執行 `app`。

專案設定：

- namespace / applicationId：`com.example.smartpillbox`
- Android Gradle Plugin 9.0.1（內建 Kotlin）
- Gradle 9.1.0
- JDK 17
- compileSdk 36
- targetSdk 36
- minSdk 21
- versionName 2.1.8

## 重要限制

- 手機語音辨識能否離線取決於裝置已安裝的語音服務與語言包。
- 台語 TTS 能否使用取決於手機 TTS 引擎是否提供 `nan-TW` 聲音。
- QA 回答是衛教研究資訊，不是診斷或個別醫療建議；不得自行停藥、加量或換藥。
- App 的「感測器 API 測試」是手動測試入口。正式硬體資料由照片中的 ESP32 經 USB 橋接器上報。
