@echo off
cd /d "%~dp0"

echo.
echo  ====================================================
echo   Pharma-DMF Linker  -  DMF Monitoring System
echo  ====================================================
echo.
echo   URL : http://localhost:8501
echo   Stop: press Ctrl+C in this window
echo.
echo  Starting server... the browser opens in a few seconds.
echo.

start "" /min "%~dp0_open_browser.bat"
python -m streamlit run app.py

echo.
echo  Server stopped (exit code %errorlevel%).
pause
