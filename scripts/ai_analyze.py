# -*- coding: utf-8 -*-
"""
ai_analyze.py - OpenAI-compatible LLM commit analysis for update_project.py
Config: ~/.git-commit-ai-analyzer/config.user.json (api_key, base_url, model, ...)
"""

from __future__ import annotations

import json
import os
import re
import sys

# DeepSeek V4 Pro max output 384K; default 32K leaves room for reasoning + final answer
# without blocking pre-commit for minutes (384K would be overkill for commit summary)
DEFAULT_MAX_TOKENS = 32768
DEFAULT_TIMEOUT = 180.0
MAX_RETRY_TOKENS = 65536

DEFAULT_PROJECT_CONTEXT = (
    "\u672a\u63d0\u4f9b\u9879\u76ee\u80cc\u666f\uff1b\u8bf7\u6839\u636e\u6587\u4ef6\u8def\u5f84\u4e0e diff \u63a8\u65ad\u6280\u672f\u6808\u4e0e\u4e1a\u52a1\u9886\u57df\u3002"
)

DEFAULT_PROMPT_HEAD_TEMPLATE = (
    "\u4f60\u662f\u4e00\u4f4d\u5145\u7535\u6869\u56fa\u4ef6\u9879\u76ee\u7684\u8d44\u6df1\u5de5\u7a0b\u5e08\uff0c"
    "\u6b63\u5728\u5ba1\u9605\u4e00\u6b21 Git \u6682\u5b58\u533a\u6539\u52a8\u3002\n"
    "\u8bf7\u7528\u4e2d\u6587\u5199\u4e00\u6bb5\u300c\u5de5\u7a0b\u5206\u6790\u6458\u8981\u300d\uff0c\u7ed9\u56e2\u961f\u5de5\u7a0b\u5e08\u9605\u8bfb\uff0c\u8981\u6c42\uff1a\n\n"
    "- \u91cd\u70b9\u56de\u7b54\u300c\u4e3a\u4ec0\u4e48\u6539\u300d\u548c\u300c\u4e1a\u52a1\u5f71\u54cd\u300d\uff0c\u907f\u514d\u5355\u7eaf\u63cf\u8ff0\u4ee3\u7801\n"
    "- \u8bc6\u522b\u6838\u5fc3\u4e3b\u7ebf\uff08\u6700\u591a 3 \u6761\uff09\uff1a\u6bcf\u6761 1~2 \u53e5\u8bdd\uff0c\u5fc5\u987b\u70b9\u540d\u5173\u8054\u7684\u6587\u4ef6\u8def\u5f84\u6216\u51fd\u6570/\u5b8f\uff08\u7528\u53cd\u5f15\u53f7\uff09\uff0c\u7981\u6b62\u91cd\u590d\u5b8c\u6574\u6587\u4ef6\u6e05\u5355\n"
    "- \u6307\u51fa\u300c\u4f34\u968f\u8c03\u6574\u300d\uff08\u9608\u503c/\u5e38\u91cf/\u6784\u5efa\u811a\u672c/\u547d\u540d\u4fee\u6b63\u7b49\u5bb9\u6613\u88ab\u5ffd\u7565\u7684\u5c0f\u6539\u52a8\uff09\n"
    "- \u7ed9\u51fa\u5f71\u54cd\u8bc4\u4f30\u4e0e\u56de\u5f52\u5efa\u8bae\uff08\u91cd\u70b9\u9a8c\u8bc1\u54ea\u4e9b\u6a21\u5757\u6216\u6d41\u7a0b\uff09\n"
    "- \u4e0d\u8981\u5199\u300c\u4ee3\u7801\u5df2\u4fee\u6539\u300d\u8fd9\u79cd\u5e9f\u8bdd\n"
    "- \u4e0d\u8981\u4f7f\u7528 emoji\n"
    "- \u5168\u6587\u4ec5\u7528\u4e2d\u6587\uff0c\u7981\u6b62\u8f93\u51fa\u82f1\u6587\u6216\u601d\u8003\u8fc7\u7a0b\n"
    "- \u6bcf\u6761\u4e3b\u7ebf\u3001\u4f34\u968f\u8c03\u6574\u3001\u5f71\u54cd\u8bc4\u4f30\u3001\u56de\u5f52\u5efa\u8bae\u5404\u4e0d\u8d85\u8fc7 2 \u53e5\u8bdd\uff0c\u5168\u6587\u5efa\u8bae 300~600 \u5b57\n"
    "- \u76f4\u63a5\u8f93\u51fa\u6700\u7ec8 Markdown\uff0c\u4e0d\u8981\u8f93\u51fa\u601d\u8003\u8fc7\u7a0b\uff0c\u4e0d\u8981\u8f93\u51fa <thinking> / redacted_thinking \u7b49\u6807\u7b7e\n"
    "- \u4e25\u683c\u4f7f\u7528\u4ee5\u4e0b Markdown \u6a21\u677f\u8f93\u51fa\uff08\u4e0d\u8981\u5305\u88f9\u5728 ``` \u4ee3\u7801\u5757\u91cc\uff09\uff1a\n\n"
    "**\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08AI\uff09**\n"
    "- \u4e3b\u7ebf1\uff08<\u7b80\u77ed\u4e3b\u9898>\uff09\uff1a<\u5185\u5bb9\uff0c\u542b\u53cd\u5f15\u53f7\u6587\u4ef6\u6216\u7b26\u53f7>\n"
    "- \u4e3b\u7ebf2\uff08<\u7b80\u77ed\u4e3b\u9898>\uff09\uff1a<\u5185\u5bb9\uff0c\u542b\u53cd\u5f15\u53f7\u6587\u4ef6\u6216\u7b26\u53f7>\n"
    "- \u4e3b\u7ebf3\uff08<\u7b80\u77ed\u4e3b\u9898>\uff09\uff1a<\u5185\u5bb9\uff0c\u542b\u53cd\u5f15\u53f7\u6587\u4ef6\u6216\u7b26\u53f7>\n"
    "- \u6d89\u53ca\u6587\u4ef6\uff1a`\u8def\u5f84/a.c`\uff08\u51fd\u6570 foo\uff09\u3001`\u8def\u5f84/b.h`\uff08\u5b8f BAR\uff09\n"
    "- \u4f34\u968f\u8c03\u6574\uff1a<\u5185\u5bb9>\n"
    "- \u5f71\u54cd\u8bc4\u4f30\uff1a<\u5185\u5bb9>\n"
    "- \u56de\u5f52\u5efa\u8bae\uff1a<\u5185\u5bb9>\n\n"
    "\u4ed3\u5e93\u80cc\u666f\uff1a{project_context}\n\n---\n"
)

