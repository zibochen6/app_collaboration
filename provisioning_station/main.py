"""
FastAPI application entry point
"""

import asyncio
import atexit
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

# Windows requires ProactorEventLoop for asyncio subprocess support
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Configure application logging (uvicorn only sets up its own loggers)
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s:\t %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .middleware.auth import ApiKeyAuthMiddleware
from .routers import (
    api_keys,
    deployments,
    device_management,
    devices,
    docker_devices,
    preview,
    restore,
    serial_camera,
    solutions,
    versions,
    websocket,
)
from .services.api_key_manager import get_api_key_manager
from .services.mqtt_bridge import get_mqtt_bridge, is_mqtt_available
from .services.serial_camera_service import get_serial_camera_manager
from .services.solution_manager import solution_manager
from .services.stream_proxy import get_stream_proxy

# Global flag to track if cleanup has been performed
_cleanup_done = False
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _sync_cleanup():
    """Synchronous cleanup for atexit handler (last resort)"""
    global _cleanup_done
    if _cleanup_done:
        return

    logger.debug("Running synchronous cleanup (atexit)...")

    # Try to stop FFmpeg processes synchronously
    try:
        stream_proxy = get_stream_proxy()
        # Kill any running FFmpeg processes directly
        for stream_id, stream_info in list(stream_proxy._streams.items()):
            if stream_info.process and stream_info.process.returncode is None:
                try:
                    stream_info.process.kill()
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Sync cleanup error: {e}")

    _cleanup_done = True


async def _async_cleanup():
    """Async cleanup for graceful shutdown"""
    global _cleanup_done
    if _cleanup_done:
        return

    logger.debug("Running async cleanup...")

    try:
        await get_stream_proxy().stop_all()
        logger.debug("Stream proxy stopped")
    except Exception as e:
        logger.debug(f"Stream proxy cleanup error: {e}")

    try:
        if is_mqtt_available():
            await get_mqtt_bridge().stop_all()
            logger.debug("MQTT bridge stopped")
    except Exception as e:
        logger.debug(f"MQTT bridge cleanup error: {e}")

    try:
        get_serial_camera_manager().close_all()
        logger.debug("Serial camera sessions closed")
    except Exception as e:
        logger.debug(f"Serial camera cleanup error: {e}")

    _cleanup_done = True
    logger.debug("Async cleanup completed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    global _event_loop

    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    print(f"Solutions directory: {settings.solutions_dir}")
    print(f"Platform: {sys.platform}")

    # Store event loop for signal handlers
    _event_loop = asyncio.get_running_loop()

    # Register atexit handler as last resort cleanup
    atexit.register(_sync_cleanup)

    # Ensure directories exist
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)

    # Load solutions
    await solution_manager.load_solutions()
    print(f"Loaded {len(solution_manager.solutions)} solutions")

    # Auto-create default API key if api_enabled and no keys exist
    if settings.api_enabled:
        logger.info("API access enabled — external clients can connect")
        key = get_api_key_manager().ensure_default_key()
        if key:
            masked = f"{key[:5]}...{key[-4:]}"
            logger.warning("Auto-generated default API key (masked): %s", masked)
            # Write plaintext to file with restricted permissions
            key_file = settings.data_dir / "default_api_key.txt"
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            key_file.write_text(key)
            key_file.chmod(0o600)
            logger.info(
                "Plaintext key saved to %s — read it once, then delete the file.",
                key_file,
            )

    yield

    # Shutdown - this runs when uvicorn receives SIGTERM/SIGINT
    logger.debug("Shutting down (lifespan)...")

    # Cleanup preview services
    await _async_cleanup()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "IoT Solution Provisioning Platform for Seeed Studio products.\n\n"
        "**Authentication:** Localhost requests are always allowed. "
        "Remote requests require an API key via `X-API-Key` header "
        "or `Authorization: Bearer <key>`."
    ),
    lifespan=lifespan,
)

# CORS middleware (for local development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API key auth middleware (after CORS so preflight OPTIONS are not blocked)
app.add_middleware(
    ApiKeyAuthMiddleware,
    api_enabled=settings.api_enabled,
    key_manager=get_api_key_manager(),
)

# Include routers
app.include_router(solutions.router)
app.include_router(devices.router)
app.include_router(deployments.router)
app.include_router(websocket.router)
app.include_router(versions.router)
app.include_router(device_management.router)
app.include_router(preview.router)
app.include_router(docker_devices.router)
app.include_router(restore.router)
app.include_router(serial_camera.router)
app.include_router(api_keys.router)

# Serve static frontend files
_default_frontend_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
_configured_frontend_dir: Optional[Path] = None
if settings.frontend_dir:
    # Resolve relative frontend dir against project base for stable behavior.
    _configured_frontend_dir = settings.frontend_dir
    if not _configured_frontend_dir.is_absolute():
        _configured_frontend_dir = settings.base_dir / _configured_frontend_dir
    _configured_frontend_dir = _configured_frontend_dir.resolve()

