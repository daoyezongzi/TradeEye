@echo off
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
  set "PYTHON=%VENV_PY%"
) else (
  set "PYTHON=python"
)

set "JOB=%~1"
if "%JOB%"=="" set "JOB=analysis"

if /I "%JOB%"=="analysis" goto run_analysis
if /I "%JOB%"=="recommend" goto run_recommend
if /I "%JOB%"=="news" goto run_news

echo Usage: %~nx0 ^<analysis^|recommend^|news^>
goto end

:run_analysis
"%PYTHON%" "%ROOT%main.py"
goto end

:run_recommend
"%PYTHON%" "%ROOT%recommend_main.py"
goto end

:run_news
"%PYTHON%" "%ROOT%news_main.py"
goto end

:end
exit /b %errorlevel%
