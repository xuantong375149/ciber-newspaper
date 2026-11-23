param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'NewsWebServer.lnk'

if ($Remove) {
    if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force }
    Write-Output "Removed autostart shortcut: $lnkPath"
    exit 0
}

$dir = $PSScriptRoot
$script = Join-Path $dir 'server.py'
if (-not (Test-Path $script)) { throw "server.py not found: $script" }

$python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    $py = (Get-Command python.exe -ErrorAction Stop).Source
    $python = Join-Path (Split-Path $py) 'pythonw.exe'
    if (-not (Test-Path $python)) { $python = $py }
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $python
$lnk.Arguments = '"' + $script + '"'
$lnk.WorkingDirectory = $dir
$lnk.Description = 'Local news web server (127.0.0.1:8765)'
$lnk.Save()

Write-Output ("Autostart shortcut created: {0}" -f $lnkPath)
Write-Output ("Target: {0} `"{1}`"" -f $python, $script)
