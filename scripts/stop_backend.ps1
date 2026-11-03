param(
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$pythonPaths = @(
    (Join-Path $env:LOCALAPPDATA 'SelfHealNet\venv\Scripts\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
)
$netstatOutput = netstat -ano -p tcp
$listeners = @(
    $netstatOutput | ForEach-Object {
        if ($_ -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            [int]$Matches[1]
        }
    } | Sort-Object -Unique
)

if ($listeners.Count -eq 0) {
    Write-Output "No listener on port $Port."
    exit 0
}

$owned = @()
foreach ($processId in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $expectedApp = $process.CommandLine -match '(?i)-m\s+uvicorn\s+backend\.main:app'
    $expectedPort = $process.CommandLine -match "(?i)--port\s+`"?$Port`"?(\s|$)"
    if ($process.ExecutablePath -notin $pythonPaths -or -not $expectedApp -or -not $expectedPort) {
        throw "Port $Port is owned by an unrelated process (PID $processId); refusing to stop it. Command line: $($process.CommandLine)"
    }
    $owned += $process
}

foreach ($process in $owned) {
    Stop-Process -Id $process.ProcessId
    try {
        Wait-Process -Id $process.ProcessId -Timeout 10 -ErrorAction Stop
    } catch {
        if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
            throw "SelfHealNet backend PID $($process.ProcessId) did not stop within 10 seconds. No force-kill was attempted."
        }
    }
    Write-Output "Stopped SelfHealNet backend PID $($process.ProcessId) on port $Port."
}