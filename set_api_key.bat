@echo off
chcp 65001 >nul
setlocal

set ROOT=%~dp0
set KEY_FILE=%ROOT%config\api_key.txt

echo ============================================================
echo   Set Anthropic API Key (for Claude Vision PDF reading)
echo ============================================================
echo.
echo Key will be saved at: %KEY_FILE%
echo (stored on HDD, travels with the drive)
echo.

if exist "%KEY_FILE%" (
    echo An API key already exists.
    set /p REPLACE="Type y to replace, anything else to cancel: "
    if /i not "!REPLACE!"=="y" (
        echo Cancelled
        pause
        exit /b 0
    )
)

echo.
echo Get your API key from: https://console.anthropic.com/settings/keys
echo (format: sk-ant-xxxxxxxxxxxx...)
echo.
set /p APIKEY="Paste your API key here: "

if "%APIKEY%"=="" (
    echo Cancelled (no key entered)
    pause
    exit /b 0
)

if not exist "%ROOT%config\" mkdir "%ROOT%config\"
> "%KEY_FILE%" echo %APIKEY%

echo.
echo OK - API key saved
echo   %KEY_FILE%
echo.
echo Now gui.bat or run.bat will use Claude Vision automatically
echo for PDFs that can't be read as text.
echo.
pause
endlocal
