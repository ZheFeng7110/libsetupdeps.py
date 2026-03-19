---
name: libsetupdeps-usage
description: Guide for using libsetupdeps.py correctly in downstream C/C++ projects. Use this when users ask how to integrate or operate libsetupdeps.py in their own repository.
license: MIT
---

# libsetupdeps.py usage skill

Use this skill when a user wants to set up source dependencies with `libsetupdeps.py` in their own project.

## Core behavior to enforce

1. `libsetupdeps.py` is a library file, not the user's entry script.
2. The user must create their own dependency script (commonly `setupdeps.py`, but any filename is valid).
3. The user script should `import libsetupdeps` and call:
   - `add_resource(name, url, path)`
   - `add_git_resource(name, url, path, *, branch=None, tag=None, hash=None)`
4. Dependency `path` values are resolved relative to the user script directory (not shell `cwd`).
5. This tool is source-only:
   - It downloads/clones source code.
   - Build/install/link are handled by users in their own toolchain.

## Supported command-line flags (passed to user script)

- `--append-to-gitignore`
  - Appends dependency target paths and `.libsetupdeps_cache` to `.gitignore`.
  - Creates `.gitignore` if missing.
  - Avoids duplicate entries.
- `--reset`
  - Deletes already configured dependency paths before re-fetching.
  - First run with no configured content should not fail.
- `--quiet`
  - Prints status only (no progress output).
- `--timeout=<seconds>`
  - Timeout for download/clone operations (default `120`).
- `--version`
  - Prints current version (`0.1.0`) and exits.
- `--help`
  - Prints help and exits.

## Runtime/output expectations

- Download status format: `Downloading <name> from <url> ... Done`
- Clone status format: `Cloning <name> from <url> ... Done`
- Non-quiet mode shows progress during download/clone.
- Timeout should terminate operations and raise actionable errors.

## Cache and state expectations

- Cache directory: `<script_dir>/.libsetupdeps_cache/`
- State file: `<script_dir>/.libsetupdeps_cache/.libsetupdeps_state.json`

## `add_resource` behavior details

- If downloaded file is an archive (`.zip`, `.tar.gz`, `.tgz`, `.tar.xz`), extract into target path.
- If downloaded file is not an archive, move/save the file into the target path directly.

## Direct invocation rule

If user runs `python libsetupdeps.py` (with or without args), guide them to create their own entry script and call APIs there.

## Response style for users

- Keep instructions practical and command-oriented.
- Prefer giving a ready-to-run user script snippet.
- Avoid suggesting binary package-manager workflows; stay aligned with source-only design.
