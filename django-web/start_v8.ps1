$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$agent = Start-Process `
    -FilePath $python `
    -ArgumentList @("manage.py", "run_medication_agent", "--interval", "15") `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden `
    -PassThru
$bridge = Start-Process `
    -FilePath $python `
    -ArgumentList @("esp32_usb/serial_bridge.py") `
    -WorkingDirectory $PSScriptRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    Set-Location $PSScriptRoot
    & $python manage.py runserver
} finally {
    if ($agent -and -not $agent.HasExited) {
        Stop-Process -Id $agent.Id
    }
    if ($bridge -and -not $bridge.HasExited) {
        Stop-Process -Id $bridge.Id
    }
}
