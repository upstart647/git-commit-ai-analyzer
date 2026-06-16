# -*- coding: utf-8 -*-
"""Layered prompt and analyzer config: default + global user + per-repo."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

from ai_analyze import DEFAULT_PROMPT_HEAD_TEMPLATE, DEFAULT_PROJECT_CONTEXT

REPO_CONFIG_NAME = "config.json"


def get_tool_home() -> str:
    for key in ("GIT_COMMIT_AI_ANALYZER_HOME", "GIT_COMMIT_ANALYZER_HOME"):
        env = os.environ.get(key)
        if env:
            return os.path.abspath(os.path.expanduser(env))
    script_home = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if os.path.isfile(os.path.join(script_home, "config.default.json")):
        return script_home
    return os.path.join(os.path.expanduser("~"), ".git-commit-ai-analyzer")


def _read_json(path: str) -> Dict[str, Any]:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_global_user_root() -> Dict[str, Any]:
    """Load ~/.git-commit-ai-analyzer/config.user.json (non-profile fields)."""
    return _read_json(os.path.join(get_tool_home(), "config.user.json"))


def repo_analyzer_config_path(repo_root: str) -> str:
    """Path to per-repo analyzer config."""
    return os.path.join(repo_root, ".git-commit-ai-analyzer", REPO_CONFIG_NAME)


def load_repo_analyzer_config(repo_root: str) -> Dict[str, Any]:
    """Load <repo>/.git-commit-ai-analyzer/config.json."""
    if not repo_root:
        return {}
    return _read_json(repo_analyzer_config_path(repo_root))


def merge_analyzer_settings(defaults: Dict[str, Any], repo_root: str) -> Dict[str, Any]:
    """Merge config.default.json with global user + repo analyzer keys."""
    merged = dict(defaults or {})
    global_cfg = load_global_user_root()
    repo_cfg = load_repo_analyzer_config(repo_root)

    analyzer_keys = (
        "prompt_extra",
        "prompt_override",
        "project_context_extra",
        "ai_context_enabled",
        "max_ai_context_entries",
        "ai_context_include_diff",
    )
    for key in analyzer_keys:
        if key in global_cfg and global_cfg[key] is not None:
            merged[key] = global_cfg[key]
        if key in repo_cfg and repo_cfg[key] is not None:
            merged[key] = repo_cfg[key]
    return merged


def build_prompt_head(project_context: str, repo_root: str = "") -> str:
    """Build layered prompt head: default template, optional override, extras."""
    merged_ctx = (project_context or "").strip() or DEFAULT_PROJECT_CONTEXT
    cfg = merge_analyzer_settings({}, repo_root)
    ctx_extra = (cfg.get("project_context_extra") or "").strip()
    if ctx_extra:
        merged_ctx = merged_ctx + "\n" + ctx_extra

    override = (cfg.get("prompt_override") or "").strip()
    if override:
        head = override.format(project_context=merged_ctx)
    else:
        head = DEFAULT_PROMPT_HEAD_TEMPLATE.format(project_context=merged_ctx)

    extra = (cfg.get("prompt_extra") or "").strip()
    if extra:
        head = head + "\n\n\u3010\u7528\u6237\u989d\u5916\u8981\u6c42\u3011\n" + extra + "\n"
    return head
