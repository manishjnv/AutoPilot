@echo off
REM Autopilot installer for CMD: starts the PowerShell installer (install.ps1) with the same options.
REM Options: -DryRun, -SkipLogin, -Runner NAME, -Yes. Downloads install.ps1 when it is not next to this file.
setlocal
set "PS1=%~dp0install.ps1"
if not exist "%PS1%" (
  set "PS1=%TEMP%\autopilot-install.ps1"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/manishjnv/AutoPilot/main/install.ps1 -OutFile '%TEMP%\autopilot-install.ps1'" || exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
exit /b %ERRORLEVEL%
