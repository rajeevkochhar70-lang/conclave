# CONCLAVE -- register main.py (APScheduler: Mon-Fri 13:30 PT book update, Tue/Sat 19:30 PT scan) at logon.
$ErrorActionPreference = "Stop"
$ProjectDir = "C:\Users\Owner\Trading\conclave"
$PythonExe  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectDir "main.py"
foreach ($p in @($PythonExe, $ScriptPath, (Join-Path $ProjectDir ".env"))) {
    if (-not (Test-Path $p)) { Write-Error "[FATAL] missing $p (run setup-conclave.ps1 first)"; exit 1 } }
$TaskName = "CONCLAVE-Scheduler"
$Action   = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`"" -WorkingDirectory $ProjectDir
$Trigger  = New-ScheduledTaskTrigger -AtLogon -User "$env:USERDOMAIN\$env:USERNAME"  # own-logon trigger: no admin needed
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -ExecutionTimeLimit (New-TimeSpan -Hours 0)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description "CONCLAVE paper-trading desk scheduler. Paper only; no broker connection." | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "[OK] $TaskName registered and started. Log: $ProjectDir\logs\conclave.log"
