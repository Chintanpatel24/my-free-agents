param(
  [string]$InstallDir = "$env:USERPROFILE\.free-claude-code\app",
  [string]$BinDir = "$env:USERPROFILE\.free-claude-code\bin",
  [string]$Python = "python",
  [switch]$NoPath
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Fail($m) { Write-Host $m -ForegroundColor Red; exit 1 }

try { $version = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" } catch { Fail 'Python 3.10+ is required.' }
$majorMinor = & $Python -c "import sys; print(1 if sys.version_info >= (3,10) else 0)"
if ($majorMinor.Trim() -ne '1') { Fail "Python 3.10+ is required. Found $version" }

$SrcDir = Resolve-Path (Join-Path $PSScriptRoot '..')
Say 'Installing My ClaudeCode NVIDIA NIM Proxy safely for the current user...'
New-Item -ItemType Directory -Force -Path $InstallDir, $BinDir | Out-Null
$ExistingEnv = Join-Path $InstallDir '.env'
$SavedEnv = $null
if (Test-Path $ExistingEnv) { $SavedEnv = Get-Content $ExistingEnv -Raw }
Get-ChildItem -Path $InstallDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$exclude = @('.git','.env','__pycache__','.venv','dist','build')
Get-ChildItem -Path $SrcDir -Force | ForEach-Object { if ($exclude -notcontains $_.Name -and -not $_.Name.EndsWith('.egg-info')) { Copy-Item $_.FullName -Destination $InstallDir -Recurse -Force } }
if ($SavedEnv) { Set-Content -Path $ExistingEnv -Value $SavedEnv -Encoding UTF8 }

Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'my-free-claudecode.cmd'), (Join-Path $BinDir 'my-free-claudecode.ps1')
$shimCmd1 = Join-Path $BinDir 'my-claudecode-server.cmd'
$shimCmd2 = Join-Path $BinDir 'my-claudecode.cmd'
$shimPs1A = Join-Path $BinDir 'my-claudecode-server.ps1'
$shimPs1B = Join-Path $BinDir 'my-claudecode.ps1'
Set-Content -Path $shimCmd1 -Encoding ASCII -Value "@echo off`r`nset FREE_CLAUDE_CODE_HOME=$InstallDir`r`nset PYTHONPATH=$InstallDir;%PYTHONPATH%`r`n$Python -c `"from free_claude_code.cli import main_server; main_server()`" %*`r`n"
Set-Content -Path $shimCmd2 -Encoding ASCII -Value "@echo off`r`nset FREE_CLAUDE_CODE_HOME=$InstallDir`r`nset PYTHONPATH=$InstallDir;%PYTHONPATH%`r`n$Python -c `"from free_claude_code.cli import main_claude; main_claude()`" %*`r`n"
Set-Content -Path $shimPs1A -Encoding UTF8 -Value "`$env:FREE_CLAUDE_CODE_HOME='$InstallDir'`n`$env:PYTHONPATH='$InstallDir;' + `$env:PYTHONPATH`n& $Python -c 'from free_claude_code.cli import main_server; main_server()' @args`n"
Set-Content -Path $shimPs1B -Encoding UTF8 -Value "`$env:FREE_CLAUDE_CODE_HOME='$InstallDir'`n`$env:PYTHONPATH='$InstallDir;' + `$env:PYTHONPATH`n& $Python -c 'from free_claude_code.cli import main_claude; main_claude()' @args`n"

$env:FREE_CLAUDE_CODE_HOME = $InstallDir
$env:PYTHONPATH = "$InstallDir;$env:PYTHONPATH"
& $Python -c "from free_claude_code.config import ensure_env, write_env_values; ensure_env(); write_env_values({}); print(ensure_env())" | Out-Null

if (-not $NoPath) {
  $current = [Environment]::GetEnvironmentVariable('Path','User')
  $parts = $current -split ';' | Where-Object { $_ }
  if ($parts -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable('Path', ($current.TrimEnd(';') + ';' + $BinDir), 'User')
    $env:Path += ';' + $BinDir
    Warn "Added $BinDir to your user PATH. Restart terminal if needed."
  }
}
Say 'Installed commands:'
Write-Host "  $shimCmd1"
Write-Host "  $shimCmd2"
Say "Config file: $ExistingEnv"

# Prompt for API Key
$UserApiKey = Read-Host "`nPlease enter your NVIDIA NIM API key"

if ($UserApiKey) {
    Say "Validating API key..."
    try {
        $headers = @{ "Authorization" = "Bearer $UserApiKey" }
        $resp = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/models" -Headers $headers -Method Get -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            & $Python -c "from free_claude_code.config import write_env_values; write_env_values({'NVIDIA_NIM_API': '$UserApiKey'})"
            Say "API key validated and saved."
        }
    } catch {
        Warn "API key validation failed. You can set it later in $ExistingEnv or via the admin UI."
    }
} else {
    Warn "No API key entered. You can set it later in $ExistingEnv or via the admin UI."
}

Write-Host '`nNext steps:'
Write-Host '  1. Start server: my-claudecode-server'
Write-Host '  2. Open admin UI (optional): http://127.0.0.1:2424/admin'
Write-Host '  3. New terminal: my-claudecode'