_frontend_candidates = []
if _configured_frontend_dir:
    _frontend_candidates.append(_configured_frontend_dir)
if _default_frontend_dir not in _frontend_candidates:
    _frontend_candidates.append(_default_frontend_dir)

_frontend_dir = next(
    (
        path
        for path in _frontend_candidates
        if path.exists() and (path / "index.html").exists()
    ),
    None,
)

if _configured_frontend_dir and _frontend_dir != _configured_frontend_dir:
    logger.warning(
        "Configured frontend dir is invalid or incomplete: %s. "
        "Falling back to: %s",
        _configured_frontend_dir,
        _frontend_dir or _default_frontend_dir,
    )

if _frontend_dir:
    _assets_dir = _frontend_dir / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")
    else:
        logger.warning("Frontend assets directory missing: %s", _assets_dir)

    @app.get("/")
    async def serve_frontend():
        return FileResponse(_frontend_dir / "index.html")
else:
    logger.warning(
        "Frontend dist not found; UI route disabled. Checked: %s",
        [str(path) for path in _frontend_candidates],
    )


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


def main():
    """CLI entry point"""
    import argparse
    import os
    import sys

    import uvicorn

    # Check if running as frozen executable
    is_frozen = getattr(sys, "frozen", False)
    print(f"Starting provisioning-station (frozen={is_frozen})")

    parser = argparse.ArgumentParser(
        description="SenseCraft Solution Provisioning Station"
    )

    subparsers = parser.add_subparsers(dest="command")

    # Subcommand: create-key
    create_key_parser = subparsers.add_parser("create-key", help="Create an API key")
    create_key_parser.add_argument("name", help="Name for the API key")

    # Subcommand: list-keys
    subparsers.add_parser("list-keys", help="List all API keys")

    # Subcommand: delete-key
    delete_key_parser = subparsers.add_parser("delete-key", help="Delete an API key")
    delete_key_parser.add_argument("name", help="Name of the key to delete")

    # Server arguments
    parser.add_argument(
        "--port",
        type=int,
        default=settings.port,
        help=f"Port to listen on (default: {settings.port})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=settings.host,
        help=f"Host to bind to (default: {settings.host})",
    )
    parser.add_argument(
        "--solutions-dir",
        type=str,
        default=None,
        help="Path to solutions directory (overrides default)",
    )
    parser.add_argument(
        "--frontend-dir",
        type=str,
        default=None,
        help="Path to frontend dist directory",
    )
    parser.add_argument(
        "--api-enabled",
        action="store_true",
        default=settings.api_enabled,
        help="Enable external API access (binds to 0.0.0.0)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        default=settings.debug,
        help="Enable auto-reload (for development)",
    )
    args = parser.parse_args()

    # Handle key management subcommands
    if args.command == "create-key":
        manager = get_api_key_manager()
        key = manager.create_key(args.name)
        print(f"API key created: {key}")
        print("Save this key — it will not be shown again.")
        return
    elif args.command == "list-keys":
        manager = get_api_key_manager()
        keys = manager.list_keys()
        if not keys:
            print("No API keys found.")
        else:
            for k in keys:
                print(
                    f"  {k['name']}  created={k['created_at']}  last_used={k['last_used_at']}"
                )
        return
    elif args.command == "delete-key":
        manager = get_api_key_manager()
        if manager.delete_key(args.name):
            print(f"Deleted key '{args.name}'")
        else:
            print(f"Key '{args.name}' not found")
        return

    # Sync --api-enabled flag to settings so middleware sees it
    if args.api_enabled and not settings.api_enabled:
        os.environ["PS_API_ENABLED"] = "true"
        settings.api_enabled = True

    # Set solutions dir via environment variable if provided
    # This will be picked up when uvicorn imports the app
    if args.solutions_dir:
        os.environ["PS_SOLUTIONS_DIR"] = args.solutions_dir

    if args.frontend_dir:
        os.environ["PS_FRONTEND_DIR"] = args.frontend_dir

    # When API is enabled, default host to api_host (0.0.0.0) unless explicitly set
    host = args.host
    if args.api_enabled and host == settings.host and host == "127.0.0.1":
        host = settings.api_host

    if is_frozen:
        # For frozen executables, pass the app object directly to avoid
        # module reimport issues where sys.frozen might not be preserved
        # Also disable reload since it doesn't work with frozen apps
        uvicorn.run(
            app,
            host=host,
            port=args.port,
            reload=False,
        )
    else:
        # For development, use string reference to enable hot reload
        uvicorn.run(
            "provisioning_station.main:app",
            host=host,
            port=args.port,
            reload=args.reload,
        )


if __name__ == "__main__":
    main()
