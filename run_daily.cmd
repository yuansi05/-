@echo off
rem GitHub Trending daily fetch. Usage: run_daily.cmd [--lang python] [--since weekly]
setlocal
set "PY=C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0scripts\gh_trending.py" %*
exit /b %ERRORLEVEL%
