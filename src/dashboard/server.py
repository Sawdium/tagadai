"""
FastAPI server for the training dashboard.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse

from .metrics import collector, MetricsCollector
from .routes import (
    register_training_routes,
    register_scraper_routes,
    register_metadata_routes,
    register_rl_routes,
    register_nn_routes,
)
from src.common.config import get_paths

# Get paths from centralized config
_paths = get_paths()

# Static files directory
STATIC_DIR = _paths.static_dir

# Checkpoints directory
CHECKPOINTS_DIR = _paths.checkpoints_dir
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)


def create_app(metrics: Optional[MetricsCollector] = None) -> FastAPI:
    """Create the FastAPI application."""

    # Use provided collector or global
    mc = metrics or collector

    # Connected WebSocket clients
    clients: list[WebSocket] = []

    # Background task reference
    broadcast_task = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup/shutdown events."""
        nonlocal broadcast_task

        # Startup: Create background task for broadcasting updates
        async def broadcast_updates():
            """Broadcast metrics to all connected clients."""
            while True:
                if clients:
                    data = mc.get_metrics()
                    disconnected = []
                    for client in clients:
                        try:
                            await client.send_json(data)
                        except Exception:
                            disconnected.append(client)
                    for client in disconnected:
                        if client in clients:
                            clients.remove(client)
                await asyncio.sleep(0.5)  # Update every 500ms

        broadcast_task = asyncio.create_task(broadcast_updates())
        yield
        # Shutdown: Cancel the background task
        if broadcast_task:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="TagadAI Training Dashboard", lifespan=lifespan)

    # Core routes
    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the main dashboard page."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/metrics")
    async def get_metrics():
        """Get current training metrics."""
        return mc.get_metrics()

    @app.get("/api/history")
    async def get_history():
        """Get training history."""
        return mc.get_history()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        clients.append(websocket)

        try:
            # Send initial state
            await websocket.send_json(mc.get_metrics())

            # Keep connection alive and handle incoming messages
            while True:
                try:
                    # Wait for messages (or just keep alive)
                    data = await asyncio.wait_for(
                        websocket.receive_text(),
                        timeout=30.0
                    )
                    # Handle ping/pong
                    if data == "ping":
                        await websocket.send_text("pong")
                except asyncio.TimeoutError:
                    # Send heartbeat
                    await websocket.send_json(mc.get_metrics())
        except WebSocketDisconnect:
            pass
        finally:
            if websocket in clients:
                clients.remove(websocket)

    # Register route modules
    register_training_routes(app, mc)
    register_scraper_routes(app)
    register_metadata_routes(app)
    register_rl_routes(app)
    register_nn_routes(app, mc)

    # Mount static files
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


# Default app instance
app = create_app()


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the dashboard server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
