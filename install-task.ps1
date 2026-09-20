param([string]$Time = '09:00', [string]$Python = '')
$ErrorActionPreference = 'Stop'
if (-not $Python) {
    $venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venvPython) {
        $Python = $venvPython
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = (& py -3 -c 'import sys; print(sys.executable)').Trim()
    } elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        $Python = (& python.exe -c 'import sys; print(sys.executable)').Trim()
    }
}
if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Python executable not found. Supply -Python or create .venv.' }
$windowlessPython = Join-Path (Split-Path -Parent $Python) 'pythonw.exe'
if (Test-Path -LiteralPath $windowlessPython) { $Python = $windowlessPython }
$scriptPath = Join-Path $PSScriptRoot 'checkin.py'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $Python -Argument ('"' + $scriptPath + '"') -WorkingDirectory $PSScriptRoot
$daily = New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($Time, 'HH:mm', $null))
$logon = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 15) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'AbleSci-HTTP-Checkin' -Action $action -Trigger @($daily, $logon) -Principal $principal -Settings $settings -Description 'Standalone HTTP check-in; same Windows user required.' -Force | Out-Null
Write-Output ('Installed AbleSci-HTTP-Checkin at ' + $Time + ' (Windows local time), plus logon.')
