param(
  [string]$RepoUrl = $env:MY_FREE_AGENTS_REPO,
  [string]$Branch = $(if ($env:MY_FREE_AGENTS_BRANCH) { $env:MY_FREE_AGENTS_BRANCH } else { 'main' })
)

$ErrorActionPreference = 'Stop'
if (-not $RepoUrl) { $RepoUrl = 'https://github.com/Chintanpatel24/my-free-agents.git' }

function Step($Message) { Write-Host "[my-free-agents] $Message" -ForegroundColor Cyan }
function Done($Message) { Write-Host "[ok] $Message" -ForegroundColor Green }
function Fail($Message) { Write-Host "[error] $Message" -ForegroundColor Red; exit 1 }

Step "Updating My Free Agents for Claude Code"

$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$LocalInstaller = if ($ScriptDir) { Join-Path $ScriptDir 'scripts\install.ps1' } else { $null }

if ($LocalInstaller -and (Test-Path $LocalInstaller) -and (Test-Path (Join-Path $ScriptDir 'pyproject.toml'))) {
  Step "Using local installer at $LocalInstaller"
  & $LocalInstaller @args
  exit $LASTEXITCODE
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Fail "git is required for update. Install Git, then run this command again."
}

$Tmp = Join-Path ([IO.Path]::GetTempPath()) ('my-free-agents-' + [guid]::NewGuid().ToString('N'))
$RepoDir = Join-Path $Tmp 'repo'
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null

try {
  Step "Downloading $RepoUrl ($Branch)"
  git clone --depth 1 --branch $Branch $RepoUrl $RepoDir
  if ($LASTEXITCODE -ne 0) { Fail "git clone failed with exit code $LASTEXITCODE" }

  Step "Running updater"
  & (Join-Path $RepoDir 'scripts\install.ps1') @args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  Done "Update finished"
} catch {
  Fail $_.Exception.Message
} finally {
  Step "Cleaning temporary files"
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Tmp
}
