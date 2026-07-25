# =============================================================================
# MT5 Automated Forex Trading Bot — Install Autostart (Task Scheduler)
# =============================================================================
#
# Registers autostart.bat as a Windows Task Scheduler task that fires
# automatically at every logon of the current user.
#
# Task settings:
#   Trigger:              At logon of current user
#   Run Level:            Highest privileges (required for powercfg + MT5)
#   Execution Time Limit: None — bot runs all day, never auto-killed
#   Restart on Failure:   3 times, 1 minute apart
#   Start When Available: Yes — runs ASAP if PC was off at trigger time
#   Multiple Instances:   IgnoreNew — only one bot instance allowed
#   Working Directory:    Project root (auto-resolved from this script's path)
#
# USAGE (from PowerShell as Administrator):
#   .\scripts\install_autostart.ps1
#
# Or from a normal PowerShell (will prompt for elevation):
#   powershell -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1
# =============================================================================

#Requires -Version 5.0

[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

$TaskName        = "MT5TradingBot"
$TaskDescription = "MT5 Automated Forex Trading Bot — auto-starts at logon"
$ScriptDir       = Split-Path -Parent $PSScriptRoot   # Project root
$AutostartBat    = Join-Path $ScriptDir "autostart.bat"

# ---------------------------------------------------------------------------
# Verify autostart.bat exists
# ---------------------------------------------------------------------------

if (-not (Test-Path $AutostartBat)) {
    Write-Host ""
    Write-Host "[ERROR] autostart.bat not found at: $AutostartBat" -ForegroundColor Red
    Write-Host "        Ensure you are running this script from the project root." -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "============================================================"
Write-Host " MT5 Trading Bot — Install Autostart Task"
Write-Host "============================================================"
Write-Host ""
Write-Host " Task name:   $TaskName"
Write-Host " Launcher:    $AutostartBat"
Write-Host " Working dir: $ScriptDir"
Write-Host ""

# ---------------------------------------------------------------------------
# Remove existing task if present (idempotent install)
# ---------------------------------------------------------------------------

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host " Removing existing task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ---------------------------------------------------------------------------
# Build Task Scheduler XML
# ---------------------------------------------------------------------------
# Using XML is more reliable than schtasks.exe /Create for advanced settings:
#   - ExecutionTimeLimit PT0S = No limit (bot runs all day)
#   - RestartOnFailure: 3 retries, 1-minute interval
#   - StartWhenAvailable: true — fires ASAP if PC was off at trigger time
#   - MultipleInstancesPolicy: IgnoreNew — prevents double-launch

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$TaskXml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>$TaskDescription</Description>
    <Author>$CurrentUser</Author>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$CurrentUser</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$CurrentUser</UserId>
      <LogonType>InteractiveToken</LogonType>
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
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$AutostartBat</Command>
      <WorkingDirectory>$ScriptDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

# ---------------------------------------------------------------------------
# Register the task
# ---------------------------------------------------------------------------

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Xml $TaskXml `
        -Force | Out-Null

    Write-Host " [OK] Task '$TaskName' registered successfully." -ForegroundColor Green
    Write-Host ""
    Write-Host " Settings applied:"
    Write-Host "   Trigger:              At logon of $CurrentUser"
    Write-Host "   Run Level:            Highest Available (for powercfg + MT5)"
    Write-Host "   Execution Limit:      None (runs all day)"
    Write-Host "   Restart on Failure:   3 times, 1 minute apart"
    Write-Host "   Start When Available: Yes"
    Write-Host "   Multiple Instances:   IgnoreNew"
    Write-Host ""
    Write-Host " Next steps:"
    Write-Host "   1. Reboot to test — the bot will start automatically."
    Write-Host "   2. Use stop_bot.bat to stop the bot manually."
    Write-Host "   3. To remove: run scripts\uninstall_autostart.ps1"
    Write-Host ""
    Write-Host "============================================================"
    Write-Host ""
}
catch {
    Write-Host ""
    Write-Host "[ERROR] Failed to register task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host " If you see an 'Access Denied' error, run PowerShell as Administrator."
    Write-Host " Right-click PowerShell → 'Run as Administrator', then retry."
    Write-Host ""
    exit 1
}
