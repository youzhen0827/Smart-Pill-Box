param(
    [string]$Device = "",
    [string]$ModelPath = "D:\Project Revision\models\MiniCPM5-2B_smartpill_trained_int8.litertlm",
    [string]$ApkPath = ""
)

$ErrorActionPreference = "Stop"
$packageName = "com.example.smartpillbox.lora"
$modelName = "MiniCPM5-2B_smartpill_trained_int8.litertlm"
$expectedBytes = 2546936640
$expectedSha256 = "646A5D14AA9D717602B798EFB09672F902547F3C9E2F1739372E50AA1160E92D"

$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ApkPath) {
    $packagedApk = Join-Path $PSScriptRoot "SmartPillBox-LoRA-Trained-INT8.apk"
    if (Test-Path -LiteralPath $packagedApk) {
        $ApkPath = $packagedApk
    } else {
        $ApkPath = Join-Path $projectRoot "app\build\outputs\apk\lora\debug\app-lora-debug.apk"
    }
}

$adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path -LiteralPath $adb)) {
    $adb = (Get-Command adb -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $ApkPath)) {
    throw "找不到 LoRA APK：$ApkPath"
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "找不到 LoRA 模型：$ModelPath"
}

$model = Get-Item -LiteralPath $ModelPath
if ($model.Length -ne $expectedBytes) {
    throw "LoRA 模型大小不正確：$($model.Length) bytes"
}
if ((Get-FileHash -LiteralPath $ModelPath -Algorithm SHA256).Hash -ne $expectedSha256) {
    throw "LoRA 模型 SHA-256 驗證失敗。"
}

$adbArgs = @()
if ($Device) {
    $adbArgs += @("-s", $Device)
}

Write-Host "正在安裝 LoRA 測試版 APK..." -ForegroundColor Cyan
& $adb @adbArgs install -r $ApkPath
if ($LASTEXITCODE -ne 0) { throw "LoRA APK 安裝失敗。" }

$remoteDir = "/sdcard/Android/data/$packageName/files/models"
$remotePath = "$remoteDir/$modelName"
& $adb @adbArgs shell mkdir -p $remoteDir
if ($LASTEXITCODE -ne 0) { throw "無法建立手機模型資料夾。" }

Write-Host "正在傳送約 2.55 GB LoRA 模型，請保持 USB 連線..." -ForegroundColor Cyan
& $adb @adbArgs push $ModelPath $remotePath
if ($LASTEXITCODE -ne 0) { throw "LoRA 模型傳送失敗。" }

$remoteBytes = (& $adb @adbArgs shell stat -c %s $remotePath).Trim()
if ($remoteBytes -ne "$expectedBytes") {
    throw "手機模型大小不正確：$remoteBytes bytes"
}

& $adb @adbArgs shell am force-stop $packageName
& $adb @adbArgs shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "LoRA 測試版與訓練模型安裝完成。" -ForegroundColor Green
