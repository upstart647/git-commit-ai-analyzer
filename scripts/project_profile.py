# -*- coding: utf-8 -*-
"""
project_profile.py - \u9996\u6b21\u8fd0\u884c\u626b\u63cf\u4ed3\u5e93\u751f\u6210 project_context\uff08\u5199\u5165 PROJECT.md frontmatter\uff09
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SOURCE_EXTS = {".c", ".h", ".cpp", ".hpp", ".py", ".rs", ".go", ".java", ".ts", ".tsx", ".js", ".vue", ".cs"}
README_NAMES = ("README.md", "README.rst", "README.txt", "readme.md", "Readme.md")


def _run_git(repo_root, *args):
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


def scan_repo(repo_root):
    root = Path(repo_root)
    top_dirs = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        if name.startswith(".") or name in ("node_modules", "Output", "firmware", "build", "dist"):
            continue
        top_dirs.append(name)

    readme_snippet = ""
    for rn in README_NAMES:
        rp = root / rn
        if rp.is_file():
            try:
                text = rp.read_text(encoding="utf-8", errors="replace")
                readme_snippet = text[:2000].strip()
            except Exception:
                pass
            break

    src_dirs = []
    file_counts = {}
    max_walk = 800
    walked = 0
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel == ".":
            rel = ""
        parts = rel.replace("\\", "/").split("/") if rel else []
        if parts and parts[0].startswith("."):
            dirnames[:] = []
            continue
        for fn in filenames:
            walked += 1
            if walked > max_walk:
                break
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SOURCE_EXTS:
                continue
            rel_file = (rel + "/" + fn if rel else fn).replace("\\", "/")
            top = rel_file.split("/")[0] if "/" in rel_file else rel_file
            file_counts[top] = file_counts.get(top, 0) + 1
            if len(src_dirs) < 12:
                seg = "/".join(rel_file.split("/")[:2]) if "/" in rel_file else rel_file
                if seg not in src_dirs:
                    src_dirs.append(seg)
        if walked > max_walk:
            break

    sorted_counts = sorted(file_counts.items(), key=lambda x: -x[1])[:8]
    remote = _run_git(repo_root, "remote", "get-url", "origin")

    return {
        "top_dirs": top_dirs[:15],
        "readme_snippet": readme_snippet,
        "source_hotspots": sorted_counts,
        "sample_paths": src_dirs[:10],
        "remote": remote,
    }


def generate_context_with_llm(scan_data):
    try:
        import httpx
    except ImportError:
        return None

    from llm_env import initialize_llm_env, resolve_llm_config

    if not initialize_llm_env():
        return None

    cfg = resolve_llm_config()
    api_key = cfg["api_key"]
    base_url = cfg["base_url"]
    model = cfg["model"]
    if not api_key or not base_url or not model:
        return None
    timeout = float(cfg.get("timeout") or 60)

    user_msg = (
        "\u8bf7\u6839\u636e\u4ee5\u4e0b\u4ed3\u5e93\u626b\u63cf\u7ed3\u679c\uff0c\u7528 3~5 \u53e5\u4e2d\u6587\u5199\u9879\u76ee\u80cc\u666f"
        "\uff08\u6280\u672f\u6808\u3001\u4e1a\u52a1\u9886\u57df\u3001\u4e3b\u8981\u76ee\u5f55\u7ed3\u6784\uff09\uff0c\u4f9b\u540e\u7eed commit \u5206\u6790\u4f7f\u7528\u3002"
        "\u4e0d\u8981\u4f7f\u7528 emoji\uff0c\u4e0d\u8981\u6807\u9898\uff0c\u76f4\u63a5\u8f93\u51fa\u6bb5\u843d\u3002\n\n"
        + json.dumps(scan_data, ensure_ascii=False, indent=2)
    )

    url = base_url + cfg["chat_path"]
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "\u4f60\u662f\u5d4c\u5165\u5f0f\u4e0e\u5de5\u4e1a\u8f6f\u4ef6\u9879\u76ee\u5206\u6790\u52a9\u624b\u3002",
            },
            {"role": "user", "content": user_msg},
        ],
        "max_tokens": 1024,
        "temperature": 0.2,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=body)
        if resp.status_code != 200:
            return None
        data = resp.json()
        content = (data["choices"][0]["message"].get("content") or "").strip()
        return content if content else None
    except Exception:
        return None


def build_fallback_context(scan_data):
    parts = []
    tops = scan_data.get("top_dirs") or []
    if tops:
        parts.append("\u9876\u5c42\u76ee\u5f55\uff1a" + "\u3001".join(tops[:8]))
    hotspots = scan_data.get("source_hotspots") or []
    if hotspots:
        hs = ["{}({})".format(k, v) for k, v in hotspots[:5]]
        parts.append("\u4e3b\u8981\u6e90\u7801\u96c6\u4e2d\u4e8e\uff1a" + "\u3001".join(hs))
    remote = scan_data.get("remote")
    if remote:
        parts.append("\u8fdc\u7a0b\u4ed3\u5e93\uff1a" + remote)
    if not parts:
        return "\u672a\u8bc6\u522b\u9879\u76ee\u7ed3\u6784\uff1b\u8bf7\u6839\u636e\u6587\u4ef6\u8def\u5f84\u4e0e diff \u63a8\u65ad\u4e1a\u52a1\u80cc\u666f\u3002"
    return "\u3002".join(parts) + "\u3002"


def ensure_project_context(repo_root, project_md_path, log_fn=None):
    """\u8bfb\u53d6\u6216\u751f\u6210 project_context\uff1b\u82e5\u9700\u8981\u5219\u5199\u56de PROJECT.md frontmatter\u3002"""
    from update_project import (
        ensure_project_md_skeleton,
        parse_frontmatter,
        read_text_utf8,
        write_text_utf8,
        dump_frontmatter,
    )

    ensure_project_md_skeleton(project_md_path)
    content = read_text_utf8(project_md_path)
    fm, body = parse_frontmatter(content)
    existing = (fm.get("project_context") or "").strip()
    if existing and len(existing) > 20:
        return existing

    if log_fn:
        log_fn("\u9996\u6b21\u751f\u6210 project_context\uff0c\u626b\u63cf\u4ed3\u5e93...")

    scan_data = scan_repo(repo_root)
    ctx = generate_context_with_llm(scan_data)
    if not ctx:
        ctx = build_fallback_context(scan_data)
        if log_fn:
            log_fn("project_context \u4f7f\u7528\u626b\u63cf\u56de\u9000\u6a21\u677f\uff08\u65e0 LLM \u6216\u8c03\u7528\u5931\u8d25\uff09")

    fm["project_context"] = ctx
    new_content = dump_frontmatter(fm) + body
    write_text_utf8(project_md_path, new_content)
    if log_fn:
        log_fn("project_context \u5df2\u5199\u5165 PROJECT.md")
    return ctx
