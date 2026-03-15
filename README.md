# libsetupdeps.py

[English](./README.md) | [简体中文](./README_zh.md)

`libsetupdeps.py` is a lightweight source-dependency setup tool for C/C++ projects.

It only downloads/clones dependency source code into target directories. Build, install, and link steps are intentionally left to users. This source-only model avoids many platform/architecture/ABI compatibility concerns that binary package managers usually need to handle.

The project ships one core file: `libsetupdeps.py`. Users create their own entry script (commonly `setupdeps.py`, but any filename works), import `libsetupdeps`, call APIs, and run `python <your-script>.py`.

Its workflow is similar to CMake `FetchContent`, while aiming to avoid repeated downloads during reconfiguration.

## Usage steps

1. Put `libsetupdeps.py` in your project root, then create your own entry script (for example `setupdeps.py`).
2. In that script, call `libsetupdeps.py` APIs to define dependencies.
3. Run `python setupdeps.py` (or your custom script name) to configure dependencies.

Optional command-line flags:

- `--append-to-gitignore`: append configured dependency target paths to `<script_dir>/.gitignore` (create if missing, no duplicate entries).
- `--reset`: delete configured dependency paths before re-downloading/re-cloning; if this is the first run and paths do not exist, nothing is deleted.
- `--version`: print current version and exit (currently `0.0.0`).
- `--help`: print help message and exit.

Example:

```python
# setupdeps.py (filename can be customized)

from libsetupdeps import add_resource, add_git_resource

# Download and extract archive to dependency/lua
add_resource("lua", "https://lua.ac.cn/ftp/lua-5.5.0.tar.gz", "dependency/lua")

# Clone repository and checkout tag
add_git_resource(
    "gtest",
    "https://github.com/google/googletest.git",
    "test/googletest",
    tag="v1.17.0",
)
```

## API

```python
add_resource(name: str, url: str, path: str) -> None
```

Download and extract an archive dependency into the target directory.

- `name`: dependency name (used in state and errors)
- `url`: archive URL (supports `.zip`, `.tar.gz`, `.tgz`, `.tar.xz`)
- `path`: target directory (relative paths are resolved from the user script directory)

```python
add_git_resource(
    name: str,
    url: str,
    path: str,
    *,
    branch: str | None = None,
    tag: str | None = None,
    hash: str | None = None
) -> None
```

Clone a git repository and optionally checkout one ref.

- `name`: dependency name
- `url`: git repository URL
- `path`: target directory (resolved relative to script dir)
- `branch` / `tag` / `hash`: at most one can be set

## Paths and state files

- Path base: user entry script directory (not shell `cwd`)
- Temporary download cache: `<script_dir>/.libsetupdeps_cache/`
- State file: `<script_dir>/.libsetupdeps_state.json`
- Idempotency: if the dependency signature (`name/url/path/ref`) is unchanged and target path exists, setup is skipped

## Error handling

- Invalid arguments raise `ValueError` (for example empty values, unsupported archive type, conflicting refs).
- Download/extract/filesystem/git failures raise `LibSetupDepsError` with:
  - dependency name
  - URL
  - target path
  - failure stage (`download`, `extract`, `clone`, `checkout`, ...)
  - suggestion text

## Tests

Project tests use `pytest`.

- Full suite: `python -m pytest -q`
- Single test: `python -m pytest -q tests/test_libsetupdeps.py::test_add_resource_updates_state_file`
