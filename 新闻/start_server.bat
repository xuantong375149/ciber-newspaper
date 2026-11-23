@echo off
rem Start the local news server in the background (http://127.0.0.1:8765/).
cd /d "%~dp0"
start "" pythonw server.py
