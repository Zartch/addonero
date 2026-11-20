@echo off
rem Oroboros: procesar ahora (exportar, archivo, plan y Resumen.lua) y ver el resultado.
rem Uso: oroboros_procesar.bat --find "<carpeta de WoW Forever>"
python "%~dp0oroboros_watch.py" %* --once
echo.
pause