FORMAT_FROM_REASONING = (
    "\u4e0b\u9762\u662f\u4e00\u6bb5\u6a21\u578b\u63a8\u7406\u8349\u7a3f\uff0c\u8bf7\u6574\u7406\u6210\u6700\u7ec8 Markdown\u3002\n"
    "\u53ea\u8f93\u51fa\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff0c\u4ee5\u300c**\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08AI\uff09**\u300d\u5f00\u5934\uff1a\n\n"
)

SYS_PROMPT = (
    "\u4f60\u662f\u8d44\u6df1\u5d4c\u5165\u5f0f\u56fa\u4ef6\u5de5\u7a0b\u5e08\u3002"
    "\u76f4\u63a5\u8f93\u51fa\u6700\u7ec8 Markdown\uff0c\u4ec5\u4e2d\u6587\uff0c\u7b80\u6d01\u6e05\u6670\uff0c"
    "\u4e0d\u8981\u8f93\u51fa\u601d\u8003\u8fc7\u7a0b\u6216\u82f1\u6587\u3002"
)

SYS_FORMAT = "\u4f60\u662f\u6587\u6863\u6574\u7406\u52a9\u624b\uff0c\u53ea\u8f93\u51fa\u6700\u7ec8 Markdown\u3002"


def build_prompt_head(project_context, repo_root=""):
    if repo_root:
        try:
            from prompt_config import build_prompt_head as _layered

            return _layered(project_context, repo_root)
        except Exception:
            pass
    ctx = (project_context or "").strip() or DEFAULT_PROJECT_CONTEXT
    return DEFAULT_PROMPT_HEAD_TEMPLATE.format(project_context=ctx)


