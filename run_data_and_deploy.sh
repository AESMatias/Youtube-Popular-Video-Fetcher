#!/bin/bash
# WARNING: Run this script with bash, not sh, for compatibility with the virtual environment activation.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" >> "$LOG_FILE"
}

# Update repository from GitHub
log_message "Pulling latest changes from GitHub repository..."
git pull https://github.com/AESMatias/Youtube-Popular-Video-Fetcher.git
if [ $? -eq 0 ]; then
    log_message "Git pull completed successfully."
else
    log_message "Error: Git pull failed."
    exit 1
fi

LOG_FILE="script_execution.log"
YOUTUBE_COLLECTOR_SCRIPT="youtube_data_collector.py"
OPENAI_PROCESSING_SCRIPT="openai_data_processing.py"
ASTRO_PROJECT_PORT=50000

log_message "Starting the automated data collection and deployment script."

#  Activate Python virtual environment (assuming it's named 'venv' in the current directory)
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
    log_message "Python virtual environment activated."
else
    log_message "Error: Python virtual environment 'venv' not found. Please ensure it exists and is set up correctly."
    exit 1
fi

# Execute youtube_data_collector.py and provide 'a' as input, which means "append to existing data"
# log_message "Executing $YOUTUBE_COLLECTOR_SCRIPT..."
# # Make sure expect is installed (sudo apt-get install expect)!
# expect -c "
#     spawn python3 $YOUTUBE_COLLECTOR_SCRIPT
#     expect \"Do you want to (o)verwrite, (a)ppend to existing, or (s)kip this step? (o/a/s): \"
#     send \"a\\r\"
#     expect eof
# "
log_message "Executing $YOUTUBE_COLLECTOR_SCRIPT with APPEND ..."
# We use printf to send "a" followed by a newline (\n) directly to the stdin of the Python script.
if printf "a\n" | python3 "$YOUTUBE_COLLECTOR_SCRIPT" >> "$LOG_FILE" 2>&1; then
    log_message "$YOUTUBE_COLLECTOR_SCRIPT executed successfully."
else
    log_message "Error: $YOUTUBE_COLLECTOR_SCRIPT failed to execute."
    deactivate  # Deactivate venv on error
    exit 1
fi



if [ $? -eq 0 ]; then
    log_message "$YOUTUBE_COLLECTOR_SCRIPT executed successfully with 'append' option."
else
    log_message "Error: $YOUTUBE_COLLECTOR_SCRIPT failed to execute."
    deactivate # Deactivate venv on error
    exit 1
fi

# Execute openai_data_processing.py after youtube_data_collector.py finishes
log_message "Executing $OPENAI_PROCESSING_SCRIPT..."
python3 "$OPENAI_PROCESSING_SCRIPT"
if [ $? -eq 0 ]; then
    log_message "$OPENAI_PROCESSING_SCRIPT executed successfully."
else
    log_message "Error: $OPENAI_PROCESSING_SCRIPT failed to execute."
    deactivate # Deactivate venv on error
    exit 1
fi

# Deactivate the virtual environment when done
deactivate
log_message "Python virtual environment deactivated."

# Copy the data from src/data to the dist/data directory before building, without this,
# the new data will not be available in the built project.
cp -R src/data dist/data

# We build the project
log_message "Running npm run build..."
npm run build
if [ $? -eq 0 ]; then
    log_message "npm run build completed successfully."
else
    log_message "Error: npm run build failed."
    exit 1
fi

# We kill the existing PM2 processes related to the Astro server, if any
log_message "Killing existing PM2 processes..."
pm2 kill
if [ $? -eq 0 ]; then
    log_message "PM2 processes killed successfully."
else
    log_message "Warning: pm2 kill command might have failed or no processes were running. Continuing anyway."
fi

# After building and killing existing PM2 processes, we start the Astro server again with PM2
log_message "Starting Astro server with PM2..."
# The port is setted in NGINX config too, I was hassling with it for a while
pm2 start serve --name "astro-server" -- dist --listen $ASTRO_PROJECT_PORT
if [ $? -eq 0 ]; then
    log_message "Astro server started successfully with PM2 in port $ASTRO_PROJECT_PORT."
else
    log_message "Error: Failed to start Astro server with PM2 on port $ASTRO_PROJECT_PORT."
    exit 1
fi

log_message "Script execution completed successfully."