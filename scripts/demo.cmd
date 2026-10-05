@echo off
rem Rezhim pokaza na Windows: sobrat' interfeys i zapustit' vsyo odnim processom na http://localhost:8000
rem Internet ne nuzhen. Ostanovka - Ctrl+C.
cd /d "%~dp0..\frontend"
call npm run build
if errorlevel 1 goto err
cd /d "%~dp0..\backend"
echo.
echo   Otkroyte http://localhost:8000 cherez 10-15 sekund
echo.
"%~dp0..\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
goto end
:err
echo Sborka interfeysa ne udalas'. Snachala: cd frontend ^& npm install
:end
pause
