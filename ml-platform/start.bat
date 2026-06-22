@echo off
echo ============================================
echo   ML Platform - Starting Services
echo ============================================
echo.
echo Starting Backend (FastAPI on port 8000)...
start \"ML Backend\" cmd /c \"cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload\"
echo.
echo Starting Frontend (Vite on port 5173)...
start \"ML Frontend\" cmd /c \"cd frontend && npm run dev\"
echo.
echo ============================================
echo   Backend:  http://localhost:8000/docs
echo   Frontend: http://localhost:5173
echo.
echo   Login: admin / admin123
echo ============================================
echo.
pause
