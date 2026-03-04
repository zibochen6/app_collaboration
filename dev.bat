@echo off
setlocal enabledelayedexpansion

:: Provisioning Station - Development Mode with Hot Reload
:: Builds frontend then runs backend with --reload

set BACKEND_PORT=3260
set PROJECT_DIR=%~dp0

echo ==========================================
echo   Provisioning Station - Dev Mode
echo ==========================================
echo.

:: Check dependencies
echo [1/5] Checking dependencies...

where uv >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: uv is not installed
    exit /b 1
)

where npm >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo Error: npm is not installed
    exit /b 1
)

:: Sync Python dependencies
echo [2/5] Syncing Python dependencies...
cd /d "%PROJECT_DIR%"
uv sync --quiet
if %ERRORLEVEL% neq 0 (
    echo Error: Failed to sync Python dependencies
    exit /b 1
)

:: Install frontend dependencies if needed
echo [3/5] Checking frontend dependencies...
cd /d "%PROJECT_DIR%frontend"
if not exist "node_modules" (
    echo Installing npm packages...
    npm install --silent
)

:: Cleanup leftover processes on port
echo [4/5] Checking ports...
cd /d "%PROJECT_DIR%"
uv run python scripts/port_cleanup.py %BACKEND_PORT%
if %ERRORLEVEL% neq 0 (
    echo Warning: Port may still be in use
    echo If startup fails, manually kill the blocking process or use a different port.
    timeout /t 2 /nobreak >nul
)

:: Build frontend
echo [5/5] Building frontend...
cd /d "%PROJECT_DIR%frontend"
npm run build
if %ERRORLEVEL% neq 0 (
    echo Error: Frontend build failed
    exit /b 1
)

:: Start backend with hot reload
cd /d "%PROJECT_DIR%"
echo.
echo ==========================================
echo   Provisioning Station is running!
echo.
echo   Open: http://localhost:%BACKEND_PORT%
echo.
echo   Backend hot reload enabled.
echo   Frontend changes require re-run.
echo   Press Ctrl+C to stop
echo ==========================================
echo.

uv run uvicorn provisioning_station.main:app --host 0.0.0.0 --port %BACKEND_PORT% --reload --loop asyncio

endlocal
