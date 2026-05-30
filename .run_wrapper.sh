#!/bin/bash
LOG_FILE="logs/run_$(date +%Y%m%d_%H%M%S).log"
echo "Starting DATA-REPOSITORY at $(date)" | tee "$LOG_FILE"
echo "=====================================" | tee -a "$LOG_FILE"

# Run the actual program
bash -i ./run_Program.sh 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

echo "=====================================" | tee -a "$LOG_FILE"
echo "Exit code: $EXIT_CODE at $(date)" | tee -a "$LOG_FILE"

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "ERROR: Script failed with exit code $EXIT_CODE"
    echo "Press Enter to close..."
    read
fi
