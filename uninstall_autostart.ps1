$ErrorActionPreference = "Stop"

$TaskName = "SrunAutoLogin"
$RunValueName = "SrunAutoLogin"
$InstallDir = Join-Path $env:ProgramData "SrunAutoLogin"
$CommonStartup = [Environment]::GetFolderPath("CommonStartup")
$StartupBat = Join-Path $CommonStartup "SrunAutoLogin.bat"

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $RunValueName -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $StartupBat) {
    Remove-Item -LiteralPath $StartupBat -Force
}

if (Test-Path -LiteralPath $InstallDir) {
    Remove-Item -LiteralPath $InstallDir -Recurse -Force
}

Write-Host ""
Write-Host "SrunAutoLogin autostart has been removed."
Write-Host ""