def _format_file_summaries(summaries):
    if not summaries:
        return []
    lines = ["\u3010\u6587\u4ef6\u6458\u8981\uff08\u811a\u672c\u9884\u8ba1\u7b97\uff09\u3011"]
    for item in summaries:
        if isinstance(item, str):
            lines.append("  - {}".format(item))
            continue
        if not isinstance(item, dict):
            continue
        path = item.get("path") or "?"
        mod = item.get("module") or ""
        parts = [path]
        if mod:
            parts.append("[{}]".format(mod))
        touch = item.get("functions") or []
        if touch:
            parts.append("Touch: {}".format(" | ".join(touch)))
        changes = item.get("assign_changes") or []
        if changes:
            parts.append("Change: {}".format(" ; ".join(changes)))
        lines.append("  - {}".format(" | ".join(parts)))
    lines.append("")
    return lines


def build_prompt(payload):
    meta = payload.get("meta") or {}
    added = payload.get("files_added") or []
    modified = payload.get("files_modified") or []
    deleted = payload.get("files_deleted") or []
    diff_text = payload.get("diff_text") or ""
    project_context = payload.get("project_context") or meta.get("project_context") or ""
    repo_root = payload.get("repo_root") or ""
    file_summaries = payload.get("file_summaries") or []

    out = [build_prompt_head(project_context, repo_root), "\u3010\u5143\u4fe1\u606f\u3011"]
    for k, v in meta.items():
        if k == "project_context":
            continue
        out.append("- {}: {}".format(k, v))
    out.append("")

    out.extend(_format_file_summaries(file_summaries))

    def _block(title, items):
        if not items:
            return
        out.append("\u3010{}\u3011({})".format(title, len(items)))
        for it in items:
            out.append("  - {}".format(it))
        out.append("")

    _block("\u65b0\u589e\u6587\u4ef6", added)
    _block("\u4fee\u6539\u6587\u4ef6", modified)
    _block("\u5220\u9664\u6587\u4ef6", deleted)

    out.append("\u3010\u5173\u952e\u4ee3\u7801\u5dee\u5f02\uff08\u5df2\u622a\u65ad\uff09\u3011")
    out.append("```diff")
    out.append(diff_text if diff_text else "(\u7a7a diff)")
    out.append("```")
    out.append("")
    out.append("\u8bf7\u4e25\u683c\u6309\u6a21\u677f\u8f93\u51fa\uff0c\u4e0d\u8981\u9644\u52a0\u591a\u4f59\u524d\u540e\u7f00\uff1a")
    return "\n".join(out)


