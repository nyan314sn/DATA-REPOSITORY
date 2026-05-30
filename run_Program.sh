#!/bin/bash

# --- Configuration ---
CONDA_ENV_NAME="nyan_investment_env"

# --- Activate Conda ---
echo "Activating Conda environment: $CONDA_ENV_NAME..."
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "$CONDA_ENV_NAME"

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate '$CONDA_ENV_NAME'."
    exit 1
fi

# --- Run Scripts ---
python -u "0-download_Sharadar_data.py"





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


