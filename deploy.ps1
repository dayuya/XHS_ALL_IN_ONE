param(
    [ValidateSet('Start', 'Stop', 'Status', 'Logs', 'Open')]
    [string]$Action = 'Start'
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
switch ($Action) {
    'Start'  { docker compose up -d --build --wait --wait-timeout 120 }
    'Stop'   { docker compose down }
    'Status' { docker compose ps }
    'Logs'   { docker compose logs --tail 100 }
    'Open'   { Start-Process 'http://127.0.0.1:18081'; exit 0 }
}
exit $LASTEXITCODE
