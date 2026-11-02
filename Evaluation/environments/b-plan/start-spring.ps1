param(
    [Parameter(Mandatory = $true)]
    [string]$Runtime
)

$ErrorActionPreference = 'Stop'
$runtimePath = (Resolve-Path -LiteralPath $Runtime).Path
$snapshot = Get-Content -LiteralPath (Join-Path $runtimePath 'snapshot.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$verification = Get-Content -LiteralPath (Join-Path $runtimePath 'database-verification.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $verification.spring_rows_match_snapshot -or -not $verification.search_original_columns_match_snapshot) {
    throw 'The evaluation corpus must be verified before Spring starts.'
}
if ($verification.pending_search_jobs -ne 0 -or $verification.pending_spring_outbox -ne 0) {
    throw 'Pending jobs could invoke inference during preparation.'
}
$jarPath = Join-Path $runtimePath 'spring.jar'
if ((Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $snapshot.jar_sha256) {
    throw 'The frozen evaluation JAR has changed.'
}
$pidPath = Join-Path $runtimePath 'spring.pid'
if (Test-Path -LiteralPath $pidPath) {
    $previousProcessId = [int](Get-Content -LiteralPath $pidPath -Raw)
    if (Get-Process -Id $previousProcessId -ErrorAction SilentlyContinue) {
        throw 'A recorded Spring process is still alive; inspect it instead of starting a duplicate.'
    }
}
$portListener = Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue
if ($portListener) { throw 'Port 18080 is occupied.' }

# Environment property sources must not redirect this process to the existing stack.
$inheritedNames = @(Get-ChildItem Env: | ForEach-Object Name)
foreach ($variableName in $inheritedNames) {
    if ($variableName -match '^(SPRING_|DB_|REDIS_|KAFKA_|EMBEDDING_|TRAVELMATE_|OLLAMA|LLM_|OPENAI_|PERPLEXITY_|LANGSMITH_|LANGCHAIN_|OTEL_|CONVERSATION_|EXECUTION_OBSERVATION_|JWT_|KAKAO_|TOUR|JAVA_TOOL_OPTIONS|JDK_JAVA_OPTIONS)') {
        [Environment]::SetEnvironmentVariable($variableName, $null, 'Process')
    }
}
$propertiesPath = (Join-Path $runtimePath 'spring.properties').Replace('\', '/')
$javaProcess = Start-Process -FilePath (Get-Command java).Source -WindowStyle Hidden -PassThru -ArgumentList @(
    '-Xmx768m', '-jar', ('"' + $jarPath + '"'), ('"--spring.config.additional-location=file:' + $propertiesPath + '"')
) -WorkingDirectory $runtimePath -RedirectStandardOutput (Join-Path $runtimePath 'spring.stdout.log') -RedirectStandardError (Join-Path $runtimePath 'spring.stderr.log')
$javaProcess.Id | Set-Content -LiteralPath $pidPath -Encoding ASCII
Write-Output "Started isolated Windows Spring. PID: $($javaProcess.Id)"
