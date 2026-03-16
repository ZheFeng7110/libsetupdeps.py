import io
import json
import runpy
import tarfile
import zipfile
from pathlib import Path

import pytest

import libsetupdeps


def _set_main_script(monkeypatch: pytest.MonkeyPatch, script_path: Path) -> None:
    monkeypatch.setattr(
        libsetupdeps.__main__, "__file__", str(script_path), raising=False
    )


def _set_cli_args(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(libsetupdeps.sys, "argv", ["setupdeps.py", *args])
    monkeypatch.setattr(libsetupdeps, "_META_FLAGS_HANDLED", False)


def test_script_dir_resolution_from_main_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "setupdeps.py"
    script.write_text("# placeholder", encoding="utf-8")
    _set_main_script(monkeypatch, script)

    assert libsetupdeps._get_script_dir() == tmp_path.resolve()


def test_resolve_path_relative_to_script_dir_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script_dir = tmp_path / "project_root"
    other_cwd = tmp_path / "other"
    script_dir.mkdir()
    other_cwd.mkdir()
    _set_main_script(monkeypatch, script_dir / "deps_config.py")
    monkeypatch.chdir(other_cwd)

    resolved = libsetupdeps._resolve_user_path("dependency/lua")
    assert resolved == (script_dir / "dependency" / "lua").resolve()


def test_cache_dir_under_script_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    cache_dir = libsetupdeps._cache_dir()

    assert cache_dir == (tmp_path / ".libsetupdeps_cache")
    assert cache_dir.exists()


def test_add_resource_rejects_empty_name_url_path() -> None:
    with pytest.raises(ValueError):
        libsetupdeps.add_resource(" ", "https://example.org/file.zip", "deps/a")
    with pytest.raises(ValueError):
        libsetupdeps.add_resource("a", " ", "deps/a")
    with pytest.raises(ValueError):
        libsetupdeps.add_resource("a", "https://example.org/file.zip", " ")


def test_version_flag_prints_version_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_cli_args(monkeypatch, "--version")
    with pytest.raises(SystemExit) as exc:
        libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.0.0"


def test_help_flag_prints_help_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _set_cli_args(monkeypatch, "--help")
    with pytest.raises(SystemExit) as exc:
        libsetupdeps.add_git_resource(
            "gtest", "https://example.org/gtest.git", "test/gtest"
        )
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "libsetupdeps.py usage:" in output
    assert "--append-to-gitignore" in output
    assert "--reset" in output
    assert "--quiet" in output
    assert "--timeout=<seconds>" in output


def test_timeout_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cli_args(monkeypatch)
    assert libsetupdeps._timeout_seconds() == 120

    _set_cli_args(monkeypatch, "--timeout=45")
    assert libsetupdeps._timeout_seconds() == 45


def test_timeout_invalid_value_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_cli_args(monkeypatch, "--timeout=abc")
    with pytest.raises(ValueError):
        libsetupdeps._timeout_seconds()

    _set_cli_args(monkeypatch, "--timeout=0")
    with pytest.raises(ValueError):
        libsetupdeps._timeout_seconds()


def test_add_resource_download_to_cache_then_extract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "setupdeps.py"
    script.write_text("# placeholder", encoding="utf-8")
    _set_main_script(monkeypatch, script)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("include/header.h", "int v = 1;\n")
    payload = buffer.getvalue()

    class _FakeResponse(io.BytesIO):
        def __enter__(self):  # noqa: D401
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: D401
            return None

    monkeypatch.setattr(
        libsetupdeps.request,
        "urlopen",
        lambda _url, timeout=None: _FakeResponse(payload),
    )

    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")

    extracted = tmp_path / "dependency" / "lua" / "include" / "header.h"
    assert extracted.exists()
    assert extracted.read_text(encoding="utf-8") == "int v = 1;\n"
    cache_dir = tmp_path / ".libsetupdeps_cache"
    assert cache_dir.exists()
    assert list(cache_dir.iterdir()) == []


def test_quiet_mode_hides_download_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--quiet")
    seen_show_progress: list[bool] = []

    def _fake_download_to_file(**kwargs):
        seen_show_progress.append(kwargs["show_progress"])
        kwargs["destination_file"].write_bytes(b"dummy")

    monkeypatch.setattr(libsetupdeps, "_download_to_file", _fake_download_to_file)
    monkeypatch.setattr(libsetupdeps, "_extract_archive", lambda *args, **kwargs: None)

    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")
    assert seen_show_progress == [False]


def test_download_status_line_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch)
    monkeypatch.setattr(
        libsetupdeps,
        "_download_to_file",
        lambda **kwargs: kwargs["destination_file"].write_bytes(b"dummy"),
    )
    monkeypatch.setattr(libsetupdeps, "_extract_archive", lambda *args, **kwargs: None)

    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")
    output = capsys.readouterr().out
    assert "Downloading lua from https://example.org/lua.zip ..." in output
    assert "Downloading lua from https://example.org/lua.zip ... Done" in output


