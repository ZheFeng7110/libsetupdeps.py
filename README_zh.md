# libsetupdeps.py

[English](./README.md) | 简体中文

`libsetupdeps.py` 是一个面向 C/C++ 工程的轻量依赖源码配置工具。

它只负责把依赖源码下载/克隆到指定目录，编译、安装、链接由用户自行处理。这个模式不需要像传统二进制包管理器那样处理系统、平台架构、ABI 兼容等问题，灵活度更高。

本项目提供的核心文件是 `libsetupdeps.py`。用户在自己的工程里编写入口脚本（常见名 `setupdeps.py`，也可自定义名称），在脚本中 `import libsetupdeps` 并调用 API，最后执行 `python <用户脚本名>.py` 即可完成依赖配置。

这个库的工作方式与 CMake 的 `FetchContent` 类似，但不会因为重新配置而导致潜在的重复下载。

## 使用步骤

1. 将文件 `libsetupdeps.py` 下载到您的工程根目录，然后创建文件 `setupdeps.py`（文件名可自定义）。
2. 编写 `setupdeps.py`：调用 `libsetupdeps.py` 的 API 描述您的工程所需要的依赖。
3. 运行命令 `python setupdeps.py`，完成依赖的配置。

可选命令行参数：

- `--append-to-gitignore`：将本次配置中的依赖目标路径追加到 `<script_dir>/.gitignore`（若文件不存在会自动创建，已存在条目不会重复追加）。
- `--reset`：重新配置前先删除已配置依赖目录，然后重新下载/克隆并写回状态。第一次运行时若目录不存在则不会执行删除。
- `--version`：输出当前版本号并退出（当前为 `0.0.0`）。
- `--help`：输出帮助信息并退出。

示例：

```python
# setupdeps.py（文件名可自定义）

from libsetupdeps import add_resource, add_git_resource

# 下载压缩包并解压到 dependency/lua
add_resource("lua", "https://lua.ac.cn/ftp/lua-5.5.0.tar.gz", "dependency/lua")

# 克隆 git 仓库并签出到 tag
add_git_resource(
    "gtest",
    "https://github.com/google/googletest.git",
    "test/googletest",
    tag="v1.17.0",
)
```

## API

```Python
add_resource(name: str, url: str, path: str) -> None
```

下载并解压压缩包资源到目标目录。

- name：依赖名称（用于状态记录与错误信息）
- url：资源 URL（支持 .zip、.tar.gz、.tgz、.tar.xz）
- path：目标目录（相对路径时，以用户入口脚本所在目录为基准）

```Python
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

克隆 git 仓库并可选签出到指定分支/标签/提交。

- name：依赖名称
- url：git 仓库地址
- path：目标目录（相对脚本目录）
- branch/tag/hash：三者最多只能设置一个

## 路径与状态文件

- 路径解析基准：用户入口脚本所在目录（不是当前 shell 的 cwd）。
- 下载临时文件目录：<script_dir>/.libsetupdeps_cache/
- 状态文件：<script_dir>/.libsetupdeps_state.json
- 当同一依赖签名（name/url/path/ref）未变化且目标目录存在时，会执行幂等跳过。

## 错误处理

- 参数错误会抛 ValueError（例如空参数、不支持的压缩格式、ref 冲突）。
- 下载/解压/文件系统/git 失败会抛 LibSetupDepsError，消息中包含：
    - 依赖名
    - URL
    - 目标路径
    - 失败阶段（如 download / extract / clone / checkout）
    - 建议操作

## 测试

项目使用 pytest。

- 全量测试：`python -m pytest -q`
- 单个测试：`python -m pytest -q tests/test_libsetupdeps.py::test_add_resource_updates_state_file`
