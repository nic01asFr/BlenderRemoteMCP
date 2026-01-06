@echo off
REM Blender MCP Server - Windows Startup Script

echo ========================================
echo Blender MCP Server
echo ========================================
echo.

REM Parse arguments
set MODE=docker
if "%1"=="--local" set MODE=local

if "%MODE%"=="docker" (
    REM Check if Docker is running
    docker info >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Docker is not running.
        echo Please start Docker Desktop first, or use: start.bat --local
        pause
        exit /b 1
    )

    REM Check if blender-canvas image exists
    docker images | findstr "blender-canvas" >nul 2>&1
    if errorlevel 1 (
        echo Building blender-canvas Docker image...
        echo This may take several minutes on first run.
        echo.
        docker build -t blender-canvas:latest docker/blender-canvas/
        if errorlevel 1 (
            echo ERROR: Failed to build blender-canvas image
            pause
            exit /b 1
        )
    )

    echo Starting with Docker Compose...
    docker-compose up -d

    echo.
    echo ========================================
    echo Server started!
    echo.
    echo API:      http://localhost:8000
    echo MCP:      http://localhost:8000/mcp
    echo Web UI:   http://localhost:8000
    echo.
    echo View logs: docker-compose logs -f api
    echo Stop:      docker-compose down
    echo ========================================

) else (
    REM Local mode
    echo Running in local mode...
    echo.

    REM Check Python environment
    if not exist "venv\Scripts\activate" (
        echo Creating virtual environment...
        python -m venv venv
    )

    call venv\Scripts\activate

    echo Installing dependencies...
    pip install -q -r requirements.txt

    REM Check if blender-canvas image exists for containers
    docker info >nul 2>&1
    if not errorlevel 1 (
        docker images | findstr "blender-canvas" >nul 2>&1
        if errorlevel 1 (
            echo Building blender-canvas Docker image...
            docker build -t blender-canvas:latest docker/blender-canvas/
        )
    )

    echo.
    echo Starting MCP server on http://localhost:8000
    echo.
    python main_mcp.py
)

pause
