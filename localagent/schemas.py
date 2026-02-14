"""Pydantic schemas for LocalAgent request/response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Available subagent tools."""

    FILE_SCANNER = "file_scanner"
    SUMMARIZER = "summarizer"
    BASH_RUNNER = "bash_runner"
    FETCH_DETAIL = "fetch_detail"


class PolicyId(str, Enum):
    """Available execution policies."""

    DEFAULT = "default"
    READONLY = "readonly"
    BUILD = "build"


class InputRefType(str, Enum):
    """Types of input references."""

    GLOB = "glob"
    HASH = "hash"
    COMMAND = "command"
    CONTENT = "content"


class ResultRefType(str, Enum):
    """Types of result references."""

    FILE = "file"
    MEMORY = "memory"
    CACHE = "cache"


class TaskStatus(str, Enum):
    """Task execution status."""

    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    QUEUED = "queued"


# --- Input/Output References ---


class InputRef(BaseModel):
    """Reference to input data for a task."""

    type: InputRefType
    value: str


class ResultRef(BaseModel):
    """Reference to a result artifact."""

    type: ResultRefType
    path: str | None = None
    hash: str = Field(..., pattern=r"^sha256:[a-f0-9]{64}$")
    size_bytes: int | None = None


# --- Request Schemas ---


class DelegationRequest(BaseModel):
    """Request to delegate a task to a subagent."""

    session_id: str | None = Field(
        default=None,
        pattern=r"^sess-[a-zA-Z0-9]+$",
        description="Optional session ID for context continuity",
    )
    task_id: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Unique identifier for this delegation task",
    )
    tool_name: ToolName = Field(..., description="Target subagent to execute")
    input_refs: list[InputRef] = Field(
        default_factory=list,
        description="Input references (patterns, hashes, or commands)",
    )
    max_summary_tokens: int = Field(
        default=200,
        ge=50,
        le=500,
        description="Maximum tokens in summary response",
    )
    policy_id: PolicyId = Field(
        default=PolicyId.DEFAULT,
        description="Execution policy for the task",
    )


class FetchDetailRequest(BaseModel):
    """Request to fetch full content for a result reference."""

    task_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    hash: str = Field(..., pattern=r"^sha256:[a-f0-9]{64}$")
    format: Literal["raw", "summary"] = "raw"
    max_tokens: int | None = None


# --- Response Schemas ---


class DelegationResponse(BaseModel):
    """Response from a delegated task."""

    session_id: str | None = None
    task_id: str
    status: TaskStatus
    queue_position: int | None = None
    summary: str = Field(..., max_length=1500, description="Human-readable summary")
    result_refs: list[ResultRef] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    audit_log_hashes: list[str] = Field(default_factory=list)


class FetchDetailResponse(BaseModel):
    """Response with full content for a result reference."""

    task_id: str
    status: TaskStatus
    content: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    hash: str


class ErrorResponse(BaseModel):
    """Error response for failed requests."""

    detail: str
    task_id: str | None = None
    error_code: str | None = None


# --- Subagent Result Schemas ---


class ScanResult(BaseModel):
    """Result from file_scanner subagent."""

    summary: str
    summary_token_count: int
    result_refs: list[ResultRef]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    files_scanned: int = 0
    total_bytes: int = 0


class SummarizeResult(BaseModel):
    """Result from summarizer subagent."""

    summary: str
    token_count: int
    was_compressed: bool
    model_used: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class BashResult(BaseModel):
    """Result from bash_runner subagent."""

    stdout: str
    stderr: str
    exit_code: int
    was_sandboxed: bool = True
    command_executed: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


# --- Health Check ---


class HealthResponse(BaseModel):
    """Health check response."""

    broker: Literal["healthy", "unhealthy"] = "healthy"
    ollama: Literal["healthy", "unhealthy", "recovering"] = "healthy"
    queue_depth: int = 0
    last_ollama_check: str | None = None
