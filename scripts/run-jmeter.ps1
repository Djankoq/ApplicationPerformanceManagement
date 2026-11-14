param(
    [string]$JMeterHome = $env:JMETER_HOME,
    [string]$TargetHost = '127.0.0.1',
    [ValidateRange(1,65535)][int]$Port = 8080,
    [ValidateSet('http','https')][string]$Protocol = 'http',
    [ValidateRange(2,10000)][int]$Threads = 10,
    [ValidateRange(1,86400)][int]$RampUpSeconds = 20,
    [ValidateRange(1,100000)][int]$Loops = 10,
    [ValidateRange(0,60000)][int]$ThinkTimeMs = 500,
    [ValidateRange(0,60000)][int]$ThinkTimeRangeMs = 1000
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (!$JMeterHome) { $JMeterHome = Join-Path $projectRoot '.tools/apache-jmeter-5.6.3' }
$jmeter = Join-Path $JMeterHome 'bin/jmeter.bat'
if (!(Test-Path -LiteralPath $jmeter -PathType Leaf)) {
    throw "JMeter not found: $jmeter. Extract Apache JMeter 5.6.3 into .tools or pass -JMeterHome."
}
$JMeterHome = (Resolve-Path -LiteralPath $JMeterHome).Path
$jmeter = Join-Path $JMeterHome 'bin/jmeter.bat'
$resultDirectory = Join-Path $projectRoot ('reports/jmeter/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $resultDirectory -Force | Out-Null
$resultsFile = Join-Path $resultDirectory 'results.jtl'
$arguments = @(
    '-n', '-t', (Join-Path $projectRoot 'jmeter/api-users.jmx'),
    '-l', $resultsFile, '-j', (Join-Path $resultDirectory 'jmeter.log'),
    '-e', '-o', (Join-Path $resultDirectory 'html'),
    ('-Jjmeter.reportgenerator.temp_dir=' + (Join-Path $resultDirectory 'temp')),
    "-Jhost=$TargetHost", "-Jport=$Port", "-Jprotocol=$Protocol",
    "-Jthreads=$Threads", "-JrampUp=$RampUpSeconds", "-Jloops=$Loops",
    "-JthinkTimeMs=$ThinkTimeMs", "-JthinkTimeRangeMs=$ThinkTimeRangeMs",
    ('-JdataFile=' + (Join-Path $projectRoot 'jmeter/api-delays.csv')),
    '-Jjmeter.save.saveservice.output_format=csv',
    '-Jjmeter.save.saveservice.print_field_names=true',
    '-Jjmeter.save.saveservice.assertion_results_failure_message=true',
    '-Jjmeter.save.saveservice.url=true',
    '-Jjmeter.save.saveservice.thread_counts=true',
    '-Jsample_variables=platformDelayMs,virtualDelayMs'
)
$previousJMeterHome = $env:JMETER_HOME
try {
    $env:JMETER_HOME = $JMeterHome
    & $jmeter @arguments
    if ($LASTEXITCODE -ne 0) { throw "JMeter exited with code $LASTEXITCODE. See $resultDirectory/jmeter.log" }
} finally {
    $env:JMETER_HOME = $previousJMeterHome
}
if (!(Test-Path -LiteralPath $resultsFile)) { throw "No JTL results. See $resultDirectory/jmeter.log" }
$samples = @(Import-Csv -LiteralPath $resultsFile)
$failures = @($samples | Where-Object { $_.success -ne 'true' })
$expected = [long]$Threads * $Loops * 2
Write-Output "Results: $resultsFile"
Write-Output "HTML report: $resultDirectory/html/index.html"
Write-Output "Samples: $($samples.Count) / $expected; failures: $($failures.Count)"
# JMeter can exit with code 0 even when HTTP requests or assertions fail.
if ($failures.Count -gt 0) {
    $failures | Select-Object -First 5 label,responseCode,failureMessage | Format-Table -AutoSize
    throw "$($failures.Count) request(s) or assertion(s) failed. See $resultsFile"
}
if ($samples.Count -ne $expected) { throw "Incomplete run: expected $expected samples, got $($samples.Count)." }
if (!(Test-Path -LiteralPath (Join-Path $resultDirectory 'html/index.html'))) {
    throw "HTML report was not generated. See $resultDirectory/jmeter.log"
}
