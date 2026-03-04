"""
Stream Proxy Service - RTSP to MJPEG/HLS conversion

Uses FFmpeg to convert RTSP streams to MJPEG (low latency) or HLS format for browser playback.
"""

import asyncio
import logging
import os
import platform
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Dict, Optional

logger = logging.getLogger(__name__)

# JPEG markers
JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"


@dataclass
class StreamInfo:
    """Information about an active stream"""

    stream_id: str
    rtsp_url: str
    hls_dir: Optional[Path] = None
    process: Optional[asyncio.subprocess.Process] = (
        None  # Can also be subprocess.Popen on Windows
    )
    started_at: float = 0
    last_accessed: float = 0
    error: Optional[str] = None
    status: str = "starting"  # starting | running | stopped | error
    mode: str = "mjpeg"  # mjpeg | hls
    # MJPEG specific
    _frame_buffer: bytes = field(default=b"", repr=False)
    _latest_frame: Optional[bytes] = field(default=None, repr=False)
    _frame_event: Optional[asyncio.Event] = field(default=None, repr=False)
    _reader_task: Optional[asyncio.Task] = field(default=None, repr=False)
    _stderr_output: str = field(default="", repr=False)
    _is_sync_process: bool = field(
        default=False, repr=False
    )  # True if using sync subprocess on Windows
    _stop_event: Optional[object] = field(
        default=None, repr=False
    )  # threading.Event for sync mode


