# v2.1_Android_6_workflow — 智慧藥盒 Android App

本版本已將原本的記帳／睡眠專案殘留內容移除，介面改為 `django_hw2-prj_B2209221` 參考專案的視覺語言：

- 深藍色頂部列 `#142B7A`
- 淺灰頁面背景 `#EEF1F5`
- 白色圓角卡片
- 今日排程／已服藥／待確認／漏服統計卡
- TabHost 分頁：今日任務、新增臨時服藥、固定排程、Agent 追蹤、語音衛教、連線設定
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

- 讀取指定長輩當日 Django 紀錄
- 顯示狀態統計與早／中／晚三格排程狀態
- 確認已服藥
- 補登漏服紀錄為已服藥
- 刪除 Django 紀錄
- 顯示 Agent 狀態與提醒次數

### 新增任務

新增單次提醒時會把姓名、年齡、藥品、日期時間、劑量、提醒內容、早／中／晚時段與裝置 ID 寫入 Django。

固定、週期性的服藥排程應在 Django 網站的「排程管理」建立，由後端 Agent 定時展開成每日任務。

### QA 醫療衛教 Agent

- 手機語音輸入：Android `RecognizerIntent`
- 後端 RAG：只檢索 Django 中已匯入的 FDA NDC／FDA Drug Label 或真實 Kaggle CSV
- 本機沒有證據時可要求 Django 即時同步 openFDA
- 顯示回答與可追溯資料來源
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
- versionName 2.1.6

## 重要限制

- 手機語音辨識能否離線取決於裝置已安裝的語音服務與語言包。
- 台語 TTS 能否使用取決於手機 TTS 引擎是否提供 `nan-TW` 聲音。
- QA 回答是衛教研究資訊，不是診斷或個別醫療建議；不得自行停藥、加量或換藥。
- App 的「感測器 API 測試」是手動測試入口。正式硬體資料由 ESP32 或 Raspberry Pi GPIO 程式上報。
