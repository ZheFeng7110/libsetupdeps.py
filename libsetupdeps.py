"""
`libsetupdeps.py <https://github.com/ZheFeng7110/libsetupdeps.py.git>`_

A lightweight source-dependency setup helper for C/C++ projects.

Usage:
    1) Put this file in your project root.
    2) Create your own entry script (for example: setupdeps.py).
    3) In that script, import and call APIs such as add_resource/add_git_resource.
    4) Run: `python <your-script>.py [--append-to-gitignore] [--reset] [--help] [--version]`

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
import zipfile
from pathlib import Path
from typing import Any
from urllib import parse, request
from urllib.error import URLError

import __main__

_STATE_FILE_NAME = ".libsetupdeps_state.json"
_CACHE_DIR_NAME = ".libsetupdeps_cache"
__version__ = "0.0.0"
_META_FLAGS_HANDLED = False


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
    return _get_script_dir() / _STATE_FILE_NAME


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
    _state_file().write_text(
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
            f"  python {entry_script} [--append-to-gitignore] [--reset]",
            f"  python {entry_script} --version",
            f"  python {entry_script} --help",
            "",
            "Options:",
            "  --append-to-gitignore  Append dependency paths to .gitignore.",
            "  --reset                Delete configured paths before re-fetching.",
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


def _detect_archive_suffix(url: str) -> str:
    path = parse.urlparse(url).path.lower()
    if path.endswith(".tar.gz") or path.endswith(".tgz"):
        return ".tar.gz"
    if path.endswith(".tar.xz"):
        return ".tar.xz"
    if path.endswith(".zip"):
        return ".zip"
    raise ValueError(f"Unsupported archive format in URL: {url}")


def _extract_archive(archive_file: Path, target_dir: Path) -> None:
    suffix = archive_file.name.lower()
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(archive_file, "r") as archive:
            archive.extractall(target_dir)
        return
    if (
        suffix.endswith(".tar.gz")
        or suffix.endswith(".tgz")
        or suffix.endswith(".tar.xz")
    ):
        with tarfile.open(archive_file, "r:*") as archive:
            archive.extractall(target_dir, filter="data")
        return
    raise ValueError(f"Unsupported archive format: {archive_file.name}")


def _run_git(args: list[str], *, name: str, url: str, path: str, stage: str) -> None:
    try:
        subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
        )
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
    """Download and extract an archive dependency into a user-specified path.

    Parameters:
        name: Dependency identifier used for state tracking and error messages.
        url: Archive URL. Supported formats: `.zip`, `.tar.gz`, `.tgz`, `.tar.xz`.
        path: Target directory. Relative paths are resolved from the user script directory.
    """

    _handle_meta_flags_once()
    resource_name = _normalize_non_empty(name, "name")
    resource_url = _normalize_non_empty(url, "url")
    resource_path = _normalize_non_empty(path, "path")
    target_dir = _resolve_user_path(resource_path)
    should_reset = _has_cli_flag("--reset")
    should_append_to_gitignore = _has_cli_flag("--append-to-gitignore")

    state = _load_state()
    if should_reset:
        _remove_configured_path(target_dir)
        state["resources"].pop(resource_name, None)
    if should_append_to_gitignore:
        _append_path_to_gitignore(resource_path)

    target_dir.mkdir(parents=True, exist_ok=True)
    signature = _resource_signature(resource_name, resource_url, target_dir)
    existing = state["resources"].get(resource_name)
    if not should_reset and existing == signature and target_dir.exists():
        return

    suffix = _detect_archive_suffix(resource_url)
    cache_dir = _cache_dir()
    temp_file_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=cache_dir,
            suffix=suffix,
            prefix=f"{resource_name}_",
        ) as temp_file:
            temp_file_path = Path(temp_file.name)
            with request.urlopen(resource_url) as response:
                shutil.copyfileobj(response, temp_file)

        _extract_archive(temp_file_path, target_dir)
        state["resources"][resource_name] = signature
        _save_state(state)
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

    _run_git(
        ["git", "clone", resource_url, str(target_dir)],
        name=resource_name,
        url=resource_url,
        path=str(target_dir),
        stage="clone",
    )

    if ref_type and ref_value:
        _run_git(
            ["git", "-C", str(target_dir), "checkout", ref_value],
            name=resource_name,
            url=resource_url,
            path=str(target_dir),
            stage="checkout",
        )

    state["resources"][resource_name] = signature
    _save_state(state)


if __name__ == "__main__":
    _handle_direct_invocation()
