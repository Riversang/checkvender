@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set DRIVE=%~d0
set ROOT=%~dp0

set PYTHON=
for /f "delims=" %%i in ('dir /b /s "%DRIVE%\WinPython\python.exe" 2^>nul') do (
    set PYTHON=%%i
    goto :found
)

echo [ERROR] Python not found in %DRIVE%\WinPython\
pause
exit /b 1

:found
if exist "%ROOT%config\api_key.txt" (
    set /p APIKEY=<"%ROOT%config\api_key.txt"
    set ANTHROPIC_API_KEY=!APIKEY!
)

set PYTHONUTF8=1
"%PYTHON%" "%ROOT%main.py" %*
pause
endlocal
