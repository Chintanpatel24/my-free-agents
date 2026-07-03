$ErrorActionPreference = 'Stop'
$Root = Resolve-Path (Join-Path $PSScriptRoot '..')
Push-Location $Root
try {
  python -m compileall -q free_claude_code
  $env:PYTHONPATH = "$Root;$env:PYTHONPATH"
  python -m unittest discover -s tests -p 'test_*.py'
  python tests/smoke_proxy.py
  Write-Host 'All verification checks passed.' -ForegroundColor Green
} finally {
  Pop-Location
}
