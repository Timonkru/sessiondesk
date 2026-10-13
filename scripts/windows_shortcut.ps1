# Creates a "SessionDesk" shortcut on the Windows desktop.
# Run from the repo root after installing into .venv:   powershell -ExecutionPolicy Bypass -File scripts\windows_shortcut.ps1
# Double-click starts the server (minimized console window - close it to stop SessionDesk) and opens the
# desk in its own app window. Double-clicking again while it runs just reopens the window.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root ".venv\Scripts\sessiondesk.exe"
if (-not (Test-Path $exe)) { throw "Not found: $exe - run 'pip install -e .' inside .venv first." }
$icon = Join-Path $root "sessiondesk\static\sessiondesk.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "SessionDesk.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $exe
$sc.Arguments = "--app"
$sc.WorkingDirectory = $root
$sc.WindowStyle = 7          # minimized console
$sc.IconLocation = "$icon,0"
$sc.Description = "SessionDesk - local market desk"
$sc.Save()
Write-Output "Shortcut created: $link"
