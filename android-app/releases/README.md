# Android APK 下載

兩個版本可安裝在同一支手機上，套件名稱不同，不會互相覆蓋。

## 官方 INT4 版

- APK：`official/SmartPillBox-Official-INT4-v2.1.12.apk`
- 套件：`com.example.smartpillbox.official`
- 模型：MiniCPM5-2B 官方 INT4，約 1.55 GB
- 首次開啟：連接 Wi-Fi 時可由 App 自動下載官方模型
- 用途：作為未微調模型的比較基準

## LoRA 訓練 INT8 版

- APK：`lora/SmartPillBox-LoRA-Trained-INT8-v2.1.12.apk`
- 套件：`com.example.smartpillbox.lora`
- 模型：智慧藥盒 LoRA 訓練 INT8，約 2.55 GB
- 模型安裝：模型本體未包在 APK，需使用 USB 或無線 ADB 傳入手機
- 用途：依姓名、藥物、劑量、時間及逾時狀態產生較自然的服藥提醒

## 本版提醒模型流程

兩個版本會把同一組提醒資料送進各自模型，方便公平比較：

- 姓名
- 藥物
- 劑量
- 預定時間
- 服用備註
- 目前狀況

通知標題會分別顯示「官方模型」或「LoRA 模型」。模型輸出未通過安全檢查時，App 會改用固定安全提醒。

> APK 透過 Git LFS 儲存。GitHub 頁面若只顯示 LFS 指標，請使用 Git LFS clone/pull，或從專案發布頁下載。
