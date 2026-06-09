$ErrorActionPreference = "Stop"

$TaskName = "SrunAutoLogin"
$RunValueName = "SrunAutoLogin"
$InstallDir = Join-Path $env:ProgramData "SrunAutoLogin"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ExeSource = Join-Path $SourceDir "SrunAutoLogin.exe"
$InternalSource = Join-Path $SourceDir "_internal"
$ExeTarget = Join-Path $InstallDir "SrunAutoLogin.exe"
$DefaultServerUrl = "https://net.szu.edu.cn"

if (-not (Test-Path -LiteralPath $ExeSource)) {
    throw "SrunAutoLogin.exe was not found next to this installer."
}
if (-not (Test-Path -LiteralPath $InternalSource)) {
    throw "_internal runtime folder was not found next to this installer."
}

function Convert-PlainText {
    param([Security.SecureString]$SecureValue)

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

function Format-EnvValue {
    param([string]$Value)

    if ($null -eq $Value) {
        return '""'
    }

    $escaped = $Value.Replace('\', '\\').Replace('"', '\"')
    return '"' + $escaped + '"'
}

Write-Host ""
Write-Host "SrunAutoLogin installer"
Write-Host "The app will be installed to: $InstallDir"
Write-Host ""

$Username = Read-Host "Srun username"
$PasswordSecure = Read-Host "Srun password" -AsSecureString
$Password = Convert-PlainText $PasswordSecure
$ServerUrl = Read-Host "Server URL [$DefaultServerUrl]"
if ([string]::IsNullOrWhiteSpace($ServerUrl)) {
    $ServerUrl = $DefaultServerUrl
}

if ([string]::IsNullOrWhiteSpace($Username) -or [string]::IsNullOrWhiteSpace($Password)) {
    throw "Username and password cannot be empty."
}

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Get-ChildItem -LiteralPath $InstallDir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notin @(".env", "srun_autologin.log") } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item -LiteralPath $ExeSource -Destination $ExeTarget -Force
Copy-Item -LiteralPath $InternalSource -Destination $InstallDir -Recurse -Force

try {
    $account = "$env:USERDOMAIN\$env:USERNAME"
    $acl = Get-Acl -LiteralPath $InstallDir
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $account,
        "Modify",
        "ContainerInherit,ObjectInherit",
        "None",
        "Allow"
    )
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $InstallDir -AclObject $acl
}
catch {
}

$EnvLines = @(
    "SRUN_USERNAME=$(Format-EnvValue $Username)",
    "SRUN_PASSWORD=$(Format-EnvValue $Password)",
    "SRUN_SERVER_URL=$(Format-EnvValue $ServerUrl)"
)
Set-Content -LiteralPath (Join-Path $InstallDir ".env") -Value $EnvLines -Encoding UTF8

$Config = [ordered]@{
    username = ""
    password = ""
    auto_start = $true
    check_interval = 10
    theme = "system"
    server_url = $ServerUrl
}
$Config | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $InstallDir "srun_config.json") -Encoding UTF8

try {
    wevtutil sl Microsoft-Windows-NetworkProfile/Operational /e:true | Out-Null
}
catch {
    Write-Host "NetworkProfile event log could not be enabled; continuing."
}

$ExeEscaped = [Security.SecurityElement]::Escape($ExeTarget)
$InstallDirEscaped = [Security.SecurityElement]::Escape($InstallDir)
$EventSubscription = "<QueryList><Query Id='0' Path='Microsoft-Windows-NetworkProfile/Operational'><Select Path='Microsoft-Windows-NetworkProfile/Operational'>*[System[Provider[@Name='Microsoft-Windows-NetworkProfile'] and EventID=10000]]</Select></Query></QueryList>"
$EventSubscriptionEscaped = [Security.SecurityElement]::Escape($EventSubscription)

$TaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Srun campus network auto login daemon.</Description>
  </RegistrationInfo>
  <Triggers>
    <BootTrigger>
      <Enabled>true</Enabled>
    </BootTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>$EventSubscriptionEscaped</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>S-1-5-18</UserId>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>4</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$ExeEscaped</Command>
      <Arguments>--daemon --interval 10</Arguments>
      <WorkingDirectory>$InstallDirEscaped</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml -Force | Out-Null

$RunCommand = '"' + $ExeTarget + '" --daemon --interval 10'
New-Item -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Force | Out-Null
New-ItemProperty -Path "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run" -Name $RunValueName -PropertyType String -Value $RunCommand -Force | Out-Null

$CommonStartup = [Environment]::GetFolderPath("CommonStartup")
$StartupBat = Join-Path $CommonStartup "SrunAutoLogin.bat"
$StartupBatContent = @"
@echo off
cd /d "$InstallDir"
start "" "$ExeTarget" --daemon --interval 10
"@
Set-Content -LiteralPath $StartupBat -Value $StartupBatContent -Encoding ASCII

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "Installed."
Write-Host "Scheduled task: $TaskName"
Write-Host "Fallback registry: HKLM\Software\Microsoft\Windows\CurrentVersion\Run\$RunValueName"
Write-Host "Fallback startup script: $StartupBat"
Write-Host "Runtime log: $(Join-Path $InstallDir 'srun_autologin.log')"
Write-Host ""
