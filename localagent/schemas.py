"""Pydantic schemas for LocalAgent request/response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class ToolName(str, Enum):
    """Available subagent tools."""

    FILE_SCANNER = "file_scanner"
    SUMMARIZER = "summarizer"
    SMART_SEARCH = "smart_search"


class InputRefType(str, Enum):
    """Types of input references."""

    GLOB = "glob"
    HASH = "hash"
    CONTENT = "content"


class ResultRefType(str, Enum):
    """Types of result references."""

    FILE = "file"
    CACHE = "cache"


class TaskStatus(str, Enum):
    """Task execution status."""

    COMPLETED = "completed"
    FAILED = "failed"


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

    task_id: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Unique identifier for this delegation task",
    )
    tool_name: ToolName = Field(..., description="Target subagent to execute")
    input_refs: list[InputRef] = Field(
        default_factory=list,
        description="Input references (patterns, hashes, or content)",
    )
    root_dir: str | None = Field(
        default=None,
        description="Root directory for file operations (defaults to cwd)",
    )
    max_summary_tokens: int = Field(
        default=200,
        ge=50,
        le=500,
        description="Maximum tokens in summary response",
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

    task_id: str
    status: TaskStatus
    summary: str = Field(..., max_length=1500, description="Human-readable summary")
    result_refs: list[ResultRef] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)


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


class SearchMatch(BaseModel):
    """A single search match from ChromaDB."""

    file_path: str
    chunk_content: str
    distance: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SmartSearchResult(BaseModel):
    """Result from smart_search subagent."""

    query: str
    matches: list[SearchMatch]
    summary: str
    summary_token_count: int
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    collection_searched: str
    total_matches: int


# --- Health Check ---


class HealthResponse(BaseModel):
    """Health check response."""

    broker: Literal["healthy", "unhealthy"] = "healthy"
    ollama: Literal["healthy", "unhealthy"] = "healthy"
