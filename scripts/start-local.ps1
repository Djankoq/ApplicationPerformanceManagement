param([switch]$Build, [switch]$InstallMonitoring)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:MAVEN_USER_HOME = "$projectRoot/.cache/maven-user"
if ($Build) {
    & "$projectRoot/mvnw.cmd" "-Dmaven.repo.local=$projectRoot/.cache/m2" --batch-mode --no-transfer-progress verify
    if ($LASTEXITCODE -ne 0) { throw 'Maven build failed' }
}
if ($InstallMonitoring) {
    python "$PSScriptRoot/install_monitoring.py"
    if ($LASTEXITCODE -ne 0) { throw 'Monitoring installation failed' }
}
$prometheusExe = Get-ChildItem "$projectRoot/.tools/prometheus" -Recurse -Filter prometheus.exe | Select-Object -First 1 -ExpandProperty FullName
$grafanaExe = Get-ChildItem "$projectRoot/.tools/grafana" -Recurse -Filter grafana.exe | Select-Object -First 1 -ExpandProperty FullName
if (!$prometheusExe -or !$grafanaExe) { throw 'Run python scripts/install_monitoring.py first' }
if (!(Test-Path "$projectRoot/target/apm-lab.jar")) { throw 'Build target/apm-lab.jar first' }
foreach ($port in @(8080,9090,3000)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "Port $port is in use; stop the existing service before starting"
    }
}
$runDirectory = "$projectRoot/.run"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
foreach ($directory in @('grafana-data','grafana-logs','grafana-plugins','prometheus-data')) {
    New-Item -ItemType Directory -Force -Path "$runDirectory/$directory" | Out-Null
}
$services = @()
function Start-LabProcess($name, $executable, $arguments) {
    $process = Start-Process -FilePath $executable -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput "$runDirectory/$name.log" -RedirectStandardError "$runDirectory/$name.err.log"
    # Start time prevents stop-local.ps1 from stopping an unrelated process after PID reuse.
    $script:services += @{ name=$name; pid=$process.Id; started=$process.StartTime.ToUniversalTime().ToString('o') }
    $script:services | ConvertTo-Json | Set-Content "$runDirectory/processes.json"
}
function Wait-LabService($url) {
    $deadline = (Get-Date).AddSeconds(60)
    do {
        try {
            Invoke-RestMethod $url -TimeoutSec 2 | Out-Null
            return
        } catch { Start-Sleep -Milliseconds 500 }
    } while ((Get-Date) -lt $deadline)
    throw "Service did not become ready: $url. See .run/*.log"
}
$env:PROMETHEUS_URL = 'http://127.0.0.1:9090'
$env:GRAFANA_DASHBOARDS_PATH = "$projectRoot/monitoring/grafana/dashboards"
$env:GF_PATHS_PROVISIONING = "$projectRoot/monitoring/grafana/provisioning"
$env:GF_PATHS_DATA = "$runDirectory/grafana-data"
$env:GF_PATHS_LOGS = "$runDirectory/grafana-logs"
$env:GF_PATHS_PLUGINS = "$runDirectory/grafana-plugins"
$env:GF_SERVER_HTTP_ADDR = '127.0.0.1'
$env:GF_PLUGINS_PREINSTALL_DISABLED = 'true'
$grafanaHome = Split-Path -Parent (Split-Path -Parent $grafanaExe)
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$javaSettings = & java -XshowSettings:properties -version 2>&1
$ErrorActionPreference = $previousErrorAction
$javaHomeLine = $javaSettings | Select-String '^\s*java.home\s*='
$javaExecutable = Join-Path (($javaHomeLine.ToString() -split '=', 2)[1].Trim()) 'bin/java.exe'
try {
    Start-LabProcess 'app' $javaExecutable '-jar target/apm-lab.jar'
    Wait-LabService 'http://127.0.0.1:8080/actuator/health'
    Start-LabProcess 'prometheus' $prometheusExe "--config.file=monitoring/prometheus.local.yml --storage.tsdb.path=.run/prometheus-data --storage.tsdb.retention.time=7d --web.listen-address=127.0.0.1:9090"
    Wait-LabService 'http://127.0.0.1:9090/-/ready'
    Start-LabProcess 'grafana' $grafanaExe "server --homepath=`"$grafanaHome`" --config=`"$projectRoot/monitoring/grafana/grafana.ini`""
    Wait-LabService 'http://127.0.0.1:3000/api/health'
} catch {
    & "$PSScriptRoot/stop-local.ps1"
    throw
}
Write-Output 'Application: http://127.0.0.1:8080/actuator/health'
Write-Output 'Prometheus:  http://127.0.0.1:9090/targets'
Write-Output 'Grafana:     http://127.0.0.1:3000/d/apm-red'
