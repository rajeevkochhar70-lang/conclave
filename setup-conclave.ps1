#Requires -Version 5.1
# CONCLAVE -- standalone setup: own venv, tests, real-data walk-forward.
# USAGE: PowerShell -ExecutionPolicy Bypass -File setup-conclave.ps1
$ErrorActionPreference = "Continue"
$REPO = "C:\Users\Owner\Trading\conclave"
function Head($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Pass($m) { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

Set-Location $REPO
Head "1/5 Python"
$pv = (python --version) 2>&1; Write-Host "  $pv"
Head "2/5 venv"
if (-not (Test-Path ".venv\Scripts\python.exe")) { python -m venv .venv }
$py = ".venv\Scripts\python.exe"
& $py -m pip install -q --upgrade pip
& $py -m pip install -q -r requirements.txt
Pass "deps installed"
Head "3/5 .env"
if (-not (Test-Path ".env")) { Copy-Item .env.example .env; Write-Host "  created .env from template -- add SLACK_WEBHOOK_URL / API keys if wanted" }
Head "4/5 tests"
& $py -m pytest -q tests
Head "5/5 walk-forward on real data (120 trading days, LLM off, no Slack)"
& $py -m conclave simulate --days 120 --no-slack
Write-Host "`nNext: '$py -m conclave scan --no-slack' for this weekend's setups, then setup_task_scheduler.ps1" -ForegroundColor Cyan
