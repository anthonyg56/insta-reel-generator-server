#!/bin/bash

# Check if Redis is running, if not start it
if ! pgrep redis-server > /dev/null
then
    echo "Starting Redis Server..."
    redis-server &
    sleep 2  # Wait for Redis to start
fi

# Activate virtual environment
source venv/bin/activate

# Start Celery worker in the background
echo "Starting Celery Worker..."
celery -A celery_config.celery_app worker --loglevel=info &

# Start FastAPI server
echo "Starting FastAPI Server..."
cmd.exe /c "wt.exe -w 0 wsl.exe bash -c \"cd $(pwd) && source venv/bin/activate && fastapi dev main.py\""