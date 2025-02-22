# Insta Reel Generator Server

A FastAPI server that generates Instagram-style reels using AI and B-roll
footage.

## Prerequisites

- Python 3.8+
- Windows Subsystem for Linux (WSL) with Ubuntu
- Redis Server
- Git
- supabase account
- openai account
- pexels account

## Development Setup

1. Install WSL (if not already installed):
   - Open PowerShell as Administrator and run:
     ```bash
     wsl --install
     ```

2. Setup wsl user credentials for development environment:
   - Here is a guide:
     https://learn.microsoft.com/en-us/windows/wsl/setup/environment

3. Install redis and start the server:
   - Here is a guide: https://redis.io/docs/latest/getting_started/installation/

4. open a ubuntu wsl terminal and clone the repo:
   ```bash
   git clone https://github.com/yourusername/insta-reel-generator-server.git
   ```

5. Create a virtual environment and install dependencies:
   ```bash
   sudo apt update
   sudo apt install python3-venv python3-pip
   cd /mnt/c/path/to/repo
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

6. Add environment variables to the .env file:

- Refer to the .env.default file for the required variables
- Create a .env file in the root of the project and add the variables

6. run celery worker:
   ```bash
   celery -A celery_config worker --loglevel=info
   ```

7. run the server:
   ```bash
   fastapi dev main.py
   ```

## API Documentation

Once the server is running, you can access:

- Interactive API docs: `http://localhost:8000/docs`
- Alternative API docs: `http://localhost:8000/redoc`

## Common Issues and Solutions

1. **Celery Worker Not Starting**: Make sure you're running Celery from WSL, not
   Windows directly.

2. **Environment Variables Not Loading**: Ensure .env file has Unix line endings
   ```bash
   dos2unix .env
   ```

3. **Redis Connection Issues**: Verify Redis is running in WSL with
   `redis-cli ping`.

4. **Package Installation Issues**: If pip install fails, try installing
   packages individually or with verbose output:

## Intentions

- To teach my self how to build ai tools
