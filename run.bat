@echo off
rem pythonw.exe = no console window. Change pythonw to python to see errors.
rem Keep this file ASCII-only: cmd reads .bat in the OEM codepage (cp950),
rem so UTF-8 Chinese comments get mis-parsed as commands.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0typeless.py"
