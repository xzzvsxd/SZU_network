# SrunAutoLogin deployment

## Files in the release package

- `SrunAutoLogin.exe` and `_internal/`: packaged onedir app. Keep them together.
- `install_autostart.bat`: one-click installer. It asks for the Srun username and password on the target machine, then writes them to `%ProgramData%\SrunAutoLogin\.env`.
- `uninstall_autostart.bat`: removes the scheduled task, fallback startup entries, installed files, config, credentials, and logs.
- `.env.example`: credential template. Do not put real credentials in the release package.

## Install

1. Copy the whole release folder to the target Windows device.
2. Double-click `install_autostart.bat`.
3. Approve the UAC prompt.
4. Enter the Srun username and password.

The installer creates:

- A `SYSTEM` scheduled task named `SrunAutoLogin`.
- A boot trigger, logon trigger, and network-connected event trigger.
- HKLM Run and common Startup-folder fallbacks.
- Runtime files under `%ProgramData%\SrunAutoLogin`.

The daemon starts immediately after installation, then starts again on boot and when Windows reports a network connection. It uses a 10-second retry interval and keeps retrying while public network access is unavailable.

## Uninstall

Double-click `uninstall_autostart.bat` and approve the UAC prompt.
