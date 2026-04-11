@echo off
REM Переходим в папку с ботом
cd /d C:\Users\ubiva\OneDrive\Desktop\Proects\EPParserBot

REM Запускаем watchmedo для авто-перезапуска бота
watchmedo auto-restart --patterns="*.py" --recursive -- python main.py

pause