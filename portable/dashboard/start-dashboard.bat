@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   MOD_CTRL Dashboard - Windows launcher
echo ==========================================

if not exist backend\.env (
    echo.
    echo ERROR: backend\.env is missing.
    echo Please copy backend\.env.example to backend\.env and fill in MONGO_URL.
    pause
    exit /b 1
)

start "MOD_CTRL backend" cmd /k "cd backend && python -m uvicorn server:app --host 0.0.0.0 --port 8001 --reload"
timeout /t 3 /nobreak >nul
start "MOD_CTRL frontend" cmd /k "cd frontend && yarn start"
timeout /t 5 /nobreak >nul
start "" http://localhost:3000

echo.
echo Backend on http://localhost:8001
echo Frontend on http://localhost:3000
echo Close the two terminal windows when finished.
