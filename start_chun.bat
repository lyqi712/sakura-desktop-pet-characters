@echo off
chcp 65001 > nul
set "PRJ_ROOT=%~dp0"
set "SAKURA_PRJ_ROOT=%PRJ_ROOT%"
set "SAKURA_PET_ID=chun"
set "SAKURA_CHARACTER_ID=chun"
set "SAKURA_DATA_DIR=%PRJ_ROOT%data\pets\chun"

REM Check non-ASCII path (PySide6 crashes under non-English paths)
powershell -NoProfile -Command "$path = $env:SAKURA_PRJ_ROOT; if ($path -match '[^\x20-\x7E]') { exit 1 } else { exit 0 }" > nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "$path = $env:SAKURA_PRJ_ROOT; Write-Host '[ERROR] Project path contains non-English chars; PySide6 cannot start'; Write-Host '        Move project to an ASCII path, e.g. D:\sakura'; Write-Host ('        Current path: ' + $path)"
    pause
    exit /b 1
)

REM Use only runtime/python.exe
if exist "%PRJ_ROOT%runtime\python.exe" (
    set "PYTHON_EXE=%PRJ_ROOT%runtime\python.exe"
) else (
    echo [ERROR] runtime\python.exe not found
    echo.
    echo Please install Python environment first:
    echo   1. Download Python 3.11 embedded or use virtualenv
    echo   2. Place python.exe in runtime\ directory
    echo   3. Install dependencies: runtime\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM Embedding model cache lives in data\runtime\hf-cache; HF_HOME must align,
REM otherwise offline cache miss triggers network download + timeout.
set "HF_HOME=%PRJ_ROOT%data\runtime\hf-cache"
set "SENTENCE_TRANSFORMERS_HOME=%PRJ_ROOT%data\runtime\hf-cache"
set "HF_HUB_OFFLINE=1"
set "TRANSFORMERS_OFFLINE=1"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"
if not exist "%SAKURA_DATA_DIR%" mkdir "%SAKURA_DATA_DIR%"

cd /d "%PRJ_ROOT%"
"%PYTHON_EXE%" main.py --pet-id chun --character-id chun --data-dir "%SAKURA_DATA_DIR%"
pause
