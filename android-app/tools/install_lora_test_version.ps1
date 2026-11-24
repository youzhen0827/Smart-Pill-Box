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
    throw "LoRA APK not found: $ApkPath"
}
if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "LoRA model not found: $ModelPath"
}

$model = Get-Item -LiteralPath $ModelPath
if ($model.Length -ne $expectedBytes) {
    throw "Unexpected LoRA model size: $($model.Length) bytes"
}
if ((Get-FileHash -LiteralPath $ModelPath -Algorithm SHA256).Hash -ne $expectedSha256) {
    throw "LoRA model SHA-256 verification failed."
}

$adbArgs = @()
if ($Device) {
    $adbArgs += @("-s", $Device)
}

Write-Host "Installing LoRA test APK..." -ForegroundColor Cyan
& $adb @adbArgs install -r $ApkPath
if ($LASTEXITCODE -ne 0) { throw "LoRA APK installation failed." }

$remoteDir = "/sdcard/Android/data/$packageName/files/models"
$remotePath = "$remoteDir/$modelName"
& $adb @adbArgs shell mkdir -p $remoteDir
if ($LASTEXITCODE -ne 0) { throw "Unable to create the model directory on the phone." }

Write-Host "Transferring the 2.55 GB LoRA model. Keep the wireless connection active..." -ForegroundColor Cyan
& $adb @adbArgs push $ModelPath $remotePath
if ($LASTEXITCODE -ne 0) { throw "LoRA model transfer failed." }

$remoteBytes = (& $adb @adbArgs shell stat -c %s $remotePath).Trim()
if ($remoteBytes -ne "$expectedBytes") {
    throw "Unexpected model size on phone: $remoteBytes bytes"
}

& $adb @adbArgs shell am force-stop $packageName
& $adb @adbArgs shell monkey -p $packageName -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "LoRA test APK and trained model installed successfully." -ForegroundColor Green
