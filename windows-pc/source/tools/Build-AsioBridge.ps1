param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\native\x64'))
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'Windows x64 required' }
$source = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\native\asio_pcm_bridge.cpp')).Path
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$destination = (Resolve-Path -LiteralPath $OutputDirectory).Path
$output = Join-Path $destination 'xstage_asio_pcm.dll'
$compiler = Get-Command cl.exe -ErrorAction SilentlyContinue
if (-not $compiler) { throw 'MSVC cl.exe missing; initialize an x64 Visual Studio developer environment' }
$working = Join-Path $env:TEMP ('xstage-asio-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $working | Out-Null
try {
    Push-Location $working
    try {
        & $compiler.Source /nologo /std:c++17 /EHsc /O2 /LD /W4 $source /link "/OUT:$output"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output -PathType Leaf)) {
            throw 'ASIO PCM bridge DLL compilation failed'
        }
    } finally { Pop-Location }
} finally {
    Remove-Item -LiteralPath $working -Recurse -Force -ErrorAction SilentlyContinue
}
Write-Host "Built: $output"
