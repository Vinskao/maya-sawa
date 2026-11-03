@echo off
chcp 65001 >nul
rem Double-click to sign in to the IB gateway (same as: powershell -ExecutionPolicy Bypass -File ibkr-gateway\login.ps1).
rem It opens the tunnel, opens the IB login page, waits while you type your user name and password and approve the
rem 2FA on your phone, starts the market-data session, then closes the tunnel. Nothing is stored.
title IB gateway login
echo IB gateway: opening the login page. Sign in, approve 2FA on your phone, then come back to this window.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0login.ps1" %*
set code=%errorlevel%
echo.
if "%code%"=="0" (echo Done. You can close this window.) else (echo The login did not finish ^(exit code %code%^). Read the message above, then run this file again.)
pause
exit /b %code%