class StreamProxy:
    """
    Manages RTSP to MJPEG/HLS stream conversion using FFmpeg.
    """

    def __init__(self, output_base_dir: Optional[str] = None):
        if output_base_dir:
            self.output_base_dir = Path(output_base_dir)
        else:
            self.output_base_dir = Path(tempfile.gettempdir()) / "stream_proxy"

        self.output_base_dir.mkdir(parents=True, exist_ok=True)
        self.streams: Dict[str, StreamInfo] = {}
        self._ffmpeg_path = self._find_ffmpeg()
        self._has_v4l2m2m = self._check_v4l2m2m()

    def _find_ffmpeg(self) -> Optional[str]:
        """Find FFmpeg executable, checking common installation paths"""
        # First try PATH
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            logger.info(f"Found FFmpeg at: {ffmpeg}")
            return ffmpeg

        # Platform-specific paths
        if platform.system() == "Windows":
            # Expand environment variables for Windows paths
            home = Path.home()
            common_paths = [
                # Standard installation locations
                "C:\\ffmpeg\\bin\\ffmpeg.exe",
                "C:\\ffmpeg\\ffmpeg.exe",
                "C:\\Program Files\\ffmpeg\\bin\\ffmpeg.exe",
                "C:\\Program Files (x86)\\ffmpeg\\bin\\ffmpeg.exe",
                # Package managers
                str(
                    home
                    / "scoop"
                    / "apps"
                    / "ffmpeg"
                    / "current"
                    / "bin"
                    / "ffmpeg.exe"
                ),
                str(home / "scoop" / "shims" / "ffmpeg.exe"),
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\ffmpeg-*\bin\ffmpeg.exe"
                ),
                os.path.expandvars(r"%ChocolateyInstall%\bin\ffmpeg.exe"),
                # User directories
                str(home / "ffmpeg" / "bin" / "ffmpeg.exe"),
                str(home / "ffmpeg" / "ffmpeg.exe"),
                str(home / "bin" / "ffmpeg.exe"),
                # Tools directory
                "C:\\tools\\ffmpeg\\bin\\ffmpeg.exe",
                "C:\\tools\\ffmpeg\\ffmpeg.exe",
            ]
        else:
            # Unix-like systems (macOS, Linux)
            common_paths = [
                "/opt/homebrew/bin/ffmpeg",  # Homebrew on Apple Silicon
                "/usr/local/bin/ffmpeg",  # Homebrew on Intel Mac / Linux
                "/usr/bin/ffmpeg",  # System install
                "/opt/local/bin/ffmpeg",  # MacPorts
                "/snap/bin/ffmpeg",  # Snap on Linux
                str(Path.home() / ".local" / "bin" / "ffmpeg"),  # User local
            ]

        for path in common_paths:
            # Handle glob patterns for WinGet
            if "*" in path:
                import glob

                matches = glob.glob(path)
                for match in matches:
                    if os.path.isfile(match) and os.access(match, os.X_OK):
                        logger.info(f"Found FFmpeg at: {match}")
                        return match
            elif os.path.isfile(path) and os.access(path, os.X_OK):
                logger.info(f"Found FFmpeg at: {path}")
                return path

        logger.warning("FFmpeg not found in PATH or common locations")
        return None

    def _check_v4l2m2m(self) -> bool:
        """Check if v4l2m2m hardware acceleration is available (Raspberry Pi)"""
        if platform.system() != "Linux":
            return False
        # Check for v4l2 device
        return os.path.exists("/dev/video10") or os.path.exists("/dev/video11")

    async def start_mjpeg_stream(
        self,
        rtsp_url: str,
        stream_id: Optional[str] = None,
        fps: int = 10,
        quality: int = 5,
    ) -> str:
        """
        Start an RTSP to MJPEG stream.

        Args:
            rtsp_url: The RTSP URL to convert
            stream_id: Optional stream ID
            fps: Target frame rate (default: 10)
            quality: JPEG quality (2=best, 31=worst, default: 5)

        Returns:
            The stream ID
        """
        if not self._ffmpeg_path:
            raise RuntimeError("FFmpeg is not installed.")

        if stream_id is None:
            stream_id = str(uuid.uuid4())[:8]

        # Stop existing stream with same ID
        if stream_id in self.streams:
            await self.stop_stream(stream_id)

        stream_info = StreamInfo(
            stream_id=stream_id,
            rtsp_url=rtsp_url,
            mode="mjpeg",
            started_at=time.time(),
            last_accessed=time.time(),
            _frame_event=asyncio.Event(),
        )
        self.streams[stream_id] = stream_info

        try:
            await self._start_mjpeg_ffmpeg(stream_info, fps, quality)
            logger.info(f"Started MJPEG stream {stream_id} from {rtsp_url}")
        except Exception as e:
            import traceback

            stream_info.status = "error"
            stream_info.error = str(e)
            logger.error(f"Failed to start MJPEG stream {stream_id}: {e!r}")
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            raise

        return stream_id

    async def _start_mjpeg_ffmpeg(
        self, stream_info: StreamInfo, fps: int, quality: int
    ):
        """Start FFmpeg for MJPEG output to pipe"""
        cmd = [self._ffmpeg_path]

        # Hardware acceleration on Raspberry Pi
        if self._has_v4l2m2m:
            cmd.extend(["-hwaccel", "v4l2m2m"])

        cmd.extend(
            [
                "-rtsp_transport",
                "tcp",
                "-fflags",
                "nobuffer+discardcorrupt",
                "-flags",
                "low_delay",
                "-err_detect",
                "ignore_err",
                "-analyzeduration",
                "5000000",  # 5 seconds for streams with PPS issues
                "-probesize",
                "5000000",  # Larger probe size for problematic streams
                "-i",
                stream_info.rtsp_url,
                "-f",
                "image2pipe",
                "-c:v",
                "mjpeg",
                "-q:v",
                str(quality),
                "-r",
                str(fps),
                "-an",  # No audio
                "-flush_packets",
                "1",
                "pipe:1",
            ]
        )

        logger.debug(f"Starting FFmpeg MJPEG: {' '.join(cmd)}")

        # Check event loop type for debugging
        loop = asyncio.get_running_loop()
        loop_name = type(loop).__name__
        logger.debug(f"Event loop type: {loop_name}")

        # On Windows, SelectorEventLoop doesn't support subprocess - use sync Popen instead
        # ProactorEventLoop supports subprocess but uvicorn uses SelectorEventLoop by default
        is_windows = platform.system().lower() == "windows"
        has_selector = "Selector" in loop_name
        use_sync = is_windows and has_selector
        logger.debug(
            f"Subprocess mode: is_windows={is_windows}, has_selector={has_selector}, use_sync={use_sync}"
        )
        if use_sync:
            logger.debug("Using threaded subprocess for Windows compatibility")
            import subprocess
            import threading

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stream_info.process = process
            stream_info._is_sync_process = True
        else:
            # On Windows, hide console window for async subprocess too
            kwargs = {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
            }
            if platform.system() == "Windows":
                import subprocess

                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

            stream_info.process = await asyncio.create_subprocess_exec(*cmd, **kwargs)
            stream_info._is_sync_process = False

        # Drain stderr concurrently to prevent pipe buffer deadlock.
        # On macOS the pipe buffer is only 4-16KB; if ffmpeg fills it
        # with connection/codec info, it blocks and stops producing frames.
        if stream_info._is_sync_process:
            # For sync subprocess, use threads
            import threading

            stream_info._stop_event = threading.Event()
            threading.Thread(
                target=self._drain_stderr_sync, args=(stream_info,), daemon=True
            ).start()
            # Start reading frames in a thread, but notify async via event
            threading.Thread(
                target=self._read_mjpeg_frames_sync, args=(stream_info,), daemon=True
            ).start()
        else:
            asyncio.create_task(self._drain_stderr(stream_info))
            # Start reading frames in background
            stream_info._reader_task = asyncio.create_task(
                self._read_mjpeg_frames(stream_info)
            )

        # Startup timeout: kill ffmpeg if no frame within 30 seconds
        # Some RTSP streams (especially with H.264 PPS issues) need time to sync
        asyncio.create_task(self._startup_timeout(stream_info, timeout=30))

    async def _startup_timeout(self, stream_info: StreamInfo, timeout: int = 15):
        """Kill ffmpeg if it doesn't produce a frame within timeout seconds"""
        await asyncio.sleep(timeout)
        if stream_info.status == "starting":
            logger.error(
                f"MJPEG stream {stream_info.stream_id}: no frames after {timeout}s, "
                f"killing ffmpeg. RTSP URL may be unreachable: {stream_info.rtsp_url}"
            )
            if stream_info.process and stream_info.process.returncode is None:
                stream_info.process.kill()

    async def _drain_stderr(self, stream_info: StreamInfo):
        """Read and log ffmpeg stderr to prevent pipe buffer from filling up"""
        stderr_lines = []
        try:
            while True:
                line = await stream_info.process.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text:
                    stderr_lines.append(text)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        # Store last stderr for error reporting
        if stderr_lines:
            stream_info._stderr_output = "\n".join(stderr_lines[-20:])

    def _drain_stderr_sync(self, stream_info: StreamInfo):
        """Synchronous version of _drain_stderr for Windows subprocess.Popen"""
        stderr_lines = []
        try:
            while not stream_info._stop_event.is_set():
                line = stream_info.process.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text:
                    stderr_lines.append(text)
        except Exception:
            pass
        if stderr_lines:
            stream_info._stderr_output = "\n".join(stderr_lines[-20:])

    async def _read_mjpeg_frames(self, stream_info: StreamInfo):
        """Read JPEG frames from ffmpeg stdout pipe"""
        buffer = b""
        frame_start = -1

        try:
            while True:
                chunk = await stream_info.process.stdout.read(65536)
                if not chunk:
                    break

                buffer += chunk

                # Find complete JPEG frames in buffer
                while True:
                    # Find SOI marker
                    if frame_start < 0:
                        soi_pos = buffer.find(JPEG_SOI)
                        if soi_pos < 0:
                            # No SOI found, discard buffer up to last byte
                            buffer = buffer[-1:] if buffer else b""
                            break
                        frame_start = soi_pos

                    # Find EOI marker after frame_start
                    eoi_pos = buffer.find(JPEG_EOI, frame_start + 2)
                    if eoi_pos < 0:
                        # No complete frame yet, trim buffer
                        if frame_start > 0:
                            buffer = buffer[frame_start:]
                            frame_start = 0
                        break

                    # Extract complete JPEG frame
                    frame_end = eoi_pos + 2
                    frame = buffer[frame_start:frame_end]

                    # Update latest frame
                    stream_info._latest_frame = frame
                    stream_info._frame_event.set()
                    stream_info._frame_event.clear()

                    if stream_info.status == "starting":
                        stream_info.status = "running"
                        logger.info(
                            f"MJPEG stream {stream_info.stream_id}: first frame received ({len(frame)} bytes)"
                        )

                    # Advance buffer past this frame
                    buffer = buffer[frame_end:]
                    frame_start = -1

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"MJPEG reader error for {stream_info.stream_id}: {e}")
            stream_info.error = str(e)
            stream_info.status = "error"
        finally:
            if stream_info.status == "starting":
                # ffmpeg exited without producing any frames
                stderr_msg = getattr(stream_info, "_stderr_output", "")
                stream_info.error = stderr_msg or "Stream failed to produce frames"
                stream_info.status = "error"
                logger.error(
                    f"MJPEG stream {stream_info.stream_id} failed: {stream_info.error}"
                )
            elif stream_info.status == "running":
                stream_info.status = "stopped"

    def _read_mjpeg_frames_sync(self, stream_info: StreamInfo):
        """Synchronous version of _read_mjpeg_frames for Windows subprocess.Popen"""
        buffer = b""
        frame_start = -1

        try:
            while not stream_info._stop_event.is_set():
                chunk = stream_info.process.stdout.read(65536)
                if not chunk:
                    break

                buffer += chunk

                # Find complete JPEG frames in buffer
                while True:
                    # Find SOI marker
                    if frame_start < 0:
                        soi_pos = buffer.find(JPEG_SOI)
                        if soi_pos < 0:
                            buffer = buffer[-1:] if buffer else b""
                            break
                        frame_start = soi_pos

                    # Find EOI marker after frame_start
                    eoi_pos = buffer.find(JPEG_EOI, frame_start + 2)
                    if eoi_pos < 0:
                        if frame_start > 0:
                            buffer = buffer[frame_start:]
                            frame_start = 0
                        break

                    # Extract complete JPEG frame
                    frame_end = eoi_pos + 2
                    frame = buffer[frame_start:frame_end]

                    # Update latest frame (thread-safe via GIL for simple assignments)
                    stream_info._latest_frame = frame
                    # Note: asyncio.Event.set() is not thread-safe, but the frame is available

                    if stream_info.status == "starting":
                        stream_info.status = "running"

                    buffer = buffer[frame_end:]
                    frame_start = -1

        except Exception as e:
            logger.error(f"MJPEG reader error for {stream_info.stream_id}: {e}")
            stream_info.error = str(e)
            stream_info.status = "error"
        finally:
            if stream_info.status == "starting":
                stderr_msg = getattr(stream_info, "_stderr_output", "")
                stream_info.error = stderr_msg or "Stream failed to produce frames"
                stream_info.status = "error"
                logger.error(
                    f"MJPEG stream {stream_info.stream_id} failed: {stream_info.error}"
                )
            elif stream_info.status == "running":
                stream_info.status = "stopped"

    async def get_mjpeg_frames(self, stream_id: str) -> AsyncGenerator[bytes, None]:
        """
        Async generator yielding MJPEG frames for HTTP streaming.

        Yields frames in multipart/x-mixed-replace format.
        """
        stream_info = self.streams.get(stream_id)
        if not stream_info or stream_info.mode != "mjpeg":
            return

        stream_info.last_accessed = time.time()
        last_frame = None
        frame_count = 0

        while stream_info.status in ("starting", "running"):
            # Wait for a new frame or timeout
            try:
                await asyncio.wait_for(
                    self._wait_for_frame(stream_info, last_frame), timeout=5.0
                )
            except asyncio.TimeoutError:
                # Keep waiting during "starting" (ffmpeg connecting) and "running" phases
                # Only break if status changed to "error" or "stopped"
                if stream_info.status not in ("starting", "running"):
                    break
                continue

            frame = stream_info._latest_frame
            if frame and frame is not last_frame:
                last_frame = frame
                frame_count += 1
                stream_info.last_accessed = time.time()
                # Yield as multipart chunk
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                    b"\r\n" + frame + b"\r\n"
                )

    async def _wait_for_frame(self, stream_info: StreamInfo, last_frame):
        """Wait until a new frame is available"""
        while stream_info._latest_frame is last_frame and stream_info.status in (
            "starting",
            "running",
        ):
            await asyncio.sleep(0.01)

    # ========== HLS mode (kept for backward compatibility) ==========

    async def start_stream(self, rtsp_url: str, stream_id: Optional[str] = None) -> str:
        """Start converting an RTSP stream to HLS."""
        if not self._ffmpeg_path:
            raise RuntimeError("FFmpeg is not installed.")

        if stream_id is None:
            stream_id = str(uuid.uuid4())[:8]

        if stream_id in self.streams:
            existing = self.streams[stream_id]
            if existing.status == "running":
                return stream_id
            else:
                await self.stop_stream(stream_id)

        hls_dir = self.output_base_dir / stream_id
        hls_dir.mkdir(parents=True, exist_ok=True)

        stream_info = StreamInfo(
            stream_id=stream_id,
            rtsp_url=rtsp_url,
            hls_dir=hls_dir,
            mode="hls",
            started_at=time.time(),
            last_accessed=time.time(),
        )
        self.streams[stream_id] = stream_info

        try:
            await self._start_hls_ffmpeg(stream_info)
        except Exception as e:
            stream_info.status = "error"
            stream_info.error = str(e)
            raise

        return stream_id

    async def _start_hls_ffmpeg(self, stream_info: StreamInfo):
        """Start FFmpeg for HLS output"""
        hls_output = stream_info.hls_dir / "index.m3u8"

        cmd = [
            self._ffmpeg_path,
            "-rtsp_transport",
            "tcp",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-i",
            stream_info.rtsp_url,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "3",
            "-hls_flags",
            "delete_segments+append_list",
            "-start_number",
            "0",
            str(hls_output),
        ]

        # On Windows, hide console window
        kwargs = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if platform.system() == "Windows":
            import subprocess

            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        stream_info.process = await asyncio.create_subprocess_exec(*cmd, **kwargs)

        asyncio.create_task(self._monitor_process(stream_info))

        # Wait for HLS file
        max_wait = 15
        for i in range(max_wait * 2):
            await asyncio.sleep(0.5)
            if stream_info.process.returncode is not None:
                stderr = await stream_info.process.stderr.read()
                raise RuntimeError(f"FFmpeg exited: {stderr.decode()}")
            ts_files = list(stream_info.hls_dir.glob("*.ts"))
            if hls_output.exists() or len(ts_files) > 0:
                if not hls_output.exists():
                    await asyncio.sleep(1)
                stream_info.status = "running"
                return

        stream_info.process.terminate()
        raise RuntimeError(f"Timeout waiting for HLS stream: {stream_info.rtsp_url}")

    async def _monitor_process(self, stream_info: StreamInfo):
        """Monitor FFmpeg process"""
        if not stream_info.process:
            return
        stdout, stderr = await stream_info.process.communicate()
        if stream_info.process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"Stream {stream_info.stream_id} FFmpeg error: {error_msg}")
            stream_info.status = "error"
            stream_info.error = error_msg
        else:
            stream_info.status = "stopped"

    # ========== Common methods ==========

    async def stop_stream(self, stream_id: str) -> bool:
        """Stop a running stream"""
        if stream_id not in self.streams:
            return False

        stream_info = self.streams[stream_id]

        if stream_info._is_sync_process:
            # For sync subprocess (Windows), signal threads to stop
            if stream_info._stop_event:
                stream_info._stop_event.set()

            # Terminate FFmpeg (sync process)
            if stream_info.process and stream_info.process.returncode is None:
                stream_info.process.terminate()
                try:
                    stream_info.process.wait(timeout=5)
                except Exception:
                    stream_info.process.kill()
                    stream_info.process.wait()
        else:
            # Cancel reader task (async)
            if stream_info._reader_task and not stream_info._reader_task.done():
                stream_info._reader_task.cancel()
                try:
                    await stream_info._reader_task
                except asyncio.CancelledError:
                    pass

            # Terminate FFmpeg (async process)
            if stream_info.process and stream_info.process.returncode is None:
                stream_info.process.terminate()
                try:
                    await asyncio.wait_for(stream_info.process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    stream_info.process.kill()
                    await stream_info.process.wait()

        # Clean up HLS files
        if stream_info.hls_dir and stream_info.hls_dir.exists():
            shutil.rmtree(stream_info.hls_dir, ignore_errors=True)

        del self.streams[stream_id]
        logger.info(f"Stopped stream {stream_id}")
        return True

    def get_stream_info(self, stream_id: str) -> Optional[StreamInfo]:
        return self.streams.get(stream_id)

    def get_hls_path(self, stream_id: str) -> Optional[Path]:
        info = self.streams.get(stream_id)
        if info and info.mode == "hls" and info.status == "running":
            return info.hls_dir / "index.m3u8"
        return None

    def get_stream_file(self, stream_id: str, filename: str) -> Optional[Path]:
        info = self.streams.get(stream_id)
        if info and info.hls_dir:
            file_path = info.hls_dir / filename
            if file_path.exists():
                return file_path
        return None

    def list_streams(self) -> Dict[str, dict]:
        return {
            sid: {
                "stream_id": info.stream_id,
                "rtsp_url": info.rtsp_url,
                "status": info.status,
                "mode": info.mode,
                "error": info.error,
            }
            for sid, info in self.streams.items()
        }

    async def cleanup_idle_streams(self, max_idle_seconds: int = 300):
        now = time.time()
        to_stop = [
            sid
            for sid, info in self.streams.items()
            if now - info.last_accessed > max_idle_seconds
        ]
        for stream_id in to_stop:
            logger.info(f"Cleaning up idle stream: {stream_id}")
            await self.stop_stream(stream_id)

    async def stop_all(self):
        for stream_id in list(self.streams.keys()):
            await self.stop_stream(stream_id)


# Global instance
_stream_proxy: Optional[StreamProxy] = None


def get_stream_proxy() -> StreamProxy:
    global _stream_proxy
    if _stream_proxy is None:
        _stream_proxy = StreamProxy()
    return _stream_proxy
