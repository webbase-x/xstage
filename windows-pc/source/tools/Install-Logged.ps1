$ErrorActionPreference='Stop'
$logs=Join-Path $env:LOCALAPPDATA 'XStageKaraoke\Logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log=Join-Path $logs ('install-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.log')
$code=1
$started=Get-Date
$sourceRoot=Split-Path -Parent $PSScriptRoot
Start-Transcript -Path $log -Force | Out-Null
try {
    $global:LASTEXITCODE=0
    & (Join-Path (Split-Path -Parent $PSScriptRoot) 'install_to_D.ps1') -CloseRunning -RunSetup
    $code=$LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $code=1
} finally {
    # When installation failed during the full regression suite, keep its
    # *actual* failing test IDs and tracebacks in the same durable log folder.
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    foreach ($filename in @('build-tests.log','build-tests-summary.json')) {
        $from=Join-Path $sourceRoot $filename
        if ((Test-Path -LiteralPath $from -PathType Leaf) -and
            (Get-Item -LiteralPath $from).LastWriteTime -ge $started.AddSeconds(-2)) {
            $copy=Join-Path $logs (([IO.Path]::GetFileNameWithoutExtension($filename))+'-'+$stamp+[IO.Path]::GetExtension($filename))
            try {
                Copy-Item -LiteralPath $from -Destination $copy -Force -ErrorAction Stop
                Write-Host ('Build test diagnostics: '+$copy)
            } catch { Write-Warning ('Could not copy build test diagnostics: '+$_.Exception.Message) }
        }
    }
    if ($code -ne 0) {
        $summaryFile=Join-Path $sourceRoot 'build-tests-summary.json'
        if ((Test-Path -LiteralPath $summaryFile -PathType Leaf) -and
            (Get-Item -LiteralPath $summaryFile).LastWriteTime -ge $started.AddSeconds(-2)) {
            try {
                $summary=Get-Content -LiteralPath $summaryFile -Raw -Encoding UTF8 | ConvertFrom-Json
                Write-Host ('Windows tests: '+$summary.tests_run+' | failures: '+@($summary.failures).Count+' | errors: '+@($summary.errors).Count+' | skipped: '+$summary.skipped_count) -ForegroundColor Yellow
                foreach ($failure in @($summary.failures)+@($summary.errors)) {
                    if ($failure -and $failure.test) { Write-Host ('FAILED: '+$failure.test) -ForegroundColor Red }
                }
                if ($summary.fatal) { Write-Host ('BUILD GATE ERROR: '+$summary.fatal) -ForegroundColor Red }
            } catch { Write-Warning ('Could not read build test summary: '+$_.Exception.Message) }
        }
    }
    Write-Host ('Installation log: '+$log)
    Stop-Transcript | Out-Null
}
exit $code
