@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate 2>nul
echo Telegram bot ishga tushyapti... (to'xtatish: Ctrl+C)
python -m bot.bot
pause
