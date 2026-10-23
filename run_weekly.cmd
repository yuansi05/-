@echo off
rem GitHub Trending weekly report. Usage: run_weekly.cmd [--days 7]
setlocal
set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0scripts\weekly_report.py" %*
exit /b %ERRORLEVEL%
