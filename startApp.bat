@echo off
title RAG Proposal Assistant
echo ================================================
echo  RAG Proposal Assistant
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