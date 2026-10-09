$ErrorActionPreference = "Stop"
$python = (Get-Command python).Source
$agent = Start-Process `
    -FilePath $python `
    -ArgumentList @("manage.py", "run_medication_agent", "--interval", "15") `
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
}
