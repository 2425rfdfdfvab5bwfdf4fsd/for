# MT5 Trading Bot — Autostart Setup Guide

This guide covers the one-time Windows configuration steps needed for fully unattended boot-to-trade operation. These are optional — the bot works perfectly without them, but completing all steps means the bot starts automatically after a reboot with no human interaction.

---

## Overview

The boot-to-trade pipeline, once configured, works like this:

```
PC powers on
  → Windows auto-logs in (netplwiz — Step 1)
  → Task Scheduler fires autostart.bat at logon (Step 3)
  → Sleep prevention locks ON (dual-layer)
  → MetaTrader 5 launched automatically (if not running)
  → Bot waits ~120s for MT5 to appear, then 20s login grace
  → python main.py starts (logged to logs\)
  → Telegram receives trade alerts all day
  → Bot exits → original sleep timeout restored automatically
```

No keyboard, no mouse, no manual steps after setup.

---

## Step 1 — Silent Auto-Logon (netplwiz)

**Why:** Task Scheduler fires at logon — but if Windows sits at the password screen, logon never happens. Auto-logon bypasses the cold-boot prompt so the bot can start without human presence.

**Your lock screen password is unchanged** — Win+L still locks the screen normally. Auto-logon only bypasses the cold-boot prompt.

**Setup:**
1. Press `Win + R`, type `netplwiz`, press Enter
2. In the "User Accounts" dialog, select your user account
3. **Untick** "Users must enter a user name and password to use this computer"
4. Click **Apply**
5. Enter your Windows password twice to confirm
6. Click **OK**

**To restore:** Re-open `netplwiz`, tick the checkbox again.

> **Security note:** Any person with physical access to the powered-on PC can access your Windows session without a password. Ensure the PC is in a physically secure location.

---

## Step 2 — Disable Hibernate and Fast Startup

**Why:** Windows Hibernate (S4) is a full RAM-to-disk shutdown. The bot process cannot survive it, even with sleep prevention active. Fast Startup uses hibernate under the hood.

After this step, the only idle state Windows can enter is Sleep (S3), which is fully blocked by the dual-layer sleep prevention in `autostart.bat`.

**Disable Hibernate (run once as Administrator):**
```cmd
powercfg /h off
```

**Disable Fast Startup:**
1. Open **Control Panel** → **Power Options**
2. Click **"Choose what the power buttons do"** (left sidebar)
3. Click **"Change settings that are currently unavailable"**
4. Untick **"Turn on fast startup (recommended)"**
5. Click **Save changes**

**To restore hibernate:**
```cmd
powercfg /h on
```

---

## Step 3 — Register Task Scheduler Entry

The Task Scheduler task runs `autostart.bat` at every logon with these settings:

| Setting | Value | Why |
|---------|-------|-----|
| Trigger | At logon of current user | Fires instantly when Windows session starts |
| Run Level | Highest Privileges | Required for powercfg + MT5 |
| Execution Time Limit | None (PT0S) | Bot runs all day, never auto-killed |
| Restart on Failure | 3 times, 1 minute apart | Recovers from Python crash / MT5 not ready |
| Start When Available | True | Runs ASAP if PC was off at trigger time |
| Multiple Instances | IgnoreNew | Prevents a second bot from launching |

**Install (PowerShell as Administrator):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

**Uninstall:**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1
```

---

## Step 4 — Configure MT5 Terminal Path

Set `MT5_TERMINAL_PATH` in `.env` so `autostart.bat` can launch MT5 automatically:

```ini
# Common paths — find yours by right-clicking the MT5 desktop icon → Properties
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe

# For broker-specific installs:
MT5_TERMINAL_PATH=C:\Program Files\Exness MT5 Terminal\terminal64.exe
```

If not set, the bot starts and retries the MT5 connection — you must launch MT5 manually before the bot's reconnection timeout expires.

---

## Dual-Layer Sleep Prevention

The bot blocks Windows sleep at two independent levels simultaneously:

**Layer 1 — OS Power Settings (`autostart.bat`)**
```cmd
powercfg /change standby-timeout-ac 0
```
- Sets AC sleep to "Never" before the bot starts
- Saves your original setting first and restores it automatically when the bot exits
- If the PC is hard-rebooted mid-run, restore manually:
  ```cmd
  powercfg /change standby-timeout-ac 30
  ```
  (Replace `30` with your preferred timeout in minutes)

**Layer 2 — Kernel-Level Power Request (`scripts/sleep_guard.py`)**
```
SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED)
```
- Calls Windows `kernel32.dll` directly via Python ctypes
- `ES_SYSTEM_REQUIRED` — CPU cannot sleep
- `ES_AWAYMODE_REQUIRED` — blocks sleep even when screen is locked or idle
- Released via `atexit` — restores normal sleep automatically on crash/exception
- Silent no-op on Linux/macOS

**Why two layers?** If the OS setting is changed externally while the bot runs (e.g. Windows Update, Group Policy), Layer 2 still holds. If Layer 2 cannot acquire the kernel lock (rare permissions issue), Layer 1 still protects.

**Verify Layer 2 is active (run in any terminal while bot is running):**
```cmd
powercfg /requests
```
You will see `python.exe` listed under `[SYSTEM]`.

---

## Manual Sleep Restore

If the bot exits unexpectedly and the sleep timeout was not restored:

```cmd
:: Restore to 30-minute timeout (adjust to your preference)
powercfg /change standby-timeout-ac 30

:: Or restore via Power Options GUI:
:: Control Panel → Power Options → Change plan settings → "Put the computer to sleep"
```

---

## Troubleshooting

**Bot doesn't start after reboot:**
- Check `logs\autostart_<date>.log` for error messages
- Verify Task Scheduler task exists: `Get-ScheduledTask -TaskName MT5TradingBot`
- Ensure netplwiz auto-logon is configured (Step 1)

**MT5 doesn't launch automatically:**
- Verify `MT5_TERMINAL_PATH` in `.env` points to the correct executable
- Check that the path exists: `dir "C:\Program Files\MetaTrader 5\terminal64.exe"`

**Task Scheduler fires but bot stops immediately:**
- The task uses `IgnoreNew` — if a previous instance is still running, the new one exits
- Run `stop_bot.bat` first, then the next logon trigger will start fresh
- Check `logs\autostart_<date>.log` for the exit reason

**Sleep prevention not working:**
- Run `powercfg /requests` — if `python.exe` is not listed under `[SYSTEM]`, Layer 2 failed
- Ensure `autostart.bat` has `PREVENT_SLEEP=true` at the top
- Try running `autostart.bat` as Administrator

---

## Uninstalling Everything

1. Stop the bot: `stop_bot.bat`
2. Remove Task Scheduler: `powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1`
3. Restore auto-logon: `netplwiz` → tick the password requirement checkbox
4. Restore hibernate (if disabled): `powercfg /h on`
5. Restore Fast Startup: Control Panel → Power Options → System Settings → tick "Turn on fast startup"
6. Restore sleep timeout: `powercfg /change standby-timeout-ac 30`
