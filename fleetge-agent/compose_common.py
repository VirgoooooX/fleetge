"""Compose CLI options and file utilities shared by both agent entry points."""

import os
import re
import shutil
import stat
import tempfile
from contextlib import ExitStack, contextmanager

COMPOSE_FILE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
SERVICE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$")
_SENSITIVE_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|TOKEN|SECRET|KEY|AUTH|CREDENTIAL)[A-Z0-9_]*\s*[=:]\s*)([^\s'\"`]+)"
)
_BEARER_RE = re.compile(r"(?i)(Authorization:\s*)Bearer\s+[A-Za-z0-9._~+/=-]+")


def redact_sensitive_text(text: str) -> str:
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    return _SENSITIVE_RE.sub(r"\1[REDACTED]", text)


def compose_args(
    stack_dir: str,
    command: str,
    *extra: str,
    base_dir: str,
    host_project_dir: str | None = None,
    compose_file: str | None = None,
) -> list[str]:
    args = ["compose", command, *extra]
    if host_project_dir:
        args[1:1] = ["--project-directory", host_project_dir]
        if compose_file:
            args[3:3] = ["--file", compose_file]
    global_env_path = os.path.join(os.path.realpath(base_dir), "global.env")
    local_env_path = os.path.join(stack_dir, ".env")
    if os.path.isfile(global_env_path):
        if os.path.isfile(local_env_path):
            args[1:1] = ["--env-file", local_env_path if host_project_dir else "./.env"]
        args[1:1] = ["--env-file", global_env_path if host_project_dir else "../global.env"]
    elif host_project_dir and os.path.isfile(local_env_path):
        args[1:1] = ["--env-file", local_env_path]
    return args


def _preserve_owner(path: str, info: os.stat_result, *, follow_symlinks: bool = True) -> None:
    if os.name == "posix":
        current = os.stat(path, follow_symlinks=follow_symlinks)
        owner = info.st_uid, info.st_gid
        if (current.st_uid, current.st_gid) != owner:
            os.chown(path, *owner, follow_symlinks=follow_symlinks)


@contextmanager
def staged_text(path: str, content: str):
    # Follow existing symlinks and preserve file permissions on replacement.
    target = os.path.realpath(path)
    try:
        previous = os.stat(target)
    except FileNotFoundError:
        previous = None
    with tempfile.TemporaryDirectory(prefix=".fleetge-write-", dir=os.path.dirname(target)) as staging:
        temp_path = os.path.join(staging, "content")
        with open(temp_path, "x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            if previous is not None:
                _preserve_owner(temp_path, previous)
                os.chmod(temp_path, stat.S_IMODE(previous.st_mode))
            os.fsync(handle.fileno())
        yield temp_path, target


def atomic_write_text(path: str, content: str) -> None:
    with staged_text(path, content) as (temp_path, target):
        os.replace(temp_path, target)


def commit_stack_files(changes: list[tuple[str | None, str]]) -> None:
    """Publish staged config files, restoring earlier files on failure."""
    with ExitStack() as backups:
        previous = {}
        for _, target in changes:
            if target in previous:
                raise OSError(f"Stack files refer to the same path: {target}")
            if not os.path.lexists(target):
                previous[target] = None
                continue
            backup_dir = backups.enter_context(tempfile.TemporaryDirectory(
                prefix=".fleetge-backup-", dir=os.path.dirname(target),
            ))
            backup = os.path.join(backup_dir, "original")
            info = os.lstat(target)
            shutil.copy2(target, backup, follow_symlinks=False)
            _preserve_owner(backup, info, follow_symlinks=False)
            if not stat.S_ISLNK(info.st_mode):
                os.chmod(backup, stat.S_IMODE(info.st_mode))
            previous[target] = backup

        applied = []
        try:
            for temp_path, target in changes:
                if temp_path is None:
                    os.unlink(target)
                else:
                    os.replace(temp_path, target)
                applied.append(target)
        except OSError as error:
            for target in reversed(applied):
                try:
                    if (backup := previous[target]) is None:
                        os.unlink(target)
                    else:
                        os.replace(backup, target)
                except OSError as rollback_error:
                    error.add_note(f"Could not restore {target}: {rollback_error}")
            raise
