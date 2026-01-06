#!/usr/bin/env python3
"""
MJPEG Stream Server
Captures the X display and streams it as MJPEG over HTTP
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import subprocess
import asyncio
import os
import signal
import sys

app = FastAPI(title="Blender Stream Server")

# Stream configuration
DISPLAY = os.environ.get("DISPLAY", ":99")
WIDTH = 1920
HEIGHT = 1080
FPS = 30
QUALITY = 85  # JPEG quality (1-100)

# Global FFmpeg process
ffmpeg_process = None


def start_ffmpeg():
    """Start FFmpeg to capture X display"""
    global ffmpeg_process

    cmd = [
        "ffmpeg",
        "-f", "x11grab",           # X11 screen capture
        "-video_size", f"{WIDTH}x{HEIGHT}",
        "-framerate", str(FPS),
        "-i", DISPLAY,            # Display to capture
        "-vf", f"scale={WIDTH}:{HEIGHT}",
        "-c:v", "mjpeg",          # MJPEG codec
        "-q:v", str(int((100 - QUALITY) / 10) + 2),  # Quality (2-31, lower=better)
        "-f", "mjpeg",            # Output format
        "-"                       # Output to stdout
    ]

    ffmpeg_process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=10**8
    )

    return ffmpeg_process


async def generate_frames():
    """Generator that yields MJPEG frames"""
    global ffmpeg_process

    if ffmpeg_process is None or ffmpeg_process.poll() is not None:
        ffmpeg_process = start_ffmpeg()

    # JPEG markers
    SOI = b'\xff\xd8'  # Start of Image
    EOI = b'\xff\xd9'  # End of Image

    buffer = b''

    try:
        while True:
            # Read chunk from FFmpeg
            chunk = ffmpeg_process.stdout.read(65536)
            if not chunk:
                # FFmpeg stopped, restart
                ffmpeg_process = start_ffmpeg()
                continue

            buffer += chunk

            # Find complete JPEG frames
            while True:
                # Find start of JPEG
                start = buffer.find(SOI)
                if start == -1:
                    buffer = b''
                    break

                # Find end of JPEG
                end = buffer.find(EOI, start + 2)
                if end == -1:
                    # Incomplete frame, wait for more data
                    buffer = buffer[start:]
                    break

                # Extract complete frame
                frame = buffer[start:end + 2]
                buffer = buffer[end + 2:]

                # Yield as multipart response
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n'
                    b'Content-Length: ' + str(len(frame)).encode() + b'\r\n'
                    b'\r\n' + frame + b'\r\n'
                )

            # Small delay to prevent CPU overload
            await asyncio.sleep(0.001)

    except Exception as e:
        print(f"Stream error: {e}")
        if ffmpeg_process:
            ffmpeg_process.kill()


@app.get("/stream")
async def video_stream():
    """MJPEG video stream endpoint"""
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.get("/snapshot")
async def snapshot():
    """Single frame snapshot"""
    global ffmpeg_process

    # Use FFmpeg to capture single frame
    cmd = [
        "ffmpeg",
        "-f", "x11grab",
        "-video_size", f"{WIDTH}x{HEIGHT}",
        "-i", DISPLAY,
        "-frames:v", "1",
        "-c:v", "mjpeg",
        "-q:v", "2",
        "-f", "image2pipe",
        "-"
    ]

    result = subprocess.run(cmd, capture_output=True)

    if result.returncode == 0:
        return StreamingResponse(
            iter([result.stdout]),
            media_type="image/jpeg"
        )
    else:
        return {"error": "Failed to capture snapshot"}


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "streaming": ffmpeg_process is not None}


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    global ffmpeg_process
    if ffmpeg_process:
        ffmpeg_process.kill()
        ffmpeg_process = None


def signal_handler(sig, frame):
    """Handle shutdown signals"""
    global ffmpeg_process
    if ffmpeg_process:
        ffmpeg_process.kill()
    sys.exit(0)


if __name__ == "__main__":
    import uvicorn

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    uvicorn.run(app, host="0.0.0.0", port=8081)
