#!/bin/bash

# --- Configuration ---
CONDA_ENV_NAME="nyan_investment_env"

# --- Activate Conda ---
echo "Activating Conda environment: $CONDA_ENV_NAME..."
# Resolve conda without depending on the caller's PATH: a launcher that runs this script in a
# NON-interactive shell skips ~/.bashrc (it returns before the conda-init block), so `conda`
# is not on PATH. Use `conda` on PATH, else $CONDA_EXE, else ~/miniconda3; none -> fail loudly.
if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
elif [ -n "${CONDA_EXE:-}" ] && [ -x "${CONDA_EXE}" ]; then
    CONDA_BASE="$("${CONDA_EXE}" info --base)"
elif [ -x "$HOME/miniconda3/bin/conda" ]; then
    CONDA_BASE="$HOME/miniconda3"
else
    echo "ERROR: conda not found (not on PATH, CONDA_EXE unset, no ~/miniconda3)." >&2
    exit 1
fi
source "${CONDA_BASE}/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV_NAME"

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate '$CONDA_ENV_NAME'."
    exit 1
fi

# --- Run Scripts ---
# API-based downloader (no browser). Fallback: "0-download_Sharadar_data.py"
python -u "0-download_Sharadar_data_api.py"





# #!/bin/bash

# # This bash script activates a specific Conda environment and runs a Python script.

# # --- Configuration ---
# CONDA_ENV_NAME="nyan_investment_env"
# PYTHON_SCRIPT_PATH="0-download_Sharadar_data.py"

# # --- Execution ---
# echo "Activating Conda environment: $CONDA_ENV_NAME..."

# # The 'conda activate' command is a shell function.
# # It's better to source the conda script to make the 'conda' command available.
# # This path might vary depending on your installation (e.g., miniconda3).
# source "$(conda info --base)/etc/profile.d/conda.sh"
# conda activate "$CONDA_ENV_NAME"

# # Check if activation was successful
# if [ $? -ne 0 ]; then
#     echo "ERROR: Failed to activate the Conda environment '$CONDA_ENV_NAME'."
#     echo "Please ensure the environment exists and Conda is correctly installed and configured."
#     exit 1
# fi

# echo "Running Python script: $PYTHON_SCRIPT_PATH..."
# python "$PYTHON_SCRIPT_PATH"

# echo ""
# echo "Script execution finished."
# read -p "Press Enter to continue..."


