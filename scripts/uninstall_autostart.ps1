# =============================================================================
# MT5 Automated Forex Trading Bot — Uninstall Autostart (Task Scheduler)
# =============================================================================
#
# Removes the Task Scheduler task registered by install_autostart.ps1.
# Also offers guidance to restore netplwiz auto-logon and sleep settings.
#
# USAGE (from PowerShell as Administrator):
#   .\scripts\uninstall_autostart.ps1
#
# Or from a normal PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_autostart.ps1
# =============================================================================

#Requires -Version 5.0

[CmdletBinding()]
param(
    [switch]$Force   # Skip confirmation prompt
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$TaskName = "MT5TradingBot"

Write-Host ""
Write-Host "============================================================"
Write-Host " MT5 Trading Bot — Uninstall Autostart Task"
Write-Host "============================================================"
Write-Host ""

# ---------------------------------------------------------------------------
# Check if the task exists
# ---------------------------------------------------------------------------

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if (-not $task) {
    Write-Host " Task '$TaskName' is not registered — nothing to remove." -ForegroundColor Yellow
    Write-Host ""
    # Check startup folder fallback (legacy)
    $StartupFallback = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\MT5TradingBot_start.bat"
    if (Test-Path $StartupFallback) {
        Write-Host " Found legacy Startup folder shortcut: $StartupFallback"
        if (-not $Force) {
            $yn = Read-Host " Remove it? [y/n]"
            if ($yn -match "^[Yy]") {
                Remove-Item $StartupFallback -Force
                Write-Host " [OK] Startup folder shortcut removed." -ForegroundColor Green
            }
        } else {
            Remove-Item $StartupFallback -Force
            Write-Host " [OK] Startup folder shortcut removed." -ForegroundColor Green
        }
    }
    Write-Host ""
    exit 0
}

# ---------------------------------------------------------------------------
# Confirm removal (unless -Force)
# ---------------------------------------------------------------------------

if (-not $Force) {
    Write-Host " Found scheduled task: $TaskName"
    Write-Host " Status: $($task.State)"
    Write-Host ""
    $yn = Read-Host " Remove this task? [y/n]"
    if ($yn -notmatch "^[Yy]") {
        Write-Host ""
        Write-Host " Cancelled — task not removed."
        Write-Host ""
        exit 0
    }
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Stop running task instance (if any)
# ---------------------------------------------------------------------------

try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Host " [OK] Stopped running task instance." -ForegroundColor Green
}
catch {
    # Task may not be running — not an error
}

# ---------------------------------------------------------------------------
# Unregister the task
# ---------------------------------------------------------------------------

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host " [OK] Task '$TaskName' removed from Task Scheduler." -ForegroundColor Green
}
catch {
    Write-Host "[ERROR] Could not remove task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host " Try running as Administrator if you see an Access Denied error."
    exit 1
}

# ---------------------------------------------------------------------------
# Startup folder fallback cleanup
# ---------------------------------------------------------------------------

$StartupFallback = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\MT5TradingBot_start.bat"
if (Test-Path $StartupFallback) {
    Remove-Item $StartupFallback -Force
    Write-Host " [OK] Startup folder shortcut also removed." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Guidance for remaining manual steps
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "============================================================"
Write-Host " Autostart removed. Additional steps (if you set them up):"
Write-Host "============================================================"
Write-Host ""
Write-Host " 1. Auto-logon (netplwiz):"
Write-Host "    Run: netplwiz"
Write-Host "    Tick 'Users must enter a username and password' → Apply"
Write-Host "    This restores the Windows password prompt on boot."
Write-Host ""
Write-Host " 2. AC sleep timeout:"
Write-Host "    If autostart.bat changed your sleep timeout, restore it with:"
Write-Host "    powercfg /change standby-timeout-ac 30"
Write-Host "    (Replace 30 with your preferred minutes, or use Power Options.)"
Write-Host ""
Write-Host " 3. Fast Startup / Hibernate:"
Write-Host "    If disabled: Control Panel → Power Options → System Settings"
Write-Host "    → Turn on fast startup (recommended) → Save changes."
Write-Host ""
Write-Host " The bot will no longer start automatically on reboot."
Write-Host " Run start_bot.bat manually to start it."
Write-Host ""
Write-Host "============================================================"
Write-Host ""
