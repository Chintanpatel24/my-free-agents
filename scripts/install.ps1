param(
  [string]$InstallDir = "$env:USERPROFILE\.my-free-agents\claudecode",
  [string]$BinDir = "$env:USERPROFILE\.my-free-agents\bin",
  [string]$Python = "python",
  [switch]$NoPath
)
$ErrorActionPreference = 'Stop'
function Say($m) { Write-Host $m -ForegroundColor Green }
function Warn($m) { Write-Host $m -ForegroundColor Yellow }
function Fail($m) { Write-Host $m -ForegroundColor Red; exit 1 }

$OldInstallDir = "$env:USERPROFILE\.free-claude-code\app"

if ([string]::IsNullOrWhiteSpace($InstallDir) -or $InstallDir -eq '\' -or $InstallDir -eq $env:USERPROFILE) {
    Fail "Refusing unsafe install directory: $InstallDir"
}

try { $version = & $Python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" } catch { Fail 'Python 3.10+ is required.' }
$majorMinor = & $Python -c "import sys; print(1 if sys.version_info >= (3,10) else 0)"
if ($majorMinor.Trim() -ne '1') { Fail "Python 3.10+ is required. Found $version" }

# Check for Claude Code
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Warn "Claude Code CLI ('claude' command) not found. Please install it first for the best experience."
    Warn "You can install it with: npm install -g @anthropic-ai/claude-code"
    $ContinueInstall = Read-Host "`nDo you want to continue anyway? (y/N)"
    if ($ContinueInstall -notmatch "^[Yy]$") {
        Say "Installation cancelled."
        exit 0
    }
}

# Check for httpx
Say "Checking Python HTTP dependency (httpx)..."
$HasDeps = ((& $Python -c "import httpx; print(1)" 2>$null) -join '')
if ($HasDeps.Trim() -ne '1') {
    Warn "Missing httpx for Python. It is required for the proxy."
    $InstallDeps = Read-Host "`nWould you like to install it now? (y/N)"
    if ($InstallDeps -match "^[Yy]$") {
        try {
            & $Python -m pip install "httpx"
        } catch {
            Warn "Failed to install dependencies automatically. Please run: $Python -m pip install httpx"
        }
    } else {
        Warn "Skipping dependency installation. Note that the server may not work correctly without them."
    }
}
$HasH2 = ((& $Python -c "import h2; print(1)" 2>$null) -join '')
if ($HasH2.Trim() -ne '1') {
    Warn "Optional HTTP/2 package h2 is not installed. That is OK; HTTP/1.1 is the fast default."
}

# Migration logic
if ((Test-Path $OldInstallDir) -and -not (Test-Path $InstallDir)) {
    Say "Migrating existing installation from $OldInstallDir to $InstallDir..."
    $ParentDir = Split-Path $InstallDir -Parent
    if (-not (Test-Path $ParentDir)) { New-Item -ItemType Directory -Force -Path $ParentDir | Out-Null }
    Copy-Item -Path $OldInstallDir -Destination $InstallDir -Recurse -Force
    Warn "Migration complete. You may want to remove $OldInstallDir manually later."
}

# Clean up old package name if it exists to avoid conflicts
$OldPackagePath = Join-Path $InstallDir 'free_claude_code'
if (Test-Path $OldPackagePath) {
    Remove-Item -Path $OldPackagePath -Recurse -Force -ErrorAction SilentlyContinue
}

$SrcDir = Resolve-Path (Join-Path $PSScriptRoot '..')
Say 'Installing My Free Agents safely for the current user...'
New-Item -ItemType Directory -Force -Path $InstallDir, $BinDir | Out-Null
$ExistingEnv = Join-Path $InstallDir '.env'
$SavedEnv = $null
if (Test-Path $ExistingEnv) { $SavedEnv = Get-Content $ExistingEnv -Raw }
Get-ChildItem -Path $InstallDir -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$exclude = @('.git','.env','__pycache__','.venv','dist','build')
Get-ChildItem -Path $SrcDir -Force | ForEach-Object { if ($exclude -notcontains $_.Name -and -not $_.Name.EndsWith('.egg-info')) { Copy-Item $_.FullName -Destination $InstallDir -Recurse -Force } }
if ($SavedEnv) { Set-Content -Path $ExistingEnv -Value $SavedEnv -Encoding UTF8 }

