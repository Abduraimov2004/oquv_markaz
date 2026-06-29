@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate 2>nul

echo.
echo ============================================================
echo  KOMPYUTERDA:  http://127.0.0.1:8000
echo.
echo  TELEFONDA (bir xil WiFi-da) quyidagi manzillardan birini oching:
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do echo     http://%%a:8000
echo ============================================================
echo  (Windows "ruxsat berasizmi" desa -> Allow / Ruxsat bering)
echo  To'xtatish: shu oynada Ctrl+C
echo ============================================================
echo.

uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
