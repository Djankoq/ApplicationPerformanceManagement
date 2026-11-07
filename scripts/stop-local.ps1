$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$state = "$projectRoot/.run/processes.json"
if (!(Test-Path -LiteralPath $state)) { return }
$labServices = Get-Content -Raw -LiteralPath $state | ConvertFrom-Json
foreach ($service in $labServices) {
    $process = Get-Process -Id $service.pid -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $service.started) {
        Stop-Process -InputObject $process
        Write-Output "Stopped $($service.name) ($($service.pid))"
    }
}
Remove-Item -LiteralPath $state
