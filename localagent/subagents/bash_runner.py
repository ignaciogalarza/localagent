"""Bash runner subagent with bubblewrap sandbox for secure command execution."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from localagent.schemas import BashResult, PolicyId

logger = logging.getLogger(__name__)

# Output limits
MAX_OUTPUT_BYTES = 10 * 1024  # 10KB

# Default timeout
DEFAULT_TIMEOUT = 10  # seconds

# Check if bubblewrap is available
BWRAP_PATH = shutil.which("bwrap")


class CommandBlockedError(Exception):
    """Raised when a command is blocked by policy."""

    pass


class SandboxUnavailableError(Exception):
    """Raised when the sandbox is not available."""

    pass


# Policy allowlists (regex patterns)
READONLY_ALLOWLIST = [
    r"^grep\s",
    r"^cat\s",
    r"^ls(\s|$)",
    r"^find\s",
    r"^wc\s",
    r"^head\s",
    r"^tail\s",
    r"^tree(\s|$)",
    r"^file\s",
    r"^stat\s",
    r"^pwd$",
    r"^echo\s",
    r"^which\s",
    r"^type\s",
    r"^env$",
    r"^printenv",
]

BUILD_ALLOWLIST = READONLY_ALLOWLIST + [
    r"^make(\s|$)",
    r"^npm run\s",
    r"^npm test",
    r"^pip list",
    r"^pip show\s",
    r"^python -m pytest",
    r"^python -m py_compile",
    r"^cargo check",
    r"^cargo test",
    r"^cargo build",
    r"^go build",
    r"^go test",
    r"^go vet",
]

# Universal blocklist (always denied)
BLOCKLIST = [
    r"rm\s+-rf",
    r"rm\s+.*\*",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bsudo\b",
    r"\bsu\s",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\binit\b",
    r"\bsystemctl\b",
    r"npm install",
    r"pip install",
    r"cargo install",
    r"go install",
    r"apt\s",
    r"apt-get\s",
    r"yum\s",
    r"dnf\s",
    r"pacman\s",
    r">\s*/",  # Redirect to root
    r">\s*~",  # Redirect to home
    r"\|.*sh\b",  # Pipe to shell
    r"`",  # Command substitution
    r"\$\(",  # Command substitution
    r";\s*rm",  # Command chaining with rm
    r"&&\s*rm",  # Command chaining with rm
]


def _get_allowlist(policy_id: PolicyId) -> list[str]:
    """Get allowlist for the given policy."""
    if policy_id == PolicyId.BUILD:
        return BUILD_ALLOWLIST
    # READONLY and DEFAULT use the same allowlist
    return READONLY_ALLOWLIST


def validate_command(command: str, policy_id: PolicyId) -> tuple[bool, str]:
    """Validate command against policy allowlist and blocklist.

    Args:
        command: The command to validate
        policy_id: The policy to apply

    Returns:
        Tuple of (allowed, reason)
    """
    command = command.strip()

    # Check blocklist first (deny wins)
    for pattern in BLOCKLIST:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Blocked: matches dangerous pattern '{pattern}'"

    # Check allowlist
    allowlist = _get_allowlist(policy_id)
    for pattern in allowlist:
        if re.match(pattern, command, re.IGNORECASE):
            return True, "Allowed by policy"

    return False, f"Not in allowlist for policy '{policy_id.value}'"


def _build_bwrap_command(
    command: str,
    work_dir: str,
    policy_id: PolicyId,
) -> list[str]:
    """Build the bubblewrap command with appropriate restrictions."""
    if not BWRAP_PATH:
        raise SandboxUnavailableError("bubblewrap (bwrap) is not installed")

    bwrap_args = [
        BWRAP_PATH,
        # Read-only bind the entire filesystem
        "--ro-bind", "/", "/",
        # Bind work directory with write access
        "--bind", work_dir, work_dir,
        # Mount /proc for process tools to work
        "--proc", "/proc",
        # Mount /dev for basic device access
        "--dev", "/dev",
        # Create new /tmp
        "--tmpfs", "/tmp",
        # Set working directory
        "--chdir", work_dir,
        # Die with parent
        "--die-with-parent",
        # Run the command via sh
        "--",
        "/bin/sh", "-c", command,
    ]

    return bwrap_args


def _truncate_output(output: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Truncate output to max_bytes."""
    if len(output.encode("utf-8", errors="replace")) <= max_bytes:
        return output

    # Truncate by bytes, preserving valid UTF-8
    encoded = output.encode("utf-8", errors="replace")[:max_bytes]
    truncated = encoded.decode("utf-8", errors="replace")
    return truncated + "\n... [output truncated]"


def run_bash(
    command: str,
    work_dir: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
    policy_id: PolicyId = PolicyId.DEFAULT,
    use_sandbox: bool = True,
) -> BashResult:
    """Execute a bash command in a sandboxed environment.

    Args:
        command: The command to execute
        work_dir: Working directory (defaults to current directory)
        timeout_seconds: Timeout in seconds
        policy_id: Execution policy
        use_sandbox: Whether to use bubblewrap sandbox

    Returns:
        BashResult with stdout, stderr, exit code, and metadata
    """
    command = command.strip()
    work_dir = work_dir or str(Path.cwd())

    # Validate command against policy
    allowed, reason = validate_command(command, policy_id)
    if not allowed:
        logger.warning(f"Command blocked: {command} - {reason}")
        raise CommandBlockedError(reason)

    logger.info(f"Executing command: {command} (policy: {policy_id.value})")

    was_sandboxed = False
    try:
        if use_sandbox and BWRAP_PATH:
            # Use bubblewrap sandbox
            bwrap_cmd = _build_bwrap_command(command, work_dir, policy_id)
            was_sandboxed = True

            result = subprocess.run(
                bwrap_cmd,
                capture_output=True,
                timeout=timeout_seconds,
                text=True,
            )
        else:
            # Fallback: run directly (less secure)
            if use_sandbox and not BWRAP_PATH:
                logger.warning("bubblewrap not available, running without sandbox")

            result = subprocess.run(
                ["/bin/sh", "-c", command],
                capture_output=True,
                timeout=timeout_seconds,
                text=True,
                cwd=work_dir,
            )

        stdout = _truncate_output(result.stdout)
        stderr = _truncate_output(result.stderr)

        return BashResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.returncode,
            was_sandboxed=was_sandboxed,
            command_executed=command,
            confidence=1.0,
        )

    except subprocess.TimeoutExpired:
        logger.warning(f"Command timed out after {timeout_seconds}s: {command}")
        return BashResult(
            stdout="",
            stderr=f"Command timed out after {timeout_seconds} seconds",
            exit_code=-1,
            was_sandboxed=was_sandboxed,
            command_executed=command,
            confidence=0.5,
        )

    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        return BashResult(
            stdout="",
            stderr=str(e),
            exit_code=-1,
            was_sandboxed=was_sandboxed,
            command_executed=command,
            confidence=0.0,
        )


def check_sandbox_available() -> bool:
    """Check if bubblewrap sandbox is available."""
    return BWRAP_PATH is not None
