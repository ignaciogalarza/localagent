# Bash Runner Security Model

## Overview

The bash_runner subagent executes shell commands in a restricted sandbox environment to prevent malicious or accidental system damage.

## Sandbox Implementation

### Bubblewrap Configuration

Commands are executed via [bubblewrap](https://github.com/containers/bubblewrap) with the following restrictions:

```bash
bwrap \
  --ro-bind / /           # Read-only root filesystem
  --bind $WORK_DIR $WORK_DIR  # Write access only to working directory
  --unshare-net           # No network access
  --unshare-pid           # Isolated PID namespace
  --tmpfs /tmp            # Fresh /tmp
  --cap-drop ALL          # Drop all capabilities
  --die-with-parent       # Terminate if parent dies
  -- /bin/sh -c "$COMMAND"
```

### Security Properties

| Property | Enforcement |
|----------|-------------|
| No network access | `--unshare-net` |
| Read-only filesystem | `--ro-bind / /` |
| Limited write access | Only `$WORK_DIR` is writable |
| No privilege escalation | `--cap-drop ALL` |
| Process isolation | `--unshare-pid` |
| Clean environment | Fresh `/tmp` per execution |

## Policy-Based Access Control

### Policy: `readonly` (Default)

Allowed commands:
- `grep`, `cat`, `ls`, `find`, `wc`
- `head`, `tail`, `tree`, `file`, `stat`
- `pwd`, `echo`, `which`, `type`

### Policy: `build`

Extends `readonly` with:
- `make`
- `npm run`, `npm test`
- `pip list`, `pip show`
- `python -m pytest`
- `cargo check`, `cargo test`, `cargo build`
- `go build`, `go test`, `go vet`

**Still blocked**: `npm install`, `pip install`, `cargo install`, `go install`

## Universal Blocklist

The following patterns are **always blocked** regardless of policy:

```python
BLOCKLIST = [
    r"rm\s+-rf",           # Recursive forced deletion
    r"rm\s+.*\*",          # Glob deletion
    r"\bcurl\b",           # Network requests
    r"\bwget\b",           # Network requests
    r"\bchmod\b",          # Permission changes
    r"\bchown\b",          # Ownership changes
    r"\bsudo\b",           # Privilege escalation
    r"\bsu\s",             # User switching
    r"\bdd\b",             # Disk operations
    r"\bmkfs\b",           # Filesystem creation
    r"\bshutdown\b",       # System shutdown
    r"\breboot\b",         # System reboot
    r"npm install",        # Package installation
    r"pip install",        # Package installation
    r"apt\s",              # Package manager
    r">\s*/",              # Redirect to root
    r"\|.*sh\b",           # Pipe to shell
    r"`",                  # Command substitution
    r"\$\(",               # Command substitution
]
```

## Timeout Enforcement

- Default timeout: 10 seconds
- Maximum timeout: 60 seconds
- Long-running processes are terminated via SIGKILL

## Output Handling

- stdout/stderr limited to 10KB
- Excess output is truncated with notice
- Binary output is not supported

## Security Testing

The test suite (`tests/test_bash_runner.py`) verifies:

1. **Allowlist enforcement**: Only permitted commands execute
2. **Blocklist enforcement**: Dangerous patterns are rejected
3. **Sandbox isolation**: Network and filesystem restrictions work
4. **Timeout handling**: Long commands are terminated
5. **Output truncation**: Large outputs don't cause issues

## Escape Vector Analysis

| Vector | Mitigation |
|--------|------------|
| Command substitution | Blocked: `` ` `` and `$()` patterns |
| Pipe to shell | Blocked: `\| sh` pattern |
| Redirect to system files | Blocked: `> /` pattern |
| Environment manipulation | Clean environment in sandbox |
| Symlink attacks | Read-only root prevents creation |
| Race conditions | PID namespace isolation |

## Limitations

1. **bubblewrap required**: Sandbox requires bwrap to be installed
2. **Linux only**: bubblewrap is Linux-specific
3. **Pattern-based blocking**: Novel attack patterns may not be caught
4. **No semantic analysis**: Commands are validated by pattern, not intent

## Recommendations

1. Always run with `use_sandbox=True` in production
2. Use `readonly` policy unless build commands are required
3. Validate working directory before execution
4. Monitor audit logs for unusual patterns
5. Keep allowlists minimal
