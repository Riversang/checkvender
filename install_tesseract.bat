@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

set ROOT=%~dp0
set DRIVE=%~d0
set INSTALL_DIR=%ROOT%tesseract

echo ============================================================
echo   Install Tesseract OCR (Thai+English)
echo ============================================================
echo.
echo This will:
echo   1. Download Tesseract portable to %INSTALL_DIR%
echo   2. Install pytesseract + Pillow into WinPython
echo   3. Tesseract will be auto-detected by pdf_reader.py
echo.
echo Why?
echo   Some vendor PDFs (DBD forms, scanned images) cannot be read
echo   as text. Tesseract OCR (free, local) handles those.
echo.
pause

rem ── 1. Find Python ──────────────────────────────────────────────────
set PYTHON=
for /f "delims=" %%i in ('dir /b /s "%DRIVE%\WinPython\python.exe" 2^>nul') do (
    set PYTHON=%%i
    goto :found_py
)
echo [ERROR] Python not found in %DRIVE%\WinPython\
pause
exit /b 1
:found_py
echo Found Python: %PYTHON%
echo.

rem ── 2. Install pip packages ────────────────────────────────────────
echo Installing pytesseract + Pillow...
"%PYTHON%" -m pip install --upgrade pytesseract Pillow
if errorlevel 1 (
    echo [ERROR] pip install failed
    pause
    exit /b 1
)
echo.

rem ── 3. Check if Tesseract already installed system-wide ────────────
where tesseract >nul 2>&1
if not errorlevel 1 (
    echo Tesseract is already installed system-wide:
    where tesseract
    echo.
    echo Checking Thai language pack...
    tesseract --list-langs 2>nul | findstr /i "tha" >nul
    if not errorlevel 1 (
        echo [OK] Thai language pack found
        goto :done
    ) else (
        echo [WARNING] Thai pack not found - you need to install it manually
        echo Download tha.traineddata from:
        echo   https://github.com/tesseract-ocr/tessdata/raw/main/tha.traineddata
        echo And place in your Tesseract tessdata folder
        goto :done
    )
)

rem ── 4. Check portable install ──────────────────────────────────────
if exist "%INSTALL_DIR%\tesseract.exe" (
    echo Portable Tesseract already exists at:
    echo   %INSTALL_DIR%
    goto :done
)

rem ── 5. Download Tesseract installer ────────────────────────────────
echo.
echo ============================================================
echo   Download Tesseract Installer
echo ============================================================
echo.
echo Tesseract requires manual installation on Windows.
echo.
echo Please:
echo   1. Open this URL in your browser:
echo      https://github.com/UB-Mannheim/tesseract/wiki
echo.
echo   2. Download the latest Windows installer
echo      (e.g. tesseract-ocr-w64-setup-5.x.x.exe)
echo.
echo   3. Run the installer
echo.
echo   4. IMPORTANT: During install, check the checkbox for
echo      "Additional language data" - "Thai"
echo.
echo   5. After install, re-run this batch file to verify
echo.

set /p OPENURL="Open the download page in browser now? (y/N): "
if /i "%OPENURL%"=="y" (
    start "" "https://github.com/UB-Mannheim/tesseract/wiki"
)

:done
echo.
echo ============================================================
echo   Verifying Tesseract installation...
echo ============================================================
echo.
"%PYTHON%" -c "import pytesseract; print('Tesseract version:', pytesseract.get_tesseract_version()); langs = pytesseract.get_languages(); print('Languages:', langs); print('Thai support:', 'tha' in langs)" 2>nul
if errorlevel 1 (
    echo.
    echo [INFO] Tesseract not detected yet.
    echo After installation, the system will auto-detect it.
    echo.
    echo Common install locations checked:
    echo   - C:\Program Files\Tesseract-OCR\tesseract.exe
    echo   - C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
    echo   - %INSTALL_DIR%\tesseract.exe
) else (
    echo.
    echo [SUCCESS] Tesseract OCR is ready!
    echo You can now run gui.bat - it will auto-OCR garbled PDFs
)
echo.
pause
endlocal
