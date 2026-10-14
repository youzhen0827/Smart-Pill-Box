# 智慧藥盒訓練模型

本資料夾保存經 2,000 筆智慧藥盒情境資料 LoRA 微調、合併並轉換為 INT8 LiteRT-LM 的 `MiniCPM5-2B` 模型。

完整模型大小為 2,546,936,640 bytes，超過一般 GitHub 單檔限制，因此拆成四個 Git LFS 分割檔。複製專案後先執行：

```powershell
git lfs pull
.\models\assemble_trained_model.ps1
```

腳本會產生：

```text
models\MiniCPM5-2B_smartpill_trained_int8.litertlm
```

並驗證 SHA-256：

```text
646A5D14AA9D717602B798EFB09672F902547F3C9E2F1739372E50AA1160E92D
```

Android 可再執行 `android-app\install_trained_model.ps1`，把同一個模型安裝到 APP 專屬儲存空間。Django 則執行 `django-web\setup_minicpm.ps1`。
