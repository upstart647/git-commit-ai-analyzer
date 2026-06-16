---
name: project
description: Project change tracking maintained by git-commit-ai-analyzer
project_context: |
  待首次 commit 自动扫描生成项目背景。
---

# Project Change History

This file is maintained by git-commit-ai-analyzer pre-commit hook.

<!-- BEGIN_RECENT_CHANGES -->
### staged-16ba8d36

| Field | Value |
|-------|-------|
| Entry ID | staged-16ba8d36 |
| Staged Tree | 16ba8d36 (`git write-tree` 前8位，非 commit hash) |
| Commit | (提交后由 post-commit 写入) |
| Author | nijunwei |
| Date | 2026-06-16 17:40:29 +0800 |
| Added | 16 |
| Modified | 0 |
| Deleted | 0 |
| Files | 16 |
| Insertions | 3153 |
| Deletions | 0 |
| Modules | 16 |

| AI Model | minimax / MiniMax-M3 |

**中文工程分析（AI）**
- 分析模型：minimax / MiniMax-M3
- 主线1（全局 Hook 工具链初始化）：首次提交落地 `git-commit-ai-analyzer` 跨平台安装框架，`install.sh` 与 `install.ps1` 解析本地/远程源、写入 `core.hooksPath` 并按需从 `config.user.json.example` 拷贝用户配置，避免在未配置 LLM 密钥前阻断提交。
- 主线2（提交时自动 AI 分析）：`hooks/pre-commit` 在每次 `git commit` 前调用 `scripts/update_project.py` 生成 `PROJECT.md`/`AI_CONTEXT.md` 并自动 `git add`，`hooks/post-commit` 收尾写提交 SHA 与 `entry_id` 映射，支撑后续回填与裁剪。
- 主线3（LLM 调用与提示工程）：`scripts/ai_analyze.py` 内置中文工程分析 Prompt 模板与「推理草稿整理」回退路径，`scripts/llm_env.py` 读取 `active`/`profiles` 并通过 `GIT_COMMIT_AI_ANALYZER_API_KEY` 等环境变量覆盖密钥、地址、模型。
- 涉及文件：`install.sh`（安装入口）、`install.ps1`（Windows 安装）、`hooks/pre-commit`（分析+自动 add）、`hooks/post-commit`（映射收尾）、`scripts/ai_analyze.py`（Prompt 与 `call_llm` 重试）、`scripts/llm_env.py`（`load_config`）、`config.default.json`（默认阈值）、`config.user.json.example`（模型 profile）、`repo-config.json.example`（国标直流充电桩项目提示增强）
- 伴随调整：`.gitignore` 忽略 `config.user.json` 防止密钥泄露；`config.default.json` 新增 `diff_max_lines_per_file=120`、`ai_timeout_sec=200`、`max_ai_context_entries=30` 等阈值；`scripts/llm_env.py` 在 Windows 下过滤 `WindowsApps` 的 `py` 启动器。
- 影响评估：本批属工具链而非充电桩固件本身，但通过全局 `core.hooksPath` 影响本机所有 Git 仓库，LLM 超时或网络异常时若 `|| true` 失效可能拖慢提交；默认非阻断且 `.git-commit-ai-analyzer.disabled` 可逐仓库逃生。
- 回归建议：分别在 Windows 与 Linux 下跑通一键安装并执行示例提交，验证无 Python / 无 LLM 密钥时 `pre-commit` 不阻断且 `PROJECT.md`/`AI_CONTEXT.md` 正常落盘，同时确认 `git reset` 后 `--prune-only` 能清理孤立条目。

> 文件明细见下方 Modified/Added 列表。

**Modules**
  - .gitignore
  - LICENSE
  - README.md
  - config.default.json
  - config.user.json.example
  - hooks/post-commit
  - hooks/pre-commit
  - install.ps1
  - install.sh
  - repo-config.json.example
  - requirements.txt
  - scripts/ai_analyze.py
  - scripts/llm_env.py
  - scripts/project_profile.py
  - scripts/prompt_config.py
  - scripts/update_project.py

**Added** (16)
  - .gitignore  [.gitignore]
    - Add: __pycache__/ ; .local/
  - LICENSE  [LICENSE]
    - Add: MIT License ; Copyright (c) 2026 git-commit-ai-analyzer contributors
  - README.md  [README.md]
    - Add: 一个面向 Git 仓库的全局 Hook 工具。 ; 安装一次后，任意本地 Git 仓库在执行 `git commit` 时都会自动调用兼容 OpenAI 协议的 HTTP API，生成中文工程分析摘要，并写入仓库内的：
  - config.default.json  [config.default.json]
    - Add: "ignore_patterns": [ ; "^\\.git-commit-ai-analyzer/\\.local/",
  - config.user.json.example  [config.user.json.example]
    - Add: "active": "deepseek", ; "prompt_extra": "请按嵌入式固件习惯分析，每条主线必须引用具体文件路径或函数名。",
  - hooks/post-commit  [hooks/post-commit]
    - Add: REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0 ; [ -f "$REPO_ROOT/.git-commit-ai-analyzer.disabled" ] && exit 0
  - hooks/pre-commit  [hooks/pre-commit]
    - Add: REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0 ; [ -f "$REPO_ROOT/.git-commit-ai-analyzer.disabled" ] && exit 0
  - install.ps1  [install.ps1]
    - Add: $ErrorActionPreference = "Stop" ; $DefaultRepo = "https://github.com/upstart647/git-commit-ai-analyzer.git"
  - install.sh  [install.sh]
    - Add: set -e ; DEFAULT_REPO="https://github.com/upstart647/git-commit-ai-analyzer.git"
  - repo-config.json.example  [repo-config.json.example]
    - Add: "prompt_extra": "本项目为国标直流充电桩固件。分析时请说明影响的协议模块、保护链路与采样通道。", ; "project_context_extra": "技术栈：C/Keil，目录 SourceCode/Main、protocol_*。",
  - requirements.txt  [requirements.txt]
    - Add: httpx>=0.27.0
  - scripts/ai_analyze.py  [scripts/ai_analyze.py]
    - Add: """ ; ai_analyze.py - OpenAI-compatible LLM commit analysis for update_project.py
  - scripts/llm_env.py  [scripts/llm_env.py]
    - Add: """Load LLM settings from ~/.git-commit-ai-analyzer/config.user.json""" ; from __future__ import annotations
  - scripts/project_profile.py  [scripts/project_profile.py]
    - Add: """ ; project_profile.py - \u9996\u6b21\u8fd0\u884c\u626b\u63cf\u4ed3\u5e93\u751f\u6210 project_context\uff08\u5199\u5165 PROJECT.md frontmatter\uff09
  - scripts/prompt_config.py  [scripts/prompt_config.py]
    - Add: """Layered prompt and analyzer config: default + global user + per-repo.""" ; from __future__ import annotations
  - scripts/update_project.py  [scripts/update_project.py]
    - Add: """ ; update_project.py - Git commit \u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08\u901a\u7528\u5168\u5c40 hook \u4e3b\u5165\u53e3\uff09

---
<!-- END_RECENT_CHANGES -->
