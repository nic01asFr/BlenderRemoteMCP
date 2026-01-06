#!/bin/bash

# Blender MCP Server - Unix Startup Script

echo "========================================"
echo "Blender MCP Server"
echo "========================================"
echo

# Parse arguments
MODE="docker"
if [ "$1" = "--local" ]; then
    MODE="local"
fi

if [ "$MODE" = "docker" ]; then
    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        echo "ERROR: Docker is not running."
        echo "Please start Docker first, or use: ./start.sh --local"
        exit 1
    fi

    # Check if blender-canvas image exists
    if ! docker images | grep -q "blender-canvas"; then
        echo "Building blender-canvas Docker image..."
        echo "This may take several minutes on first run."
        echo
        docker build -t blender-canvas:latest docker/blender-canvas/
        if [ $? -ne 0 ]; then
            echo "ERROR: Failed to build blender-canvas image"
            exit 1
        fi
    fi

    echo "Starting with Docker Compose..."
    docker-compose up -d

    echo
    echo "========================================"
    echo "Server started!"
    echo
    echo "API:      http://localhost:8000"
    echo "MCP:      http://localhost:8000/mcp"
    echo "Web UI:   http://localhost:8000"
    echo
    echo "View logs: docker-compose logs -f api"
    echo "Stop:      docker-compose down"
    echo "========================================"

else
    # Local mode
    echo "Running in local mode..."
    echo

    # Check Python environment
    if [ ! -d "venv" ]; then
        echo "Creating virtual environment..."
        python3 -m venv venv
    fi

    source venv/bin/activate

    echo "Installing dependencies..."
    pip install -q -r requirements.txt

    # Check if blender-canvas image exists for containers
    if docker info > /dev/null 2>&1; then
        if ! docker images | grep -q "blender-canvas"; then
            echo "Building blender-canvas Docker image..."
            docker build -t blender-canvas:latest docker/blender-canvas/
        fi
    fi

    echo
    echo "Starting MCP server on http://localhost:8000"
    echo
    python main_mcp.py
fi
