@echo off
setlocal

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
pushd "%ROOT%" || exit /b 1

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
if /I "%JOB%"=="backtest" goto run_backtest
if /I "%JOB%"=="settle" goto run_settle
if /I "%JOB%"=="evening" goto run_evening

echo Usage: %~nx0 ^<analysis^|recommend^|news^|backtest^|settle^|evening^>
set "EXIT_CODE=2"
goto end

:run_analysis
"%PYTHON%" "%ROOT%main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:run_recommend
"%PYTHON%" "%ROOT%recommend_main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:run_news
"%PYTHON%" "%ROOT%news_main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:run_backtest
"%PYTHON%" "%ROOT%backtest_main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:run_settle
"%PYTHON%" "%ROOT%portfolio_main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:run_evening
"%PYTHON%" "%ROOT%portfolio_main.py"
if errorlevel 1 (
  set "EXIT_CODE=%ERRORLEVEL%"
  goto end
)
"%PYTHON%" "%ROOT%main.py"
set "EXIT_CODE=%ERRORLEVEL%"
goto end

:end
popd
exit /b %EXIT_CODE%
