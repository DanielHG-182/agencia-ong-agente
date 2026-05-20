@echo off
title ONG Document Assistant
echo ================================================
echo  ONG Document Assistant
echo ================================================
echo.

:: Activate virtual environment
call .venv\Scripts\activate.bat

:: Start Streamlit
echo Starting app...
echo.
streamlit run app.py

:: Keep window open if error
if errorlevel 1 (
    echo.
    echo ERROR: App failed to start.
    pause
)