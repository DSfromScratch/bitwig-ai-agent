@echo off
:: Install Agent UI CLAP plugin to Windows CLAP directory
:: Run AFTER build_win.bat

setlocal EnableExtensions
cd /d "%~dp0"

set "SRC=build\agent-ui.clap"

if not exist "%SRC%" (
    echo Plugin not found. Run build_win.bat first.
    exit /b 1
)

:: Try user CLAP dir first (no admin needed)
set USER_CLAP=%LOCALAPPDATA%\Programs\Common\CLAP
if not exist "%USER_CLAP%" mkdir "%USER_CLAP%"

copy /y "%SRC%" "%USER_CLAP%\agent-ui.clap" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo ✓ Installed to %USER_CLAP%\agent-ui.clap
    echo Restart Bitwig Studio and rescan plugins ^(Settings ^> Plugins ^> Rescan^).
    exit /b 0
)

:: Fallback: system CLAP dir (needs admin)
set SYS_CLAP=%PROGRAMFILES%\Common Files\CLAP
if not exist "%SYS_CLAP%" mkdir "%SYS_CLAP%" 2>nul

copy /y "%SRC%" "%SYS_CLAP%\agent-ui.clap"
if %ERRORLEVEL% equ 0 (
    echo ✓ Installed to %SYS_CLAP%\agent-ui.clap
    echo Restart Bitwig Studio and rescan plugins.
) else (
    echo ERROR: Could not install. Try running as Administrator.
    exit /b 1
)