def test_timeout_flag_passed_to_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--timeout=5")
    seen_timeout: list[int] = []

    def _fake_download_to_file(**kwargs):
        seen_timeout.append(kwargs["timeout_seconds"])
        kwargs["destination_file"].write_bytes(b"dummy")

    monkeypatch.setattr(libsetupdeps, "_download_to_file", _fake_download_to_file)
    monkeypatch.setattr(libsetupdeps, "_extract_archive", lambda *args, **kwargs: None)
    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")

    assert seen_timeout == [5]


def test_append_to_gitignore_creates_file_and_appends_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--append-to-gitignore")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("pkg/a.txt", "ok")
    payload = buffer.getvalue()

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        libsetupdeps.request, "urlopen", lambda _url, timeout=None: _FakeResponse(payload)
    )
    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")

    gitignore = tmp_path / ".gitignore"
    assert gitignore.exists()
    assert gitignore.read_text(encoding="utf-8").splitlines()[-1] == "dependency/lua"


def test_append_to_gitignore_does_not_duplicate_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--append-to-gitignore")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("pkg/a.txt", "ok")
    payload = buffer.getvalue()

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        libsetupdeps.request, "urlopen", lambda _url, timeout=None: _FakeResponse(payload)
    )

    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")
    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")

    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count("dependency/lua") == 1


def test_add_resource_unsupported_archive_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")

    with pytest.raises(ValueError):
        libsetupdeps.add_resource(
            "lua", "https://example.org/lua.rar", "dependency/lua"
        )


def test_add_resource_updates_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")

    payload_stream = io.BytesIO()
    with tarfile.open(fileobj=payload_stream, mode="w:gz") as tf:
        content = b"hello"
        info = tarfile.TarInfo(name="pkg/readme.txt")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    payload = payload_stream.getvalue()

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(
        libsetupdeps.request, "urlopen", lambda _url, timeout=None: _FakeResponse(payload)
    )
    libsetupdeps.add_resource("lua", "https://example.org/lua.tar.gz", "dependency/lua")

    state = json.loads(
        (tmp_path / ".libsetupdeps_state.json").read_text(encoding="utf-8")
    )
    assert state["resources"]["lua"]["type"] == "resource"
    assert state["resources"]["lua"]["url"] == "https://example.org/lua.tar.gz"


def test_add_git_resource_rejects_multiple_refs() -> None:
    with pytest.raises(ValueError):
        libsetupdeps.add_git_resource(
            "gtest",
            "https://example.org/gtest.git",
            "test/gtest",
            branch="main",
            tag="v1.0.0",
        )


def test_add_git_resource_accepts_branch_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        libsetupdeps,
        "_run_git",
        lambda args, **kwargs: calls.append(args),
    )

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        branch="main",
    )
    assert calls[0][0:2] == ["git", "clone"]
    assert calls[1][-2:] == ["checkout", "main"]


def test_add_git_resource_accepts_tag_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        libsetupdeps, "_run_git", lambda args, **kwargs: calls.append(args)
    )

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        tag="v1.17.0",
    )
    assert calls[1][-2:] == ["checkout", "v1.17.0"]


def test_add_git_resource_accepts_hash_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        libsetupdeps, "_run_git", lambda args, **kwargs: calls.append(args)
    )

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        hash="5f8c5f8",
    )
    assert calls[1][-2:] == ["checkout", "5f8c5f8"]


def test_add_git_resource_clone_and_checkout_called(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        libsetupdeps, "_run_git", lambda args, **kwargs: calls.append(args)
    )

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        tag="v1.17.0",
    )
    assert len(calls) == 2
    assert calls[0][0:2] == ["git", "clone"]
    assert calls[1][0:4] == [
        "git",
        "-C",
        str((tmp_path / "test" / "gtest").resolve()),
        "checkout",
    ]


def test_quiet_mode_hides_clone_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--quiet")
    calls: list[dict[str, object]] = []

    def _fake_run_git(args, **kwargs):
        calls.append({"args": args, "show_progress": kwargs["show_progress"], "stage": kwargs["stage"]})

    monkeypatch.setattr(libsetupdeps, "_run_git", _fake_run_git)

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        tag="v1.17.0",
    )
    assert calls[0]["stage"] == "clone"
    assert calls[0]["show_progress"] is False


