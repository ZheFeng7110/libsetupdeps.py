"""
`libsetupdeps.py <https://github.com/ZheFeng7110/libsetupdeps.py.git>`_

A lightweight source-dependency setup helper for C/C++ projects.

Usage:
    1) Put this file in your project root.
    2) Create your own entry script (for example: setupdeps.py).
    3) In that script, import and call APIs such as add_resource/add_git_resource.
    4) Run: `python <your-script>.py [--append-to-gitignore] [--reset] [--quiet] [--timeout=<seconds>] [--help] [--version]`

Note:
    This library only fetches source code. Build/install/link are intentionally handled
    by users in their own toolchain workflow.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import URLError

import __main__

_STATE_FILE_NAME = ".libsetupdeps_state.json"
_CACHE_DIR_NAME = ".libsetupdeps_cache"
__version__ = "0.1.0"
_META_FLAGS_HANDLED = False
_DEFAULT_TIMEOUT_SECONDS = 120


class LibSetupDepsError(RuntimeError):
    """Raised when dependency setup fails with actionable context."""

    def __init__(
        self,
        *,
        name: str,
        url: str,
        path: str,
        stage: str,
        reason: str,
        suggestion: str | None = None,
    ) -> None:
        details = (
            f"[{stage}] dependency='{name}' url='{url}' path='{path}': {reason}"
            + (f" Suggestion: {suggestion}" if suggestion else "")
        )
        super().__init__(details)


def _get_script_dir() -> Path:
    main_file = getattr(__main__, "__file__", None)
    if main_file:
        return Path(main_file).resolve().parent
    return Path.cwd().resolve()


def _resolve_user_path(user_path: str) -> Path:
    path_obj = Path(user_path)
    if path_obj.is_absolute():
        return path_obj.resolve()
    return (_get_script_dir() / path_obj).resolve()


def _cache_dir() -> Path:
    directory = _get_script_dir() / _CACHE_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _state_file() -> Path:
    return _cache_dir() / _STATE_FILE_NAME


def _load_state() -> dict[str, Any]:
    file_path = _state_file()
    if not file_path.exists():
        return {"resources": {}}
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid state file format: {file_path}")
    data.setdefault("resources", {})
    if not isinstance(data["resources"], dict):
        raise ValueError(f"Invalid state file format: {file_path}")
    return data


def _save_state(state: dict[str, Any]) -> None:
    state_path = _state_file()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _normalize_non_empty(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"'{field_name}' must not be empty.")
    return normalized


def _has_cli_flag(flag: str) -> bool:
    return flag in set(sys.argv[1:])


def _help_text(script_name: str | None = None) -> str:
    entry_script = script_name or Path(sys.argv[0] if sys.argv else "setupdeps.py").name
    return "\n".join(
        [
            "libsetupdeps.py usage:",
            f"  python {entry_script} [--append-to-gitignore] [--reset] [--quiet] [--timeout=<seconds>]",
            f"  python {entry_script} --version",
            f"  python {entry_script} --help",
            "",
            "Options:",
            "  --append-to-gitignore  Append dependency paths and .libsetupdeps_cache to .gitignore.",
            "  --reset                Delete configured paths before re-fetching.",
            "  --quiet                Print status only, suppress progress output.",
            f"  --timeout=<seconds>    Timeout for download/clone operations (default: {_DEFAULT_TIMEOUT_SECONDS}).",
            "  --version              Print libsetupdeps.py version and exit.",
            "  --help                 Print this help message and exit.",
        ]
    )


def _handle_meta_flags_once() -> None:
    global _META_FLAGS_HANDLED
    if _META_FLAGS_HANDLED:
        return

    if _has_cli_flag("--version"):
        print(__version__)
        _META_FLAGS_HANDLED = True
        raise SystemExit(0)
    if _has_cli_flag("--help"):
        print(_help_text())
        _META_FLAGS_HANDLED = True
        raise SystemExit(0)

    _META_FLAGS_HANDLED = True


def _handle_direct_invocation() -> None:
    args = set(sys.argv[1:])
    if "--version" in args:
        print(__version__)
    if "--help" in args:
        print(_help_text("setupdeps.py"))

    print(
        "libsetupdeps.py is a library module. Please create your own dependency setup script "
        "(for example: setupdeps.py), import libsetupdeps, and call its APIs there."
    )
    raise SystemExit(0)


def _to_gitignore_entry(user_path: str) -> str:
    path_obj = Path(user_path)
    if path_obj.is_absolute():
        try:
            relative_path = path_obj.resolve().relative_to(_get_script_dir())
            return relative_path.as_posix()
        except ValueError:
            return path_obj.resolve().as_posix()
    return path_obj.as_posix()


def _append_path_to_gitignore(user_path: str) -> None:
    gitignore_file = _get_script_dir() / ".gitignore"
    entry = _to_gitignore_entry(user_path).strip().rstrip("/")
    if not entry:
        return

    existing_lines: list[str] = []
    if gitignore_file.exists():
        existing_lines = gitignore_file.read_text(encoding="utf-8").splitlines()
        if entry in existing_lines:
            return

    prefix_newline = False
    if gitignore_file.exists():
        content = gitignore_file.read_text(encoding="utf-8")
        prefix_newline = bool(content) and not content.endswith("\n")

    with gitignore_file.open("a", encoding="utf-8") as file:
        if prefix_newline:
            file.write("\n")
        file.write(f"{entry}\n")


def _remove_configured_path(target_path: Path) -> None:
    if not target_path.exists():
        return
    if target_path.is_dir() and not target_path.is_symlink():
        shutil.rmtree(target_path)
        return
    target_path.unlink()


def _is_quiet_mode() -> bool:
    return _has_cli_flag("--quiet")


def _timeout_seconds() -> int:
    for argument in sys.argv[1:]:
        if not argument.startswith("--timeout="):
            continue
        raw_value = argument.split("=", 1)[1].strip()
        if not raw_value:
            raise ValueError("'--timeout' value must not be empty.")
        try:
            timeout_value = int(raw_value)
        except ValueError as exc:
            raise ValueError("'--timeout' must be an integer in seconds.") from exc
        if timeout_value <= 0:
            raise ValueError("'--timeout' must be greater than 0.")
        return timeout_value
    return _DEFAULT_TIMEOUT_SECONDS


def _status_line(message: str) -> None:
    print(message, flush=True)


def _download_to_file(
    *,
    name: str,
    url: str,
    destination_file: Path,
    timeout_seconds: int,
    show_progress: bool,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    progress_next_milestone = 0
    downloaded_size = 0

    with request.urlopen(url, timeout=timeout_seconds) as response:
        headers = getattr(response, "headers", {}) or {}
        total_size_raw = headers.get("Content-Length") if hasattr(headers, "get") else None
        total_size = int(total_size_raw) if total_size_raw and total_size_raw.isdigit() else None

        with destination_file.open("wb") as output:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Download exceeded timeout of {timeout_seconds} seconds."
                    )

                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                downloaded_size += len(chunk)

                if not show_progress:
                    continue

                if total_size:
                    percentage = int((downloaded_size * 100) / total_size)
                    if percentage >= progress_next_milestone:
                        _status_line(
                            f"Download progress [{name}]: {percentage}% ({downloaded_size}/{total_size} bytes)"
                        )
                        progress_next_milestone = min(100, percentage + 10)
                elif downloaded_size >= progress_next_milestone:
                    _status_line(
                        f"Download progress [{name}]: {downloaded_size} bytes"
                    )
                    progress_next_milestone = downloaded_size + (1024 * 1024)

    if show_progress and total_size and downloaded_size != total_size:
        _status_line(
            f"Download progress [{name}]: 100% ({downloaded_size}/{total_size} bytes)"
        )


def _is_archive_filename(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered.endswith(".zip")
        or lowered.endswith(".tar.gz")
        or lowered.endswith(".tgz")
        or lowered.endswith(".tar.xz")
    )


def _download_file_name(url: str, fallback_name: str) -> str:
    parsed = parse.urlparse(url)
    file_name = Path(parsed.path).name.strip()
    if file_name:
        return file_name
    return fallback_name


def _temp_file_suffix(file_name: str) -> str:
    lowered = file_name.lower()
    if lowered.endswith(".tar.gz"):
        return ".tar.gz"
    if lowered.endswith(".tar.xz"):
        return ".tar.xz"
    if lowered.endswith(".tgz"):
        return ".tgz"
    suffix = Path(file_name).suffix
    return suffix if suffix else ".tmp"


def _extract_archive(archive_file: Path, target_dir: Path) -> None:
    file_name = archive_file.name.lower()
    if file_name.endswith(".zip"):
        with zipfile.ZipFile(archive_file, "r") as archive:
            archive.extractall(target_dir)
        return
    if (
        file_name.endswith(".tar.gz")
        or file_name.endswith(".tgz")
        or file_name.endswith(".tar.xz")
    ):
        with tarfile.open(archive_file, "r:*") as archive:
            archive.extractall(target_dir, filter="data")
        return
    raise ValueError(f"Unsupported archive format: {archive_file.name}")


def _run_git(
    args: list[str],
    *,
    name: str,
    url: str,
    path: str,
    stage: str,
    timeout_seconds: int,
    show_progress: bool,
) -> None:
    try:
        if not show_progress:
            subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return

        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines: list[str] = []
        start_time = time.monotonic()
        assert process.stdout is not None

        while True:
            if time.monotonic() - start_time > timeout_seconds:
                process.kill()
                process.wait()
                raise TimeoutError(
                    f"Git {stage} exceeded timeout of {timeout_seconds} seconds."
                )

            line = process.stdout.readline()
            if line:
                line_text = line.rstrip()
                output_lines.append(line_text)
                _status_line(line_text)
                continue

            if process.poll() is not None:
                break
            time.sleep(0.05)

        return_code = process.wait()
        if return_code != 0:
            stderr = "\n".join(output_lines[-20:])
            raise subprocess.CalledProcessError(
                returncode=return_code,
                cmd=args,
                stderr=stderr,
            )
    except TimeoutError as exc:
        raise LibSetupDepsError(
            name=name,
            url=url,
            path=path,
            stage=stage,
            reason=str(exc),
            suggestion="Increase --timeout=<seconds> and retry.",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LibSetupDepsError(
            name=name,
            url=url,
            path=path,
            stage=stage,
            reason=f"Operation timed out after {timeout_seconds} seconds.",
            suggestion="Increase --timeout=<seconds> and retry.",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        reason = stderr or str(exc)
        raise LibSetupDepsError(
            name=name,
            url=url,
            path=path,
            stage=stage,
            reason=reason,
            suggestion="Ensure git is installed and the repository/ref exists.",
        ) from exc


def _resource_signature(name: str, url: str, path: Path) -> dict[str, str]:
    return {"type": "resource", "name": name, "url": url, "path": str(path)}


def _git_signature(
    name: str, url: str, path: Path, ref_type: str | None, ref_value: str | None
) -> dict[str, str]:
    signature: dict[str, str] = {
        "type": "git",
        "name": name,
        "url": url,
        "path": str(path),
    }
    if ref_type and ref_value:
        signature["ref_type"] = ref_type
        signature["ref_value"] = ref_value
    return signature


def add_resource(name: str, url: str, path: str) -> None:
    """Download a dependency file and place it into a user-specified path.

    Parameters:
        name: Dependency identifier used for state tracking and error messages.
        url: Resource URL. Archives (`.zip`, `.tar.gz`, `.tgz`, `.tar.xz`) are extracted;
            other files are moved into the target directory directly.
        path: Target directory. Relative paths are resolved from the user script directory.
    """

    _handle_meta_flags_once()
    resource_name = _normalize_non_empty(name, "name")
    resource_url = _normalize_non_empty(url, "url")
    resource_path = _normalize_non_empty(path, "path")
    target_dir = _resolve_user_path(resource_path)
    should_reset = _has_cli_flag("--reset")
    should_append_to_gitignore = _has_cli_flag("--append-to-gitignore")
    quiet_mode = _is_quiet_mode()
    timeout_seconds = _timeout_seconds()

    state = _load_state()
    if should_reset:
        _remove_configured_path(target_dir)
        state["resources"].pop(resource_name, None)
    if should_append_to_gitignore:
        _append_path_to_gitignore(_CACHE_DIR_NAME)
        _append_path_to_gitignore(resource_path)

    target_dir.mkdir(parents=True, exist_ok=True)
    signature = _resource_signature(resource_name, resource_url, target_dir)
    existing = state["resources"].get(resource_name)
    if not should_reset and existing == signature and target_dir.exists():
        return

    download_file_name = _download_file_name(resource_url, f"{resource_name}.bin")
    suffix = _temp_file_suffix(download_file_name)
    cache_dir = _cache_dir()
    temp_file_path: Path | None = None

    try:
        _status_line(f"Downloading {resource_name} from {resource_url} ...")
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=cache_dir,
            suffix=suffix,
            prefix=f"{resource_name}_",
        ) as temp_file:
            temp_file_path = Path(temp_file.name)
        assert temp_file_path is not None
        _download_to_file(
            name=resource_name,
            url=resource_url,
            destination_file=temp_file_path,
            timeout_seconds=timeout_seconds,
            show_progress=not quiet_mode,
        )

        if _is_archive_filename(download_file_name):
            _extract_archive(temp_file_path, target_dir)
        else:
            destination_file = target_dir / download_file_name
            if destination_file.exists():
                destination_file.unlink()
            shutil.move(str(temp_file_path), str(destination_file))
        _status_line(f"Downloading {resource_name} from {resource_url} ... Done")
        state["resources"][resource_name] = signature
        _save_state(state)
    except TimeoutError as exc:
        raise LibSetupDepsError(
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="download",
            reason=str(exc),
            suggestion="Increase --timeout=<seconds> and retry.",
        ) from exc
    except URLError as exc:
        raise LibSetupDepsError(
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="download",
            reason=str(exc),
            suggestion="Check network connectivity and URL accessibility.",
        ) from exc
    except (zipfile.BadZipFile, tarfile.TarError, ValueError) as exc:
        raise LibSetupDepsError(
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="extract",
            reason=str(exc),
            suggestion="Verify the archive format and URL content.",
        ) from exc
    except OSError as exc:
        raise LibSetupDepsError(
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="filesystem",
            reason=str(exc),
            suggestion="Check path permissions and free disk space.",
        ) from exc
    finally:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()


def add_git_resource(
    name: str,
    url: str,
    path: str,
    *,
    branch: str | None = None,
    tag: str | None = None,
    hash: str | None = None,
) -> None:
    """Clone a git dependency and optionally check out a specific branch/tag/commit.

    Parameters:
        name: Dependency identifier used for state tracking and error messages.
        url: Git repository URL.
        path: Target directory. Relative paths are resolved from the user script directory.
        branch: Branch name to check out. Mutually exclusive with `tag` and `hash`.
        tag: Tag name to check out. Mutually exclusive with `branch` and `hash`.
        hash: Commit hash to check out. Mutually exclusive with `branch` and `tag`.
    """

    _handle_meta_flags_once()
    resource_name = _normalize_non_empty(name, "name")
    resource_url = _normalize_non_empty(url, "url")
    resource_path = _normalize_non_empty(path, "path")
    target_dir = _resolve_user_path(resource_path)
    should_reset = _has_cli_flag("--reset")
    should_append_to_gitignore = _has_cli_flag("--append-to-gitignore")
    quiet_mode = _is_quiet_mode()
    timeout_seconds = _timeout_seconds()

    ref_pairs: list[tuple[str, str]] = []
    if branch is not None and branch.strip():
        ref_pairs.append(("branch", branch.strip()))
    if tag is not None and tag.strip():
        ref_pairs.append(("tag", tag.strip()))
    if hash is not None and hash.strip():
        ref_pairs.append(("hash", hash.strip()))
    refs = ref_pairs
    if len(refs) > 1:
        raise ValueError("Only one of 'branch', 'tag', or 'hash' can be set.")
    ref_type, ref_value = refs[0] if refs else (None, None)

    state = _load_state()
    if should_reset:
        _remove_configured_path(target_dir)
        state["resources"].pop(resource_name, None)
    if should_append_to_gitignore:
        _append_path_to_gitignore(_CACHE_DIR_NAME)
        _append_path_to_gitignore(resource_path)

    signature = _git_signature(
        resource_name, resource_url, target_dir, ref_type, ref_value
    )
    existing = state["resources"].get(resource_name)
    if not should_reset and existing == signature and target_dir.exists():
        return

    if target_dir.exists() and any(target_dir.iterdir()) and existing != signature:
        raise LibSetupDepsError(
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="precheck",
            reason="Target path already exists and is not empty.",
            suggestion="Use a clean target directory or remove old content first.",
        )
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    _status_line(f"Cloning {resource_name} from {resource_url} ...")
    _run_git(
        ["git", "clone", "--progress", resource_url, str(target_dir)],
        name=resource_name,
        url=resource_url,
        path=str(target_dir),
        stage="clone",
        timeout_seconds=timeout_seconds,
        show_progress=not quiet_mode,
    )
    _status_line(f"Cloning {resource_name} from {resource_url} ... Done")

    if ref_type and ref_value:
        _run_git(
            ["git", "-C", str(target_dir), "checkout", ref_value],
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="checkout",
            timeout_seconds=timeout_seconds,
            show_progress=False,
        )

    state["resources"][resource_name] = signature
    _save_state(state)


if __name__ == "__main__":
    _handle_direct_invocation()
