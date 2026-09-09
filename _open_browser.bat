@echo off
rem Waits for the Streamlit server to bind, then opens the browser.
timeout /t 12 /nobreak > nul
start "" http://localhost:8501
