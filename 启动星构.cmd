@echo off
setlocal
cd /d "%~dp0"
set "XINGGOU_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%XINGGOU_PY%" goto bundled
where py >nul 2>nul
if not errorlevel 1 goto pylauncher
where python >nul 2>nul
if not errorlevel 1 goto python
echo Python 3.10 or later is required. See README.md.
pause
exit /b 1
:bundled
"%XINGGOU_PY%" "%~dp0launch.py" %*
goto done
:pylauncher
py -3 "%~dp0launch.py" %*
goto done
:python
python "%~dp0launch.py" %*
:done
if errorlevel 1 pause
