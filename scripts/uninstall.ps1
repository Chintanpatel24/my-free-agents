param(
  [string]$RootDir = "$env:USERPROFILE\.my-free-agents",
  [switch]$KeepConfig
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RootDir) -or $RootDir -eq '\' -or $RootDir -eq $env:USERPROFILE) {
  Write-Host "Refusing unsafe root: $RootDir" -ForegroundColor Red
  exit 1
}
$BinDir = Join-Path $RootDir 'bin'
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'my-free-claudecode.cmd'), (Join-Path $BinDir 'my-free-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode-server.cmd'), (Join-Path $BinDir 'my-claudecode-server.ps1'), (Join-Path $BinDir 'my-server-claudecode.cmd'), (Join-Path $BinDir 'my-server-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode.cmd'), (Join-Path $BinDir 'my-claudecode.ps1'), (Join-Path $BinDir 'start-claudecode-server.cmd'), (Join-Path $BinDir 'start-claudecode-server.ps1')
if ($KeepConfig) {
  $AppDir = Join-Path $RootDir 'claudecode'
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
    (Join-Path $AppDir 'free_claude_code'), `
    (Join-Path $AppDir 'my_claudecode_python'), `
    (Join-Path $AppDir 'bin'), `
    (Join-Path $AppDir 'scripts'), `
    (Join-Path $AppDir 'assets'), `
    (Join-Path $AppDir 'tests'), `
    (Join-Path $AppDir 'pyproject.toml'), `
    (Join-Path $AppDir 'README.md'), `
    (Join-Path $AppDir 'LICENSE')
} else {
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RootDir
}
Write-Host 'Removed My Free Agents.' -ForegroundColor Green
