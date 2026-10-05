@echo off
rem Zapusk na Windows: dvoynoy shchelchok ili "scripts\dev.cmd" iz kornya proekta.
rem Obkhodit zapret na zapusk stsenariev PowerShell (ExecutionPolicy) tol'ko dlya etogo zapuska.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1"
pause
