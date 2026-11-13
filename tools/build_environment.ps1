$ErrorActionPreference='Stop'
$projectRoot=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$env:TEMP=Join-Path $projectRoot 'temp'
$env:TMP=$env:TEMP
$env:PYTHONPYCACHEPREFIX=Join-Path $projectRoot 'cache/pycache'
$env:PYINSTALLER_CONFIG_DIR=Join-Path $projectRoot 'cache/pyinstaller'
$buildPathSaved=$env:PATH
try {
    # Process-only isolation; the machine/user PATH is never changed.
    $env:PATH='C:\Windows\System32;C:\Windows'
    & ./venv/Scripts/python.exe -B -m PyInstaller --clean --noconfirm --workpath build/environment --distpath dist tools/environment.spec *> logs/environment-build.txt
    if ($LASTEXITCODE -ne 0) {throw 'Environment EXE build failed; see logs/environment-build.txt'}
    & ./venv/Scripts/python.exe -B -m PyInstaller --noconfirm --workpath build/environment-launcher --distpath dist/environment-launcher tools/启动字幕.spec *> logs/environment-launcher-build.txt
    if ($LASTEXITCODE -ne 0) {throw 'Launcher build failed'}
} finally {$env:PATH=$buildPathSaved}
Copy-Item -LiteralPath dist/environment/环境补齐.exe -Destination ./环境补齐.exe -Force
Copy-Item -Path dist/environment/environment_internal/* -Destination ./environment_internal -Recurse -Force
# Remove only the two incompatible artifacts from the initial, failed build.
foreach ($stale in @('environment_internal/icuuc.dll','environment_internal/icudt78.dll')) {
    if (Test-Path -LiteralPath $stale) {Remove-Item -LiteralPath $stale}
}
New-Item -ItemType Directory -Path tools/backups -Force | Out-Null
if (-not (Test-Path -LiteralPath tools/backups/启动字幕-before-environment.exe)) {Copy-Item -LiteralPath ./启动字幕.exe -Destination tools/backups/启动字幕-before-environment.exe}
Copy-Item -LiteralPath dist/environment-launcher/启动字幕/启动字幕.exe -Destination ./启动字幕.exe -Force
Write-Output 'Built environment EXE and refreshed launcher. Existing subtitle processes were not restarted.'