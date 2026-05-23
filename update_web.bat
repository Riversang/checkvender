@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ============================================================
echo   Update website on Streamlit Cloud
echo ============================================================
echo.

rem check if git repo
if not exist ".git\" (
    echo [ERROR] This is not a git repo
    pause
    exit /b 1
)

rem show what changed
echo Changed files:
echo -------------------------------------------------------
git status --short
echo -------------------------------------------------------
echo.

rem any changes?
git diff --quiet
if not errorlevel 1 (
    git diff --cached --quiet
    if not errorlevel 1 (
        echo No changes to push. Nothing to do.
        pause
        exit /b 0
    )
)

rem ask for commit message
set /p MSG="Describe what you changed (or press Enter for 'update'): "
if "%MSG%"=="" set MSG=update

echo.
echo Pushing to GitHub...
echo.

git add .
git commit -m "%MSG%"
git push

echo.
echo ============================================================
echo   Done! Streamlit Cloud will auto-rebuild in 2-3 minutes
echo   Check status at: https://share.streamlit.io
echo ============================================================
echo.
pause
endlocal
