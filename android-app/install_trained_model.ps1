param(
    [string]$Device = "",
    [string]$ModelPath = ""
)

$ErrorActionPreference = "Stop"

$modelName = "MiniCPM5-2B_smartpill_trained_int8.litertlm"
$expectedBytes = 2546936640
$expectedSha256 = "646A5D14AA9D717602B798EFB09672F902547F3C9E2F1739372E50AA1160E92D"
$packageName = "com.example.smartpillbox"

if (-not $ModelPath) {
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $ModelPath = Join-Path $repositoryRoot "models\$modelName"
    $assembleScript = Join-Path $repositoryRoot "models\assemble_trained_model.ps1"
    if (-not (Test-Path -LiteralPath $ModelPath) -and (Test-Path -LiteralPath $assembleScript)) {
        & $assembleScript -OutputPath $ModelPath
    }
}

if (-not (Test-Path -LiteralPath $ModelPath)) {
    throw "找不到模型：$ModelPath"
}

$model = Get-Item -LiteralPath $ModelPath
if ($model.Length -ne $expectedBytes) {
    throw "模型大小不正確：$($model.Length) bytes"
}
if ((Get-FileHash -LiteralPath $ModelPath -Algorithm SHA256).Hash -ne $expectedSha256) {
    throw "模型 SHA-256 驗證失敗。"
}

$adb = Get-Command adb -ErrorAction Stop
$adbArgs = @()
if ($Device) {
    $adbArgs += @("-s", $Device)
}

$packagePath = & $adb.Source @adbArgs shell pm path $packageName
if (-not $packagePath) {
    throw "請先安裝並開啟一次智慧藥盒 APP。"
}

$remoteDir = "/sdcard/Android/data/$packageName/files/models"
$remotePath = "$remoteDir/$modelName"

Write-Host "正在建立手機模型資料夾..." -ForegroundColor Cyan
& $adb.Source @adbArgs shell mkdir -p $remoteDir
if ($LASTEXITCODE -ne 0) {
    throw "無法建立手機模型資料夾。"
}

Write-Host "正在傳送 2.37 GB 訓練模型，請保持 USB 連線..." -ForegroundColor Cyan
& $adb.Source @adbArgs push $ModelPath $remotePath
if ($LASTEXITCODE -ne 0) {
    throw "模型傳送失敗。"
}

$remoteBytes = (& $adb.Source @adbArgs shell stat -c %s $remotePath).Trim()
if ($remoteBytes -ne "$expectedBytes") {
    throw "手機模型大小不正確：$remoteBytes bytes"
}
$remoteSha256 = ((& $adb.Source @adbArgs shell sha256sum $remotePath) -split '\s+')[0].ToUpperInvariant()
if ($remoteSha256 -ne $expectedSha256) {
    throw "手機模型 SHA-256 驗證失敗。"
}

Write-Host "智慧藥盒訓練模型已安裝到手機。" -ForegroundColor Green
