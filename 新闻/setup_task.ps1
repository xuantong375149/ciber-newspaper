param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$taskName = 'NewsDailyUpdate'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Output "Removed scheduled task: $taskName"
    exit 0
}

$dir = $PSScriptRoot
$script = Join-Path $dir 'fetch_news.py'
if (-not (Test-Path $script)) { throw "fetch_news.py not found next to this script: $script" }

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) { throw 'python.exe not found in PATH' }
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { $pythonw = $python }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + $script + '"') -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At '07:30'),
    (New-ScheduledTaskTrigger -Daily -At '19:30')
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings `
    -Description 'Fetch BBC/CNN and other RSS news, build the local daily news page' -Force | Out-Null

$task = Get-ScheduledTask -TaskName $taskName
Write-Output ("Registered: {0} ({1})" -f $task.TaskName, $task.State)
Write-Output ("Action: {0} `"{1}`"" -f $pythonw, $script)
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Output ("Next run: {0}" -f $info.NextRunTime)
