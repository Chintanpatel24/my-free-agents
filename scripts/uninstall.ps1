param(
  [string]$RootDir = "$env:USERPROFILE\.free-claude-code",
  [switch]$KeepConfig
)
$ErrorActionPreference = 'Stop'
$BinDir = Join-Path $RootDir 'bin'
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'my-free-claudecode.cmd'), (Join-Path $BinDir 'my-free-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode-server.cmd'), (Join-Path $BinDir 'my-claudecode-server.ps1'), (Join-Path $BinDir 'my-server-claudecode.cmd'), (Join-Path $BinDir 'my-server-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode.cmd'), (Join-Path $BinDir 'my-claudecode.ps1')
if ($KeepConfig) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $RootDir 'app') } else { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $RootDir }
Write-Host 'Removed My ClaudeCode NVIDIA NIM Proxy.' -ForegroundColor Green
