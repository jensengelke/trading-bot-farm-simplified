import shutil
import sys
from pathlib import Path

# Get the config name from the command-line arguments, defaulting to "default"
config = sys.argv[1] if len(sys.argv) > 1 else "default"

# Define the logs directory path
logs_dir = Path("logs") / config

# Check if the logs directory exists
if not logs_dir.is_dir():
    print(f"Directory not found: {logs_dir}")
    sys.exit(1)

# Iterate over and delete all subdirectories in the logs directory
for sub_dir in logs_dir.iterdir():
    if sub_dir.is_dir():
        print(f"Deleting directory: {sub_dir}")
        shutil.rmtree(sub_dir)

print("Log cleaning complete.")
