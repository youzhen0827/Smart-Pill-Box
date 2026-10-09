$ErrorActionPreference = "Stop"

$python = (Get-Command python -ErrorAction Stop).Source

$projectRoot = Split-Path -Parent $PSScriptRoot
$modelDir = Join-Path $projectRoot "models"
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null

Write-Host "正在安裝 MiniCPM5-2B 本機執行元件..." -ForegroundColor Cyan
& $python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
& $python -m pip install "huggingface_hub[hf_xet]==0.36.0"

Write-Host "正在下載 MiniCPM5-2B（約 1.55 GB，可續傳）..." -ForegroundColor Cyan
& $python -c "from huggingface_hub import hf_hub_download; print(hf_hub_download(repo_id='litert-community/MiniCPM5-2B', filename='MiniCPM5-2B_int4.litertlm', local_dir=r'$modelDir'))"

Write-Host "正在確認第 8 版 Agent..." -ForegroundColor Cyan
Push-Location $PSScriptRoot
try {
    & $python manage.py check_agent_model
} finally {
    Pop-Location
}
