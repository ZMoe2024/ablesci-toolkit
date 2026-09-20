$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'AbleSci-HTTP-Checkin' -ErrorAction SilentlyContinue
if ($task) { Unregister-ScheduledTask -TaskName 'AbleSci-HTTP-Checkin' -Confirm:$false }
Write-Output 'AbleSci-HTTP-Checkin removed.'
