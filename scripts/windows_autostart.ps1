# Starts SessionDesk in the background when you log in to Windows (no window; alerts, push and jobs keep running).
# Install:  powershell -ExecutionPolicy Bypass -File scripts\windows_autostart.ps1
# Remove:   powershell -ExecutionPolicy Bypass -File scripts\windows_autostart.ps1 -Remove
# Open the desk with the desktop shortcut (it attaches to the running server); stop it on the System page
# or with:  .venv\Scripts\sessiondesk.exe --stop
param([switch]$Remove)
$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "SessionDesk (background).lnk"
if ($Remove) {
    if (Test-Path $link) { Remove-Item $link; Write-Output "Autostart removed: $link" } else { Write-Output "No autostart entry found." }
    exit 0
}
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root ".venv\Scripts\sessiondeskw.exe"
if (-not (Test-Path $exe)) { throw "Not found: $exe - run 'pip install -e .' inside .venv first (it creates sessiondeskw.exe)." }
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $exe
$sc.Arguments = "--background"
$sc.WorkingDirectory = $root
$sc.IconLocation = (Join-Path $root "sessiondesk\static\sessiondesk.ico") + ",0"
$sc.Description = "SessionDesk in the background (log: ~/.sessiondesk/logs/server.log)"
$sc.Save()
Write-Output "Autostart created: $link"
