@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem auto-detect drive letter
set DRIVE=%~d0
set ROOT=%~dp0

rem find pythonw.exe in <DRIVE>\WinPython\ (recursive)
set PYTHON=
for /f "delims=" %%i in ('dir /b /s "%DRIVE%\WinPython\pythonw.exe" 2^>nul') do (
    set PYTHON=%%i
    goto :found
)

echo [ERROR] Python not found in %DRIVE%\WinPython\
pause
exit /b 1

:found
rem load API key from config\api_key.txt if exists
if exist "%ROOT%config\api_key.txt" (
    set /p APIKEY=<"%ROOT%config\api_key.txt"
    set ANTHROPIC_API_KEY=!APIKEY!
)

start "" "%PYTHON%" "%ROOT%gui.py"
endlocal
