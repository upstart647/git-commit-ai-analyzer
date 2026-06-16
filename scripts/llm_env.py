# -*- coding: utf-8 -*-
"""Load LLM settings from ~/.git-commit-ai-analyzer/config.user.json"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

USER_CONFIG_NAME = "config.user.json"
DEFAULT_CHAT_PATH = "/v1/chat/completions"
DEFAULT_MAX_TOKENS = 32768
DEFAULT_TIMEOUT = 180.0

ENV_OVERRIDE_KEYS = {
    "api_key": "GIT_COMMIT_AI_ANALYZER_API_KEY",
    "base_url": "GIT_COMMIT_AI_ANALYZER_BASE_URL",
    "model": "GIT_COMMIT_AI_ANALYZER_MODEL",
    "chat_path": "GIT_COMMIT_AI_ANALYZER_CHAT_PATH",
    "max_tokens": "GIT_COMMIT_AI_ANALYZER_MAX_TOKENS",
    "timeout": "GIT_COMMIT_AI_ANALYZER_TIMEOUT",
}


def get_tool_home() -> str:
    for key in ("GIT_COMMIT_AI_ANALYZER_HOME", "GIT_COMMIT_ANALYZER_HOME"):
        env = os.environ.get(key)
        if env:
            return os.path.abspath(os.path.expanduser(env))
    script_home = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if os.path.isfile(os.path.join(script_home, USER_CONFIG_NAME)) or os.path.isfile(
        os.path.join(script_home, "config.default.json")
    ):
        return script_home
    return os.path.join(os.path.expanduser("~"), ".git-commit-ai-analyzer")


_LAST_CONFIG_LOAD_ERROR = ""


def get_last_config_load_error() -> str:
    """\u7528\u6cd5: \u8fd4\u56de\u4e0a\u6b21\u8bfb\u53d6 config.user.json \u5931\u8d25\u7684\u539f\u56e0"""
    return _LAST_CONFIG_LOAD_ERROR


def user_config_path() -> str:
    """\u7528\u6cd5: \u8fd4\u56de\u7528\u6237\u914d\u7f6e\u6587\u4ef6\u7edd\u5bf9\u8def\u5f84"""
    return os.path.join(get_tool_home(), USER_CONFIG_NAME)


def load_user_config_file() -> Dict[str, Any]:
    """\u7528\u6cd5: \u8bfb\u53d6 config.user.json\uff0c\u4e0d\u5b58\u5728\u6216\u89e3\u6790\u5931\u8d25\u8fd4\u56de\u7a7a dict"""
    global _LAST_CONFIG_LOAD_ERROR
    _LAST_CONFIG_LOAD_ERROR = ""
    path = user_config_path()
    if not os.path.isfile(path):
        _LAST_CONFIG_LOAD_ERROR = "file not found: " + path
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        _LAST_CONFIG_LOAD_ERROR = "root must be a JSON object"
    except json.JSONDecodeError as e:
        _LAST_CONFIG_LOAD_ERROR = "JSON parse error line {} col {}: {}".format(
            e.lineno, e.colno, e.msg
        )
    except OSError as e:
        _LAST_CONFIG_LOAD_ERROR = str(e)
    return {}


def _normalize_profile_cfg(raw: Dict[str, Any]) -> Dict[str, Any]:
    """\u7528\u6cd5: \u5c06\u5355\u4e2a profile \u6216\u65e7\u7248\u6241\u5e73\u914d\u7f6e\u89e3\u6790\u4e3a\u6807\u51c6\u5b57\u6bb5 dict"""
    if not isinstance(raw, dict):
        return {}
    return {
        "api_key": str(raw.get("api_key") or "").strip(),
        "base_url": str(raw.get("base_url") or "").strip().rstrip("/"),
        "model": str(raw.get("model") or "").strip(),
        "chat_path": str(raw.get("chat_path") or DEFAULT_CHAT_PATH).strip() or DEFAULT_CHAT_PATH,
        "max_tokens": raw.get("max_tokens", DEFAULT_MAX_TOKENS),
        "timeout": raw.get("timeout", DEFAULT_TIMEOUT),
    }


def _resolve_active_profile_cfg(root: Dict[str, Any]) -> Dict[str, Any]:
    """\u7528\u6cd5: \u6309 active + profiles \u9009\u62e9\u5f53\u524d\u5927\u6a21\u578b\u914d\u7f6e\uff1b\u65e0 profiles \u65f6\u517c\u5bb9\u65e7\u7248\u6241\u5e73\u683c\u5f0f"""
    profiles = root.get("profiles")
    if isinstance(profiles, dict) and profiles:
        active = str(root.get("active") or "").strip()
        if not active:
            active = next(iter(profiles.keys()))
        picked = profiles.get(active)
        if isinstance(picked, dict):
            cfg = _normalize_profile_cfg(picked)
            cfg["profile_name"] = active
            return cfg
        return {"profile_name": active}
    return _normalize_profile_cfg(root)


def _pick_str(cfg: Dict[str, Any], field: str, default: str = "") -> str:
    env_name = ENV_OVERRIDE_KEYS.get(field, "")
    if env_name:
        env_val = os.environ.get(env_name)
        if env_val is not None and str(env_val).strip():
            return str(env_val).strip()
    val = cfg.get(field)
    if val is None:
        return default
    return str(val).strip()


def _pick_number(cfg: Dict[str, Any], field: str, default: float, as_int: bool = False):
    env_name = ENV_OVERRIDE_KEYS.get(field, "")
    if env_name and os.environ.get(env_name):
        try:
            num = float(os.environ.get(env_name, ""))
            return int(num) if as_int else num
        except ValueError:
            pass
    val = cfg.get(field)
    if val is None or val == "":
        return default
    try:
        num = float(val)
        return int(num) if as_int else num
    except (TypeError, ValueError):
        return default


def resolve_llm_config() -> Dict[str, Any]:
    """\u7528\u6cd5: \u8fd4\u56de\u5f53\u524d\u6fc0\u6d3b\u7684 LLM \u914d\u7f6e\u53c2\u6570"""
    root = load_user_config_file()
    profile_cfg = _resolve_active_profile_cfg(root)
    chat_path = _pick_str(profile_cfg, "chat_path", DEFAULT_CHAT_PATH)
    if chat_path and not chat_path.startswith("/"):
        chat_path = "/" + chat_path
    return {
        "api_key": _pick_str(profile_cfg, "api_key"),
        "base_url": _pick_str(profile_cfg, "base_url").rstrip("/"),
        "model": _pick_str(profile_cfg, "model"),
        "chat_path": chat_path or DEFAULT_CHAT_PATH,
        "max_tokens": _pick_number(profile_cfg, "max_tokens", DEFAULT_MAX_TOKENS, as_int=True),
        "timeout": _pick_number(profile_cfg, "timeout", DEFAULT_TIMEOUT, as_int=False),
        "profile_name": profile_cfg.get("profile_name") or "",
        "config_path": user_config_path(),
    }


def initialize_llm_env() -> bool:
    """Return True if api_key is configured."""
    cfg = resolve_llm_config()
    return bool(cfg.get("api_key"))


def format_llm_log_label(cfg: Dict[str, Any] | None = None) -> str:
    """\u7528\u6cd5: \u751f\u6210\u65e5\u5fd7\u7528 AI \u63d0\u4f9b\u65b9\u63cf\u8ff0\uff08\u4e0d\u542b api_key\uff09"""
    if cfg is None:
        cfg = resolve_llm_config()
    profile = cfg.get("profile_name") or "default"
    model = cfg.get("model") or "?"
    base_url = cfg.get("base_url") or "?"
    return "profile={}, model={}, base_url={}".format(profile, model, base_url)


def config_status_message() -> str:
    """\u7528\u6cd5: \u8fd4\u56de\u914d\u7f6e\u72b6\u6001\u63d0\u793a\u6587\u672c\uff08\u7528\u4e8e\u65e5\u5fd7\uff09"""
    path = user_config_path()
    if not os.path.isfile(path):
        return (
            "\u672a\u627e\u5230 config.user.json\uff0c"
            "\u8bf7\u590d\u5236 config.user.json.example \u4e3a config.user.json "
            "\u5e76\u586b\u5199 active \u4e0e profiles\uff0c\u8def\u5f84: " + path
        )
    load_user_config_file()
    err = get_last_config_load_error()
    if err:
        return "config.user.json \u683c\u5f0f\u9519\u8bef: {} ({})".format(err, path)
    cfg = resolve_llm_config()
    missing = []
    if not cfg.get("api_key"):
        missing.append("api_key")
    if not cfg.get("base_url"):
        missing.append("base_url")
    if not cfg.get("model"):
        missing.append("model")
    if missing:
        prof = cfg.get("profile_name") or "default"
        return "config.user.json profile [{}] \u7f3a\u5c11\u5b57\u6bb5: {}".format(prof, ", ".join(missing))
    return ""
