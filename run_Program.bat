@echo off
REM This batch file activates a specific Conda environment and runs a Python script.

REM --- Configuration ---
SET CONDA_ENV_NAME=nyan_investment_env
REM API-based downloader (no browser). Fallback: "0-download_Sharadar_data.py"
SET PYTHON_SCRIPT_PATH="0-download_Sharadar_data_api.py"

REM --- Execution ---
echo Activating Conda environment: %CONDA_ENV_NAME%...
CALL conda activate %CONDA_ENV_NAME%

REM Check if activation was successful
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to activate the Conda environment '%CONDA_ENV_NAME%'.
    echo Please ensure the environment exists and Conda is correctly installed and configured in your system's PATH.
    GOTO :eof
)

echo Running Python script: %PYTHON_SCRIPT_PATH%...
python %PYTHON_SCRIPT_PATH%

echo.
echo Script execution finished.
pause
