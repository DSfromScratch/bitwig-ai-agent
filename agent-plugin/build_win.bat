@echo off
setlocal EnableExtensions

rem Ultra-simple Windows build script.
rem Run in: x64 Native Tools Command Prompt for Visual Studio.

cd /d "%~dp0"

if not exist "src\plugin_win.cpp" (
	echo ERROR: Source file not found: src\plugin_win.cpp
	exit /b 1
)

where cl >nul 2>&1
if errorlevel 1 (
	echo ERROR: cl.exe not found in PATH.
	echo Open "x64 Native Tools Command Prompt for VS" and run build_win.bat again.
	exit /b 1
)

if not exist build mkdir build

echo Building agent-ui.clap ...
cl /nologo /std:c++20 /O2 /W3 /EHsc /MD /I "clap\include" /I "src" /Fe"build\agent-ui.clap" src\plugin_win.cpp /link /DLL /SUBSYSTEM:WINDOWS user32.lib gdi32.lib comctl32.lib ws2_32.lib /OUT:build\agent-ui.clap

if errorlevel 1 (
	echo BUILD FAILED - check errors above.
	exit /b 1
)

echo Built: build\agent-ui.clap
echo Install with install_win.bat
exit /b 0
