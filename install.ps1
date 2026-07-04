param(
  [string]$RepoUrl = $env:FREE_CLAUDE_CODE_REPO,
  [string]$Branch = $(if ($env:FREE_CLAUDE_CODE_BRANCH) { $env:FREE_CLAUDE_CODE_BRANCH } else { 'dev' })
)
$ErrorActionPreference = 'Stop'
if (-not $RepoUrl) { $RepoUrl = 'https://github.com/Chintanpatel24/my-free-claudecode.git' }
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$LocalInstaller = if ($ScriptDir) { Join-Path $ScriptDir 'scripts\install.ps1' } else { $null }
if ($LocalInstaller -and (Test-Path $LocalInstaller) -and (Test-Path (Join-Path $ScriptDir 'pyproject.toml'))) { & $LocalInstaller @args; exit $LASTEXITCODE }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host 'git is required for remote install.' -ForegroundColor Red; exit 1 }
$Tmp = Join-Path ([IO.Path]::GetTempPath()) ('free-claude-code-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
try { git clone --depth 1 --branch $Branch $RepoUrl (Join-Path $Tmp 'repo'); Push-Location (Join-Path $Tmp 'repo'); & (Join-Path $Tmp 'repo\scripts\install.ps1') @args; Pop-Location } finally { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp }
