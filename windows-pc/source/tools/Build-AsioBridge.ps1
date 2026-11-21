param([string]$OutputDirectory = (Join-Path $PSScriptRoot '..\native'))
$ErrorActionPreference = 'Stop'
if (-not $IsWindows -and $PSVersionTable.PSEdition -eq 'Core') { throw 'Windows x64 required' }
$source = Join-Path $PSScriptRoot '..\native\asio_pcm_bridge.cpp'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$output = Join-Path $OutputDirectory 'xstage_asio_pcm.dll'
$compiler = Get-Command cl.exe -ErrorAction SilentlyContinue
if (-not $compiler) { throw 'MSVC cl.exe not found. Run from x64 Native Tools Command Prompt for VS.' }
& $compiler.Source /nologo /std:c++17 /EHsc /O2 /LD /W4 /Fe:$output $source
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $output)) { throw 'ASIO PCM bridge DLL compilation failed' }
Write-Host "Built: $output"
