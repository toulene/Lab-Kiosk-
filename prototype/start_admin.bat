@echo off
rem Starts the kiosk admin website and opens it in the browser. Keep this window open during the demo.
title Lab Kiosk Admin
cd /d "%~dp0"
start "" http://localhost:5050
py admin_server.py
pause
