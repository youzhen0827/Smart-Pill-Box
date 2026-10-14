$ErrorActionPreference = "Stop"

$python = "C:\Users\User\anaconda3\envs\venv_312\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$modelDir = Join-Path $projectRoot "models"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

$modelName = "MiniCPM5-2B_smartpill_trained_int8.litertlm"
$modelPath = Join-Path $modelDir $modelName
$downloadPath = Join-Path $env:USERPROFILE "Downloads\$modelName"
$expectedBytes = 2546936640
$expectedSha256 = "646A5D14AA9D717602B798EFB09672F902547F3C9E2F1739372E50AA1160E92D"

if (-not (Test-Path -LiteralPath $modelPath)) {
    $assembleScript = Join-Path $modelDir "assemble_trained_model.ps1"
    if (Test-Path -LiteralPath $assembleScript) {
        & $assembleScript -OutputPath $modelPath
    } elseif (Test-Path -LiteralPath $downloadPath) {
        Write-Host "正在安裝智慧藥盒訓練模型..." -ForegroundColor Cyan
        Copy-Item -LiteralPath $downloadPath -Destination $modelPath
    } else {
        throw "找不到訓練模型。請先執行 git lfs pull，或將模型放到：$downloadPath"
    }
}

$modelFile = Get-Item -LiteralPath $modelPath
if ($modelFile.Length -ne $expectedBytes) {
    throw "模型大小不正確：$($modelFile.Length) bytes"
}
$actualSha256 = (Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash
if ($actualSha256 -ne $expectedSha256) {
    throw "模型 SHA-256 驗證失敗，請重新下載訓練模型。"
}

Write-Host "正在安裝 MiniCPM5-2B 本機執行元件..." -ForegroundColor Cyan
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "正在確認第 8 版 Agent..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    & $python manage.py check_agent_model
} finally {
    Pop-Location
}
