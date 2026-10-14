param(
    [string]$ApiUrl = "http://127.0.0.1:8000/api/v1",
    [string]$DeviceToken = "smartpill-dev-token",
    [string]$DeviceId = "pillbox-01",
    [string]$UserName = ""
)

$ErrorActionPreference = "Stop"
$ApiUrl = $ApiUrl.TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($UserName)) {
    $UserName = [string]::Concat([char]0x738B, [char]0x963F, [char]0x516C)
}
$headers = @{
    "X-Device-Token" = $DeviceToken
    "Accept" = "application/json"
    "Content-Type" = "application/json"
}

function Send-SimulatedEvent {
    param(
        [Parameter(Mandatory = $true)][string]$EventType,
        [object]$Slot = $null,
        [switch]$Silent
    )

    $payload = [ordered]@{
        device_id = $DeviceId
        user_name = $UserName
        event_type = $EventType
        source = "software_hardware_simulator"
    }
    if ($null -ne $Slot) {
        $payload.slot = [int]$Slot
    }

    $jsonBytes = [System.Text.Encoding]::UTF8.GetBytes(($payload | ConvertTo-Json -Compress))
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$ApiUrl/sensors/events/" `
        -Headers $headers `
        -Body $jsonBytes `
        -TimeoutSec 10

    if (-not $Silent) {
        $slotText = if ($null -ne $Slot) { "slot $Slot" } else { "no slot" }
        $matchText = if ($response.matched_reminder) { $response.matched_reminder.id } else { "none" }
        Write-Host "Event sent: $slotText / $EventType; matched reminder=$matchText" -ForegroundColor Cyan
    }
    return $response
}

function Get-SimulatedState {
    $deviceQuery = [Uri]::EscapeDataString($DeviceId)
    $userQuery = [Uri]::EscapeDataString($UserName)
    return Invoke-RestMethod `
        -Method Get `
        -Uri "$ApiUrl/hardware/state/?device_id=$deviceQuery&user_name=$userQuery" `
        -Headers $headers `
        -TimeoutSec 10
}

function Format-StateSignature {
    param($State)
    $slotParts = foreach ($slot in @($State.slots)) {
        "{0}:{1}:{2}" -f $slot.slot, $slot.state, [int][bool]$slot.led_on
    }
    return "{0}|{1}|{2}" -f [int][bool]$State.online, ($slotParts -join ","), [int][bool]$State.buzzer_on
}

function Show-SimulatedState {
    param($State)
    $labels = @{ 1 = "BLUE / MORNING / LEFT"; 2 = "RED / NOON / MIDDLE"; 3 = "GREEN / EVENING / RIGHT" }
    Write-Host ""
    Write-Host ("Simulated pillbox: {0}  Device: {1}" -f $DeviceId, $(if ($State.online) { "ONLINE" } else { "OFFLINE" })) -ForegroundColor Yellow
    foreach ($slot in @($State.slots)) {
        $light = if ($slot.led_on) { "ON" } else { "OFF" }
        Write-Host ("  Slot {0} [{1}]: LED {2}, state={3}" -f $slot.slot, $labels[[int]$slot.slot], $light, $slot.state)
    }
    Write-Host ("  Buzzer: {0}" -f $(if ($State.buzzer_on) { "ON" } else { "OFF" }))
}

function Show-Menu {
    Write-Host ""
    Write-Host "=== Smart Pill Box Hardware Simulator (NO COM PORT) ===" -ForegroundColor Green
    Write-Host "1: OPEN  morning / blue / left"
    Write-Host "2: OPEN  noon / red / middle"
    Write-Host "3: OPEN  evening / green / right"
    Write-Host "4: CLOSE morning / blue / left"
    Write-Host "5: CLOSE noon / red / middle"
    Write-Host "6: CLOSE evening / green / right"
    Write-Host "P: PIR presence detected     C: PIR presence cleared"
    Write-Host "S: Show LED and buzzer state from Django"
    Write-Host "Q: Quit"
    Write-Host ""
}

Show-Menu
$lastHeartbeat = [DateTime]::MinValue
$lastPoll = [DateTime]::MinValue
$lastSignature = ""
$apiErrorShown = $false
$running = $true

while ($running) {
    $now = Get-Date
    try {
        if (($now - $lastHeartbeat).TotalSeconds -ge 30) {
            $null = Send-SimulatedEvent -EventType "heartbeat" -Silent
            $lastHeartbeat = $now
        }
        if (($now - $lastPoll).TotalSeconds -ge 5) {
            $state = Get-SimulatedState
            $signature = Format-StateSignature -State $state
            if ($signature -ne $lastSignature) {
                Show-SimulatedState -State $state
                $lastSignature = $signature
            }
            $lastPoll = $now
        }
        $apiErrorShown = $false
    }
    catch {
        if (-not $apiErrorShown) {
            Write-Host "Cannot connect to Django: $($_.Exception.Message)" -ForegroundColor Red
            Write-Host "Start Django first. This simulator will retry automatically." -ForegroundColor Yellow
            $apiErrorShown = $true
        }
    }

    if ([Console]::KeyAvailable) {
        $key = [char]::ToUpperInvariant([Console]::ReadKey($true).KeyChar)
        try {
            switch ($key) {
                "1" { $null = Send-SimulatedEvent -EventType "opened" -Slot 1 }
                "2" { $null = Send-SimulatedEvent -EventType "opened" -Slot 2 }
                "3" { $null = Send-SimulatedEvent -EventType "opened" -Slot 3 }
                "4" { $null = Send-SimulatedEvent -EventType "closed" -Slot 1 }
                "5" { $null = Send-SimulatedEvent -EventType "closed" -Slot 2 }
                "6" { $null = Send-SimulatedEvent -EventType "closed" -Slot 3 }
                "P" { $null = Send-SimulatedEvent -EventType "presence_detected" }
                "C" { $null = Send-SimulatedEvent -EventType "presence_cleared" }
                "S" { Show-SimulatedState -State (Get-SimulatedState) }
                "Q" { $running = $false }
                default { Show-Menu }
            }
            $lastPoll = [DateTime]::MinValue
        }
        catch {
            Write-Host "Failed to send event: $($_.Exception.Message)" -ForegroundColor Red
        }
    }

    Start-Sleep -Milliseconds 200
}

Write-Host "Hardware simulator stopped." -ForegroundColor Yellow