def test_timeout_flag_passed_to_git_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--timeout=7")
    seen: list[tuple[str, int]] = []

    def _fake_run_git(args, **kwargs):
        seen.append((kwargs["stage"], kwargs["timeout_seconds"]))

    monkeypatch.setattr(libsetupdeps, "_run_git", _fake_run_git)
    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        tag="v1.17.0",
    )

    assert seen == [("clone", 7), ("checkout", 7)]


def test_add_git_resource_updates_state_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    monkeypatch.setattr(libsetupdeps, "_run_git", lambda args, **kwargs: None)

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        tag="v1.17.0",
    )
    state = json.loads(
        (tmp_path / ".libsetupdeps_state.json").read_text(encoding="utf-8")
    )
    assert state["resources"]["gtest"]["type"] == "git"
    assert state["resources"]["gtest"]["ref_type"] == "tag"
    assert state["resources"]["gtest"]["ref_value"] == "v1.17.0"


def test_reset_redownloads_resource_when_target_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--reset")

    target = (tmp_path / "dependency" / "lua").resolve()
    target.mkdir(parents=True)
    stale = target / "stale.txt"
    stale.write_text("old", encoding="utf-8")
    state = {
        "resources": {
            "lua": {
                "type": "resource",
                "name": "lua",
                "url": "https://example.org/lua.zip",
                "path": str(target),
            }
        }
    }
    (tmp_path / ".libsetupdeps_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("pkg/new.txt", "fresh")
    payload = buffer.getvalue()
    calls = {"download": 0}

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    def _fake_urlopen(_url: str, timeout: int | None = None):
        calls["download"] += 1
        return _FakeResponse(payload)

    monkeypatch.setattr(libsetupdeps.request, "urlopen", _fake_urlopen)
    libsetupdeps.add_resource("lua", "https://example.org/lua.zip", "dependency/lua")

    assert calls["download"] == 1
    assert not stale.exists()
    assert (target / "pkg" / "new.txt").exists()


def test_reset_reclones_git_when_target_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    _set_cli_args(monkeypatch, "--reset")

    target = (tmp_path / "test" / "gtest").resolve()
    target.mkdir(parents=True)
    (target / "old.txt").write_text("old", encoding="utf-8")
    state = {
        "resources": {
            "gtest": {
                "type": "git",
                "name": "gtest",
                "url": "https://example.org/gtest.git",
                "path": str(target),
                "ref_type": "branch",
                "ref_value": "main",
            }
        }
    }
    (tmp_path / ".libsetupdeps_state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(libsetupdeps, "_run_git", lambda args, **kwargs: calls.append(args))
    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        branch="main",
    )

    assert len(calls) == 2
    assert calls[0][0:2] == ["git", "clone"]


def test_error_message_contains_name_url_path_and_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    monkeypatch.setattr(
        libsetupdeps,
        "_run_git",
        lambda args, **kwargs: (_ for _ in ()).throw(
            libsetupdeps.LibSetupDepsError(
                name="gtest",
                url="https://example.org/gtest.git",
                path=str((tmp_path / "test" / "gtest").resolve()),
                stage="clone",
                reason="simulated failure",
            )
        ),
    )

    with pytest.raises(libsetupdeps.LibSetupDepsError) as exc:
        libsetupdeps.add_git_resource(
            "gtest", "https://example.org/gtest.git", "test/gtest"
        )

    message = str(exc.value)
    assert "gtest" in message
    assert "https://example.org/gtest.git" in message
    assert "clone" in message
    assert str((tmp_path / "test" / "gtest").resolve()) in message


def test_idempotent_behavior_on_same_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_main_script(monkeypatch, tmp_path / "setupdeps.py")
    run_calls: list[list[str]] = []
    monkeypatch.setattr(
        libsetupdeps, "_run_git", lambda args, **kwargs: run_calls.append(args)
    )

    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        branch="main",
    )
    (tmp_path / "test" / "gtest").mkdir(parents=True, exist_ok=True)
    libsetupdeps.add_git_resource(
        "gtest",
        "https://example.org/gtest.git",
        "test/gtest",
        branch="main",
    )

    assert len(run_calls) == 2


def test_direct_invocation_prints_prompt_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module_path = Path(libsetupdeps.__file__).resolve()
    monkeypatch.setattr(libsetupdeps.sys, "argv", [str(module_path), "--help"])

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(module_path), run_name="__main__")

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "0.0.0" not in output
    assert "create your own dependency setup script" in output
    assert "--help" in output
