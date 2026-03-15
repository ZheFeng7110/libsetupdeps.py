# AGENTS.md

## 项目名称
`libsetupdeps.py`

## 项目目标
用 Python 实现一个简易 C/C++ 包管理器，专注于“依赖源码获取与组织”，不负责编译和链接。

## 核心设计约束（必须遵守）
1. 本项目只提供 `libsetupdeps.py`，不提供、也不生成用户项目脚本。
2. 用户会在自己的工程根目录编写“依赖配置入口脚本”，常见命名为 `setupdeps.py`，但脚本名称可由用户自定义。
3. 用户脚本需要 `import libsetupdeps` 并调用相关函数，最终由用户自行执行（例如 `python <用户脚本名>.py`）。
   - 支持命令行参数：
     - `--append-to-gitignore`：将依赖目标路径追加到 `.gitignore` 末尾（无文件则创建，避免重复条目）。
     - `--reset`：删除已配置依赖后重新下载/克隆并配置；首次运行无已配置内容时不删除。
     - `--version`：输出版本号（当前为 `0.0.0`）并退出。
     - `--help`：输出帮助信息并退出。
   - 若用户直接运行 `libsetupdeps.py`（或直接给它传参运行），应提示其创建自己的入口脚本并在脚本中调用 API。
4. 包管理策略为“仅处理源码”：
   - 只下载依赖的源代码到用户指定路径；
   - 编译、安装、链接由用户自行处理；
   - 这种模式不需要像传统二进制包管理器那样处理系统、平台架构、ABI 兼容等问题，灵活度更高。
5. 尽量只依赖 python3 自带的库实现功能。
6. 工作方式可类比 CMake `FetchContent`，但应避免“每次重新配置都重复下载”的体验。

## 职责边界
- `libsetupdeps.py` 负责：
  - 依赖来源定义与解析（如仓库地址、版本、分支、tag、commit）。
  - 源码下载、缓存、目录布局、重复下载规避等。
  - 维护状态文件与缓存目录（如 `.libsetupdeps_state.json`、`.libsetupdeps_cache`）。
  - 根据命令行参数执行 `.gitignore` 追加、reset 重置、help/version 输出。
  - 处理直接运行库文件时的用户引导提示。
  - 提供清晰、稳定的 Python API，供用户入口脚本调用。
- 用户入口脚本（如 `setupdeps.py`，名称可变）负责：
  - 声明项目依赖与目标路径。
  - 调用 `libsetupdeps.py` 的 API 完成依赖配置。

## 测试策略约束
- 可以编写测试代码（推荐 `pytest`）来验证 `libsetupdeps.py` 行为。
- 测试应只覆盖本项目提供的能力，不应假设固定的用户脚本文件名。

## 交互与可维护性要求
- API 设计优先简洁直观，面向用户入口脚本作者。
- 错误信息要明确（依赖名、来源、失败原因、建议操作）。
- 路径处理需跨平台（Windows/Linux/macOS）。
- 默认行为可预测，避免隐式副作用。
- 用户使用示例：
  ```Python
  # setupdeps.py

  from libsetupdeps import add_resource, add_git_resource

  # 从 https://lua.ac.cn/ftp/lua-5.5.0.tar.gz 下载包，解压后放入 dependency/lua 路径中
  add_resource("lua", "https://lua.ac.cn/ftp/lua-5.5.0.tar.gz", "dependency/lua")

  # 从 git 仓库 https://github.com/google/googletest.git 克隆代码到 test/googletest 内，并签出到标签 v1.17.0 这一个提交
  add_git_resource("gtest", "https://github.com/google/googletest.git", "test/googletest", tag="v1.17.0")
  ```
  然后执行 `python setupdeps.py` 后，该脚本将会配置好 lua 与 gtest 库。
  如需启用附加行为，可执行：
  - `python setupdeps.py --append-to-gitignore`
  - `python setupdeps.py --reset`
  - `python setupdeps.py --version`
  - `python setupdeps.py --help`

## 文档与注释
- 文档提供中文与英文两个版本，分别写入 README.md 与 README_zh.md 中
- 注释只写英文的，对于用户调用的 API 需要编写 pydoc，详细标明函数的用途，包括每个参数的含义
- 面向用户的 README 文案应优先通俗易懂，先说明“它做什么、用户怎么用、为什么这样设计”。

## 当前阶段说明
当前仓库已进入实现与迭代阶段：核心 API（`add_resource`、`add_git_resource`）与测试已落地，后续围绕稳定性、错误信息与跨平台细节持续完善。