def _get_env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _get_env_float(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _request_chat(messages, max_tokens, temperature=0.2):
    try:
        import httpx
    except ImportError as e:
        raise RuntimeError("missing httpx, run: pip install httpx") from e

    from llm_env import resolve_llm_config

    cfg = resolve_llm_config()
    api_key = cfg["api_key"]
    if not api_key:
        raise RuntimeError("config.user.json: api_key not set")

    base_url = cfg["base_url"]
    model = cfg["model"]
    if not base_url or not model:
        raise RuntimeError(
            "config.user.json: base_url and model required "
            "(copy config.user.json.example and fill in ~/.git-commit-ai-analyzer/)"
        )
    timeout = float(cfg.get("timeout") or DEFAULT_TIMEOUT)

    url = base_url + cfg["chat_path"]
    headers = {
        "Authorization": "Bearer " + api_key,
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, headers=headers, json=body)

    if resp.status_code != 200:
        raise RuntimeError("LLM HTTP {} body={}".format(resp.status_code, resp.text[:400]))

    data = resp.json()
    try:
        choice = data["choices"][0]
        msg = choice["message"]
        content = (msg.get("content") or "").strip()
        reasoning = (msg.get("reasoning_content") or "").strip()
        finish_reason = choice.get("finish_reason")
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("bad LLM response: {} raw={}".format(e, str(data)[:400]))

    return content, reasoning, finish_reason


def _strip_thinking_blocks(text):
    """\u7528\u6cd5: \u79fb\u9664\u6a21\u578b\u601d\u8003/\u63a8\u7406\u5757\uff0c\u907f\u514d\u5199\u5165 PROJECT.md"""
    if not text:
        return ""
    patterns = (
        r"<think>[\s\S]*?</think>",
        r"<thinking>[\s\S]*?</thinking>",
        r"<reasoning>[\s\S]*?</reasoning>",
    )
    out = text
    for pat in patterns:
        out = re.sub(pat, "", out, flags=re.IGNORECASE)
    return out.strip()


def _extract_analysis(text):
    text = _strip_thinking_blocks(text)
    if not text:
        return ""
    m = re.search(r"\*\*\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08AI\uff09\*\*[\s\S]*", text)
    if m:
        block = m.group(0).strip()
        lines = [block.splitlines()[0]]
        for line in block.splitlines()[1:]:
            s = line.strip()
            if not s:
                continue
            if s.startswith("**") and not s.startswith("**\u4e2d\u6587\u5de5\u7a0b\u5206\u6790"):
                break
            if s.startswith("**Modules**") or s.startswith("**Added**") or s.startswith("**Modified**"):
                break
            lines.append(line)
        return "\n".join(lines).strip()
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- \u4e3b\u7ebf") or s.startswith("- \u4f34\u968f\u8c03\u6574"):
            lines.append(line)
        elif s.startswith("- \u6d89\u53ca\u6587\u4ef6"):
            lines.append(line)
        elif s.startswith("- \u5f71\u54cd\u8bc4\u4f30") or s.startswith("- \u56de\u5f52\u5efa\u8bae"):
            lines.append(line)
        elif s.startswith("**\u4e2d\u6587\u5de5\u7a0b\u5206\u6790"):
            lines.append(line)
    return "\n".join(lines).strip() if lines else ""


def _format_from_reasoning(reasoning):
    if not reasoning:
        return ""
    tail = reasoning[-6000:] if len(reasoning) > 6000 else reasoning
    extracted = _extract_analysis(tail)
    if extracted:
        return extracted
    content, _, _ = _request_chat(
        [
            {"role": "system", "content": SYS_FORMAT},
            {"role": "user", "content": FORMAT_FROM_REASONING + tail},
        ],
        max_tokens=min(8192, int(__import__("llm_env", fromlist=["resolve_llm_config"]).resolve_llm_config().get("max_tokens") or DEFAULT_MAX_TOKENS)),
        temperature=0.1,
    )
    return content or _extract_analysis(_strip_thinking_blocks(tail))


def _finalize_llm_output(text):
    """\u7528\u6cd5: \u7edf\u4e00\u6e05\u7406 LLM \u8f93\u51fa\uff0c\u53ea\u4fdd\u7559\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\u6a21\u677f\u5757"""
    cleaned = _strip_thinking_blocks(text or "")
    extracted = _extract_analysis(cleaned)
    if extracted:
        return extracted
    return cleaned.strip()


def call_llm(prompt):
    cfg = __import__("llm_env", fromlist=["resolve_llm_config"]).resolve_llm_config()
    max_tokens = int(cfg.get("max_tokens") or DEFAULT_MAX_TOKENS)
    messages = [
        {"role": "system", "content": SYS_PROMPT},
        {"role": "user", "content": prompt},
    ]

    content, reasoning, finish_reason = _request_chat(messages, max_tokens)
    if content:
        final = _finalize_llm_output(content)
        if final:
            return final

    retry_tokens = min(max_tokens * 2, MAX_RETRY_TOKENS)
    content, reasoning2, finish_reason = _request_chat(messages, retry_tokens)
    if content:
        final = _finalize_llm_output(content)
        if final:
            return final

    merged = reasoning2 or reasoning
    if merged:
        formatted = _format_from_reasoning(merged)
        if formatted:
            return _finalize_llm_output(formatted)

    raise RuntimeError(
        "LLM content empty (finish_reason={}) reasoning_len={}".format(
            finish_reason, len(merged or "")
        )
    )


def _write_stderr(msg):
    sys.stderr.buffer.write(msg.encode("utf-8", errors="replace"))
    sys.stderr.buffer.write(b"\n")


def main():
    if len(sys.argv) < 2:
        _write_stderr("usage: ai_analyze.py <input_json_path>")
        return 2

    in_path = sys.argv[1]
    try:
        with open(in_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        _write_stderr("\u8bfb\u53d6\u8f93\u5165\u6587\u4ef6\u5931\u8d25: {}".format(e))
        return 2

    try:
        text = call_llm(build_prompt(payload))
    except Exception as e:
        _write_stderr("AI \u5206\u6790\u5931\u8d25: {}".format(e))
        return 1

    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
