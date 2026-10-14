param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$modelName = "MiniCPM5-2B_smartpill_trained_int8.litertlm"
$expectedBytes = 2546936640
$expectedSha256 = "646A5D14AA9D717602B798EFB09672F902547F3C9E2F1739372E50AA1160E92D"
$partsDir = Join-Path $PSScriptRoot "parts"

if (-not $OutputPath) {
    $OutputPath = Join-Path $PSScriptRoot $modelName
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$parts = Get-ChildItem -LiteralPath $partsDir -Filter "$modelName.part*" -File |
    Sort-Object Name
if ($parts.Count -ne 4) {
    throw "模型分割檔不完整：預期 4 個，實際找到 $($parts.Count) 個。請先執行 git lfs pull。"
}

$outputDir = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$temporaryPath = "$OutputPath.partial"
Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue

Write-Host "正在組合智慧藥盒訓練模型..." -ForegroundColor Cyan
$destination = [System.IO.File]::Open(
    $temporaryPath,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::Write,
    [System.IO.FileShare]::None
)
try {
    foreach ($part in $parts) {
        Write-Host "  加入 $($part.Name)"
        $source = [System.IO.File]::OpenRead($part.FullName)
        try {
            $source.CopyTo($destination, 8MB)
        } finally {
            $source.Dispose()
        }
    }
} finally {
    $destination.Dispose()
}

$combined = Get-Item -LiteralPath $temporaryPath
if ($combined.Length -ne $expectedBytes) {
    Remove-Item -LiteralPath $temporaryPath -Force
    throw "組合後模型大小不正確：$($combined.Length) bytes。"
}
$actualSha256 = (Get-FileHash -LiteralPath $temporaryPath -Algorithm SHA256).Hash
if ($actualSha256 -ne $expectedSha256) {
    Remove-Item -LiteralPath $temporaryPath -Force
    throw "組合後模型 SHA-256 驗證失敗。"
}

Move-Item -LiteralPath $temporaryPath -Destination $OutputPath -Force
Write-Host "模型已還原：$OutputPath" -ForegroundColor Green
