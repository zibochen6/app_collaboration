#!/usr/bin/env python3
"""
Cross-platform port cleanup utility.

Detects and optionally kills processes occupying specified ports,
but only if they appear to be leftover processes from this application.
"""

import argparse
import platform
import re
import socket
import subprocess
import sys
from typing import NamedTuple

import psutil


class PortProcess(NamedTuple):
    """Information about a process using a port."""

    pid: int
    name: str
    cmdline: str
    port: int


# Keywords that identify this application's processes
OUR_PROCESS_KEYWORDS = [
    "provisioning_station",
    "provisioning-station",
    "uvicorn",
    "vite",
    "npm run dev",
    "node_modules/.bin/vite",
    "sensecraft",
]


def _find_listening_pids_on_port(port: int) -> set[int]:
    """Find PIDs that appear to be listening on a port."""
    system = platform.system()
    pids: set[int] = set()

    if system == "Darwin":
        # macOS: use lsof
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-n", "-P"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    pids.add(int(parts[1]))

    elif system == "Linux":
        # Linux: prefer ss
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            for match in re.finditer(r"pid=(\d+)", result.stdout):
                pids.add(int(match.group(1)))

        # Fallback to lsof when ss doesn't expose PIDs
        if not pids:
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-sTCP:LISTEN", "-n", "-P"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 2:
                        pids.add(int(parts[1]))

    elif system == "Windows":
        # Windows: use netstat
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts:
                        pids.add(int(parts[-1]))

    return pids


def is_port_bindable(port: int) -> bool:
    """Check whether a port can be bound right now."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("0.0.0.0", port))
            return True
    except OSError:
        return False


def find_processes_on_port(port: int) -> list[PortProcess]:
    """Find all processes listening on a specific port (cross-platform)."""
    processes: list[PortProcess] = []
    try:
        for pid in sorted(_find_listening_pids_on_port(port)):
            proc = _get_process_info(pid, port)
            if proc is not None:
                processes.append(proc)
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        print(f"  Warning: Error checking port {port}: {e}", file=sys.stderr)

    return processes


def _get_process_info(pid: int, port: int) -> PortProcess | None:
    """Get process information by PID."""
    try:
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline())
        return PortProcess(
            pid=pid,
            name=proc.name(),
            cmdline=cmdline,
            port=port,
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def is_our_process(proc: PortProcess) -> bool:
    """Check if a process appears to be from our application."""
    search_text = f"{proc.name} {proc.cmdline}".lower()
    return any(keyword.lower() in search_text for keyword in OUR_PROCESS_KEYWORDS)


def kill_process(proc: PortProcess, force: bool = False) -> bool:
    """Kill a process and its children."""
    try:
        process = psutil.Process(proc.pid)

        # Kill children first
        children = process.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass

        # Then kill the parent
        process.terminate()

        # Wait for graceful termination
        gone, alive = psutil.wait_procs([process] + children, timeout=3)

        # Force kill if still alive
        if alive and force:
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass

        return True
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        print(f"  Failed to kill process {proc.pid}: {e}", file=sys.stderr)
        return False


def cleanup_port(port: int, auto_kill: bool = True, verbose: bool = True) -> bool:
    """
    Check and cleanup a port.

    Returns:
        True if port is now available, False otherwise.
    """
    processes = find_processes_on_port(port)
    listening_pids = _find_listening_pids_on_port(port)
    unresolved_pids = set(listening_pids) - {p.pid for p in processes}

    if is_port_bindable(port):
        if unresolved_pids and verbose:
            print(
                f"  Port {port}: Available (ignoring stale listener entries: "
                + ", ".join(str(pid) for pid in sorted(unresolved_pids))
                + ")"
            )
        elif verbose:
            print(f"  Port {port}: Available")
        return True

    if not processes and not unresolved_pids:
        if verbose:
            print(f"  Port {port}: In use (owner unresolved)")
        return False

    if verbose:
        total = len(processes) + len(unresolved_pids)
        print(f"  Port {port}: In use by {total} process(es)")

    all_handled = True
    for proc in processes:
        if verbose:
            cmdline_display = proc.cmdline[:80] + (
                "..." if len(proc.cmdline) > 80 else ""
            )
            print(f"    PID {proc.pid} ({proc.name})")
            print(f"      Command: {cmdline_display}")

        if is_our_process(proc):
            if verbose:
                print("      -> Detected as leftover process from this application")

            if auto_kill:
                if verbose:
                    print(f"      -> Terminating process {proc.pid}...")
                if kill_process(proc, force=True):
                    if verbose:
                        print("      -> Successfully terminated")
                else:
                    if verbose:
                        print("      -> Failed to terminate", file=sys.stderr)
                    all_handled = False
            else:
                if verbose:
                    print("      -> Skipping (auto-kill disabled)")
                all_handled = False
        else:
            if verbose:
                print("      -> NOT a leftover process, will not terminate automatically")
                print(
                    "      -> Please close this application manually or use a different port"
                )
            all_handled = False

    for pid in sorted(unresolved_pids):
        if verbose:
            print(f"    PID {pid} (unresolved)")
            print("      -> Process info unavailable; cannot terminate safely")
        all_handled = False

    # Re-check real availability to avoid stale netstat entries or termination races.
    if not is_port_bindable(port):
        return False

    return all_handled


def main():
    parser = argparse.ArgumentParser(
        description="Cleanup ports by killing leftover processes from this application"
    )
    parser.add_argument(
        "ports",
        type=int,
        nargs="+",
        help="Port numbers to check and cleanup",
    )
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="Only check, don't kill processes",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output errors",
    )
    parser.add_argument(
        "--exit-on-blocked",
        action="store_true",
        help="Exit with error code if any port is blocked by non-application process",
    )

    args = parser.parse_args()

    if not args.quiet:
        print("Checking ports...")

    all_available = True
    blocked_by_other = False

    for port in args.ports:
        procs = find_processes_on_port(port)
        pids = _find_listening_pids_on_port(port)
        unresolved_pids = set(pids) - {p.pid for p in procs}
        if unresolved_pids or any(not is_our_process(proc) for proc in procs):
            blocked_by_other = True

        available = cleanup_port(
            port,
            auto_kill=not args.no_kill,
            verbose=not args.quiet,
        )
        if not available:
            all_available = False

    if not args.quiet:
        print()

    if args.exit_on_blocked and blocked_by_other:
        sys.exit(2)  # Port blocked by other application

    if not all_available:
        sys.exit(1)  # Some ports still not available

    sys.exit(0)


if __name__ == "__main__":
    main()
