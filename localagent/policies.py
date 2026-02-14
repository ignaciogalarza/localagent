"""Policy definitions for LocalAgent task execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from localagent.schemas import PolicyId


class ConcurrencyMode(str, Enum):
    """Concurrency modes for task execution."""

    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


@dataclass
class Policy:
    """Execution policy definition."""

    policy_id: PolicyId
    description: str
    concurrency: ConcurrencyMode
    max_concurrent_tasks: int
    allowed_tools: list[str]
    file_read_allowed: bool = True
    file_write_allowed: bool = False
    network_allowed: bool = False
    bash_allowlist: list[str] = field(default_factory=list)
    bash_blocklist: list[str] = field(default_factory=list)


# Policy definitions
POLICIES: dict[PolicyId, Policy] = {
    PolicyId.DEFAULT: Policy(
        policy_id=PolicyId.DEFAULT,
        description="Default policy with read-only bash commands",
        concurrency=ConcurrencyMode.PARALLEL,
        max_concurrent_tasks=4,
        allowed_tools=["file_scanner", "summarizer", "bash_runner", "fetch_detail"],
        file_read_allowed=True,
        file_write_allowed=False,
        network_allowed=False,
        bash_allowlist=[
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
        ],
    ),
    PolicyId.READONLY: Policy(
        policy_id=PolicyId.READONLY,
        description="Read-only policy with limited bash commands",
        concurrency=ConcurrencyMode.PARALLEL,
        max_concurrent_tasks=4,
        allowed_tools=["file_scanner", "summarizer", "bash_runner", "fetch_detail"],
        file_read_allowed=True,
        file_write_allowed=False,
        network_allowed=False,
        bash_allowlist=[
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
        ],
    ),
    PolicyId.BUILD: Policy(
        policy_id=PolicyId.BUILD,
        description="Build policy with sequential execution and build commands",
        concurrency=ConcurrencyMode.SEQUENTIAL,
        max_concurrent_tasks=1,
        allowed_tools=["file_scanner", "summarizer", "bash_runner", "fetch_detail"],
        file_read_allowed=True,
        file_write_allowed=False,  # Still no direct writes, only via build commands
        network_allowed=False,
        bash_allowlist=[
            # Readonly commands
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
            # Build commands
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
        ],
        bash_blocklist=[
            r"npm install",
            r"pip install",
            r"cargo install",
            r"go install",
            r"sudo",
            r"su\s",
        ],
    ),
}


def get_policy(policy_id: PolicyId) -> Policy:
    """Get policy by ID."""
    return POLICIES[policy_id]


def is_tool_allowed(policy_id: PolicyId, tool_name: str) -> bool:
    """Check if a tool is allowed under the given policy."""
    policy = get_policy(policy_id)
    return tool_name in policy.allowed_tools


def get_concurrency_mode(policy_id: PolicyId) -> ConcurrencyMode:
    """Get concurrency mode for a policy."""
    return get_policy(policy_id).concurrency


def get_max_concurrent_tasks(policy_id: PolicyId) -> int:
    """Get maximum concurrent tasks for a policy."""
    return get_policy(policy_id).max_concurrent_tasks
