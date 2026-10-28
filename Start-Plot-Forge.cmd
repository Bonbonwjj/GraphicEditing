@echo off
cd /d "%~dp0"
if defined PLOT_FORGE_PYTHON (
  "%PLOT_FORGE_PYTHON%" launch.py
) else (
  where py >nul 2>nul
  if errorlevel 1 (
    python launch.py
  ) else (
    py -3 launch.py
  )
)
if errorlevel 1 pause
