"""
project_tools.py
----------------
Phase 55 — Agentic project tools for the Telegram AI Assistant.

These tools allow the LLM to interact with the GrokSniper project:
read files, list directories, write files, and execute terminal commands.
"""

import os
import shlex
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root — always resolved relative to this file
_HERE = Path(__file__).resolve()
PROJECT_ROOT = _HERE.parents[3]  # .../sniper_bot/

# Safety: restrict all file operations to within the project root
def _safe_path(relative_path: str) -> Path:
    """Resolve a path and ensure it stays within PROJECT_ROOT."""
    resolved = (PROJECT_ROOT / relative_path).resolve()
    if not str(resolved).startswith(str(PROJECT_ROOT)):
        raise PermissionError(f"Access denied: path {relative_path} escapes the project root.")
    return resolved


def read_file(relative_path: str) -> str:
    """
    Read the contents of a file within the project.
    Args:
        relative_path: Path relative to the project root, e.g. 'backend/src/agents/board_of_directors.py'
    Returns:
        The file contents as a string.
    """
    try:
        path = _safe_path(relative_path)
        if not path.is_file():
            return f"❌ Error: '{relative_path}' is not a file or does not exist."
        
        # Limit file size to prevent memory issues
        size = path.stat().st_size
        if size > 100_000:  # 100 KB limit
            return f"⚠️ File is too large ({size:,} bytes). Showing first 2000 characters.\n\n" + path.read_text(encoding="utf-8", errors="replace")[:2000]
        
        return path.read_text(encoding="utf-8", errors="replace")
    except PermissionError as e:
        return f"🔒 {e}"
    except Exception as e:
        return f"❌ Error reading file: {e}"


def list_directory(relative_path: str = ".") -> str:
    """
    List files and directories at the given path within the project.
    Args:
        relative_path: Path relative to the project root. Defaults to root.
    Returns:
        A formatted directory listing.
    """
    try:
        path = _safe_path(relative_path)
        if not path.is_dir():
            return f"❌ Error: '{relative_path}' is not a directory."
        
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        
        # Ignore common noise
        ignore = {".git", "__pycache__", "node_modules", "venv", ".next", ".venv"}
        
        lines = [f"📁 Listing: {relative_path}/\n"]
        for entry in entries:
            if entry.name in ignore:
                continue
            prefix = "📂" if entry.is_dir() else "📄"
            size_str = ""
            if entry.is_file():
                size = entry.stat().st_size
                if size < 1024:
                    size_str = f" ({size} B)"
                else:
                    size_str = f" ({size / 1024:.1f} KB)"
            lines.append(f"  {prefix} {entry.name}{size_str}")
        
        if len(lines) == 1:
            lines.append("  (empty directory)")
        
        return "\n".join(lines)
    except PermissionError as e:
        return f"🔒 {e}"
    except Exception as e:
        return f"❌ Error listing directory: {e}"


def write_file(relative_path: str, content: str) -> str:
    """
    Write content to a file within the project. Creates parent directories if needed.
    Args:
        relative_path: Path relative to the project root.
        content: The content to write.
    Returns:
        A success or error message.
    """
    try:
        path = _safe_path(relative_path)
        
        # Safety: never overwrite .env or critical configs accidentally
        protected = {".env", ".gitignore"}
        if path.name in protected:
            return f"🔒 Refused to overwrite protected file: {path.name}. Edit it manually."
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info(f"AI Assistant wrote file: {path}")
        return f"✅ Successfully wrote {len(content)} characters to {relative_path}"
    except PermissionError as e:
        return f"🔒 {e}"
    except Exception as e:
        return f"❌ Error writing file: {e}"


def run_command(command: str, timeout: int = 30) -> str:
    """
    Execute a shell command in the project root directory.
    Args:
        command: The command string to run.
        timeout: Max seconds to wait (default 30).
    Returns:
        Combined stdout + stderr output.
    """
    # Safety: block obviously dangerous commands
    blocked_patterns = ["rm -rf /", "format c:", "del /s /q c:", "shutdown", "reboot"]
    cmd_lower = command.lower().strip()
    for pattern in blocked_patterns:
        if pattern in cmd_lower:
            return f"🔒 Blocked dangerous command: {command}"
    
    try:
        logger.info(f"AI Assistant executing: {command}")
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += "\n[STDERR]\n" + result.stderr
        
        if result.returncode != 0:
            output += f"\n\n⚠️ Exit code: {result.returncode}"
        else:
            output += "\n\n✅ Command completed successfully."
        
        # Truncate very long output
        if len(output) > 3000:
            output = output[:3000] + "\n\n... (output truncated)"
        
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return f"⏰ Command timed out after {timeout} seconds."
    except Exception as e:
        return f"❌ Error executing command: {e}"
