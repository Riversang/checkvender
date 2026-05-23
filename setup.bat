@echo off
chcp 65001 >nul
setlocal

set DRIVE=%~d0
set ROOT=%~dp0

echo ===== Install dependencies =====
echo Drive: %DRIVE%
echo Project: %ROOT%
echo.

set PYTHON=
for /f "delims=" %%i in ('dir /b /s "%DRIVE%\WinPython\python.exe" 2^>nul') do (
    set PYTHON=%%i
    goto :found
)

echo [ERROR] Python not found in %DRIVE%\WinPython\
pause
exit /b 1

:found
echo Python: %PYTHON%
echo.
"%PYTHON%" -m pip install -r "%ROOT%requirements.txt"
echo.
echo ===== Done! =====
pause
endlocal