# Remove old command names to avoid confusion.
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $BinDir 'my-free-claudecode.cmd'), (Join-Path $BinDir 'my-free-claudecode.ps1'), (Join-Path $BinDir 'my-claudecode-server.cmd'), (Join-Path $BinDir 'my-claudecode-server.ps1'), (Join-Path $BinDir 'my-server-claudecode.cmd'), (Join-Path $BinDir 'my-server-claudecode.ps1')

$shimCmd1 = Join-Path $BinDir 'start-claudecode-server.cmd'
$shimCmd2 = Join-Path $BinDir 'my-claudecode.cmd'
$shimPs1A = Join-Path $BinDir 'start-claudecode-server.ps1'
$shimPs1B = Join-Path $BinDir 'my-claudecode.ps1'
$EscInstallDir = $InstallDir.Replace("'", "''")
$EscPython = $Python.Replace("'", "''")

Set-Content -Path $shimCmd1 -Encoding ASCII -Value "@echo off`r`nset `"MY_FREE_AGENTS_HOME=$InstallDir`"`r`nset `"PYTHONPATH=$InstallDir;%PYTHONPATH%`"`r`n`"$Python`" -c `"from my_claudecode_python.cli import main_server; main_server()`" %*`r`n"
Set-Content -Path $shimCmd2 -Encoding ASCII -Value "@echo off`r`nset `"MY_FREE_AGENTS_HOME=$InstallDir`"`r`nset `"PYTHONPATH=$InstallDir;%PYTHONPATH%`"`r`n`"$Python`" -c `"from my_claudecode_python.cli import main_claude; main_claude()`" %*`r`n"
Set-Content -Path $shimPs1A -Encoding UTF8 -Value "`$env:MY_FREE_AGENTS_HOME='$EscInstallDir'`n`$env:PYTHONPATH='$EscInstallDir;' + `$env:PYTHONPATH`n& '$EscPython' -c 'from my_claudecode_python.cli import main_server; main_server()' @args`n"
Set-Content -Path $shimPs1B -Encoding UTF8 -Value "`$env:MY_FREE_AGENTS_HOME='$EscInstallDir'`n`$env:PYTHONPATH='$EscInstallDir;' + `$env:PYTHONPATH`n& '$EscPython' -c 'from my_claudecode_python.cli import main_claude; main_claude()' @args`n"

$env:MY_FREE_AGENTS_HOME = $InstallDir
$env:PYTHONPATH = "$InstallDir;$env:PYTHONPATH"
& $Python -c "from my_claudecode_python.config import ensure_env, write_env_values; ensure_env(); write_env_values({}); print(ensure_env())" | Out-Null

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

# Check if API key already exists
$ExistingApiKey = ""
if (Test-Path $ExistingEnv) {
    $content = Get-Content $ExistingEnv
    foreach ($line in $content) {
        if ($line -match "^NVIDIA_NIM_API=(.*)") {
            $ExistingApiKey = $Matches[1].Trim()
            break
        }
    }
}

if ($ExistingApiKey -and $ExistingApiKey -ne "your-api-key") {
    Say "Existing API key found. Skipping prompt."
    $UserApiKey = $ExistingApiKey
} else {
    # Prompt for API Key
    if ($null -eq (Get-Variable Host -ErrorAction SilentlyContinue)) {
        $UserApiKey = [Console]::ReadLine()
    } else {
        $UserApiKey = Read-Host "`nPlease enter your NVIDIA NIM API key (Press Enter to skip and do it manually later)"
    }
}

if ($UserApiKey -and $UserApiKey -ne $ExistingApiKey) {
    Say "Validating API key..."
    try {
        $headers = @{ "Authorization" = "Bearer $UserApiKey" }
        $resp = Invoke-WebRequest -Uri "https://integrate.api.nvidia.com/v1/models" -Headers $headers -Method Get -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $env:MY_FREE_AGENTS_API_KEY = $UserApiKey
            & $Python -c "import os; from my_claudecode_python.config import write_env_values; write_env_values({'NVIDIA_NIM_API': os.environ['MY_FREE_AGENTS_API_KEY']})"
            Remove-Item Env:\MY_FREE_AGENTS_API_KEY -ErrorAction SilentlyContinue
            Say "API key validated and saved."
        }
    } catch {
        Warn "API key validation failed. You can set it later in $ExistingEnv or via the admin UI."
    }
} elseif (-not $UserApiKey) {
    Warn "No API key entered. You can set it later in $ExistingEnv or via the admin UI."
}

Write-Host "`nNext steps:"
Write-Host "  1. Start server: start-claudecode-server"
Write-Host "  2. Open admin UI (optional): http://127.0.0.1:2424/admin"
Write-Host "  3. New terminal: my-claudecode"
