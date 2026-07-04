param(
  [string]$RootDir = "$env:USERPROFILE\.my-free-agents",
  [switch]$KeepConfig
)
$ErrorActionPreference = 'Stop'
$BinDir = Join-Path $RootDir 'bin'
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'my-free-claudecode.cmd'), (Join-Path $BinDir 'my-free-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode-server.cmd'), (Join-Path $BinDir 'my-claudecode-server.ps1'), (Join-Path $BinDir 'my-server-claudecode.cmd'), (Join-Path $BinDir 'my-server-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode.cmd'), (Join-Path $BinDir 'my-claudecode.ps1'), (Join-Path $BinDir 'start-claudecode-server.cmd'), (Join-Path $BinDir 'start-claudecode-server.ps1')
if ($KeepConfig) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RootDir 'claudecode') } else { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RootDir }
Write-Host 'Removed My Free Agents.' -ForegroundColor Green
