# -*- coding: utf-8 -*-
"""
update_project.py - Git commit \u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08\u901a\u7528\u5168\u5c40 hook \u4e3b\u5165\u53e3\uff09
\u7528\u6cd5:
  \u9ed8\u8ba4(pre-commit): \u6e05\u7406\u5df2\u64a4\u56de\u6761\u76ee + \u751f\u6210\u65b0\u5206\u6790
  --prune-only      : reset \u540e\u624b\u52a8\u6e05\u7406\u5df2\u4e0d\u53ef\u8fbe\u6761\u76ee
  --finish-commit-map: post-commit \u8bb0\u5f55 commit \u4e0e entry_id \u6620\u5c04
  --repo <path>     : \u6307\u5b9a\u4ed3\u5e93\u6839\u76ee\u5f55
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

MARKER_START = "<!-- BEGIN_RECENT_CHANGES -->"
MARKER_END = "<!-- END_RECENT_CHANGES -->"
AI_CTX_MARKER_START = "<!-- BEGIN_AI_RECENT -->"
AI_CTX_MARKER_END = "<!-- END_AI_RECENT -->"
AI_CONTEXT_BACKGROUND_MAX = 500
SAMPLE_LINE_MAX_LEN = 200
SAMPLE_LINE_RAW_MAX_LEN = 512
IDE_LAYOUT_FILE_RE = re.compile(r"\.uvguix\.", re.IGNORECASE)


def get_tool_home():
    for key in ("GIT_COMMIT_AI_ANALYZER_HOME", "GIT_COMMIT_ANALYZER_HOME"):
        env = os.environ.get(key)
        if env:
            return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), ".git-commit-ai-analyzer")


def load_config(repo_root=""):
    cfg_path = os.path.join(get_tool_home(), "config.default.json")
    defaults = {
        "ignore_patterns": [],
        "diff_max_lines_per_file": 120,
        "diff_max_total_bytes": 24000,
        "max_recent_entries": 50,
        "max_commit_map_entries": 100,
        "ai_timeout_sec": 200,
        "ai_context_enabled": True,
        "max_ai_context_entries": 30,
        "ai_context_include_diff": False,
    }
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            defaults.update(loaded)
        except Exception:
            pass
    if repo_root:
        try:
            from prompt_config import merge_analyzer_settings

            defaults = merge_analyzer_settings(defaults, repo_root)
        except Exception:
            pass
    return defaults


def read_text_utf8(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text_utf8(path, content):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def append_log(log_file, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "{} {}\n".format(timestamp, message)
    try:
        parent = os.path.dirname(log_file)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(log_file, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
    except Exception:
        pass


def initialize_llm_env(log_fn=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from llm_env import initialize_llm_env as _init_llm, config_status_message

    ok = _init_llm()
    if log_fn:
        msg = config_status_message()
        if msg:
            log_fn(msg)
    return ok


def git_subprocess_env():
    env = os.environ.copy()
    env.setdefault("LC_ALL", "C.UTF-8")
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def decode_git_output(raw):
    """Git on Windows often emits diff hunks in GBK; decode bytes safely to Unicode."""
    if not raw:
        return ""
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def run_git_capture(repo_root, *args, timeout=120):
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo_root,
            capture_output=True,
            timeout=timeout,
            env=git_subprocess_env(),
        )
        if r.returncode == 0:
            return decode_git_output(r.stdout or b"")
        return ""
    except Exception:
        return ""


def run_git(repo_root, *args):
    return run_git_capture(repo_root, *args, timeout=120).strip()


def parse_frontmatter(content):
    fm = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end >= 0:
            block = content[3:end].strip()
            body = content[end + 4 :]
            if body.startswith("\n"):
                body = body[1:]
            for line in block.splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if v.startswith("|"):
                    continue
                fm[k] = v.strip().strip('"').strip("'")
            ctx_m = re.search(
                r"^project_context:\s*\|\s*\n((?:[ \t].*\n?)*)",
                block,
                re.MULTILINE,
            )
            if ctx_m:
                lines = []
                for ln in ctx_m.group(1).splitlines():
                    if ln.startswith("  "):
                        lines.append(ln[2:])
                    elif ln.startswith("\t"):
                        lines.append(ln[1:])
                    else:
                        lines.append(ln)
                fm["project_context"] = "\n".join(lines).strip()
    return fm, body


def dump_frontmatter(fm):
    lines = ["---"]
    for k, v in fm.items():
        if k == "project_context":
            lines.append("project_context: |")
            for pline in (v or "").splitlines():
                lines.append("  " + pline)
        else:
            lines.append("{}: {}".format(k, v))
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def ensure_project_md_skeleton(project_md):
    if os.path.isfile(project_md):
        return
    parent = os.path.dirname(project_md)
    os.makedirs(parent, exist_ok=True)
    skeleton = (
        "---\n"
        "name: project\n"
        "description: Project change tracking maintained by git-commit-ai-analyzer\n"
        "project_context: |\n"
        "  \u5f85\u9996\u6b21 commit \u81ea\u52a8\u626b\u63cf\u751f\u6210\u9879\u76ee\u80cc\u666f\u3002\n"
        "---\n\n"
        "# Project Change History\n\n"
        "This file is maintained by git-commit-ai-analyzer pre-commit hook.\n\n"
        "{start}\n\n{end}\n"
    ).format(start=MARKER_START, end=MARKER_END)
    write_text_utf8(project_md, skeleton)


def is_gb_dc_project(repo_root):
    """\u7528\u6cd5: \u5224\u65ad\u4ed3\u5e93\u76ee\u5f55\u540d\u662f\u5426\u4ee5 GB_DC \u5f00\u5934\uff1b\u4ec5\u6b64\u7c7b\u5de5\u7a0b\u81ea\u52a8\u8ffd\u52a0 .git-commit-ai-analyzer/ \u5230 .gitignore"""
    name = os.path.basename(os.path.abspath(repo_root))
    return name.startswith("GB_DC")


def _gitignore_covers_analyzer_dir(txt):
    """\u7528\u6cd5: \u5224\u65ad .gitignore \u662f\u5426\u5df2\u5ffd\u7565\u6574\u4e2a .git-commit-ai-analyzer \u76ee\u5f55\uff08\u4ec5 .local/ \u5b50\u76ee\u5f55\u89c4\u5219\u4e0d\u7b97\uff09"""
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s in (".git-commit-ai-analyzer/", ".git-commit-ai-analyzer"):
            return True
    return False


def _gitignore_has_exact_rule(txt, rule):
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s == rule:
            return True
    return False


def ensure_gitignore_analyzer_local(repo_root, log_fn):
    """\u7528\u6cd5: \u786e\u4fdd .local \u72b6\u6001\u76ee\u5f55\u88ab .gitignore \u5ffd\u7565\uff0c\u907f\u514d commit \u540e\u518d\u6b21\u53d8\u810f"""
    gi = os.path.join(repo_root, ".gitignore")
    needle = ".git-commit-ai-analyzer/.local/"
    txt = ""
    if os.path.isfile(gi):
        try:
            txt = read_text_utf8(gi)
            if _gitignore_has_exact_rule(txt, needle) or _gitignore_covers_analyzer_dir(txt):
                return
        except Exception:
            pass
    try:
        with open(gi, "a", encoding="utf-8", newline="\n") as f:
            if txt and not txt.endswith("\n"):
                f.write("\n")
            f.write("\n# git-commit-ai-analyzer local state\n")
            f.write(needle + "\n")
        if log_fn:
            log_fn("\u5df2\u8ffd\u52a0 .gitignore: " + needle)
    except Exception:
        pass


def ensure_gitignore_local(repo_root, log_fn):
    if not is_gb_dc_project(repo_root):
        return
    gi = os.path.join(repo_root, ".gitignore")
    needle = ".git-commit-ai-analyzer/"
    if os.path.isfile(gi):
        try:
            txt = read_text_utf8(gi)
            if _gitignore_covers_analyzer_dir(txt):
                return
        except Exception:
            pass
    try:
        with open(gi, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n# git-commit-ai-analyzer (do not commit)\n")
            f.write(needle + "\n")
        if log_fn:
            log_fn("\u5df2\u8ffd\u52a0 .gitignore: " + needle)
    except Exception:
        pass


def get_recent_section(content):
    start_idx = content.find(MARKER_START)
    end_idx = content.find(MARKER_END)
    if start_idx < 0 or end_idx <= start_idx:
        return None
    section_start = start_idx + len(MARKER_START)
    old_section = content[section_start:end_idx]
    old_entries = []
    matches = list(re.finditer(r"(?m)^### .+$", old_section))
    for i, match in enumerate(matches):
        entry_start = match.start()
        if i + 1 < len(matches):
            entry_end = matches[i + 1].start()
        else:
            entry_end = len(old_section)
        old_entries.append(old_section[entry_start:entry_end].strip())
    return {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "old_entries": old_entries,
    }


def set_recent_section(content, entries, max_entries=50):
    info = get_recent_section(content)
    if not info:
        return content
    combined = "\n\n".join(entries[:max_entries])
    new_section = MARKER_START + "\n" + combined + "\n" + MARKER_END
    end_after = info["end_idx"] + len(MARKER_END)
    return content[: info["start_idx"]] + new_section + content[end_after:]


def get_ai_context_section(content):
    start_idx = content.find(AI_CTX_MARKER_START)
    end_idx = content.find(AI_CTX_MARKER_END)
    if start_idx < 0 or end_idx <= start_idx:
        return None
    section_start = start_idx + len(AI_CTX_MARKER_START)
    old_section = content[section_start:end_idx]
    old_entries = []
    matches = list(re.finditer(r"(?m)^### .+$", old_section))
    for i, match in enumerate(matches):
        entry_start = match.start()
        if i + 1 < len(matches):
            entry_end = matches[i + 1].start()
        else:
            entry_end = len(old_section)
        old_entries.append(old_section[entry_start:entry_end].strip())
    return {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "old_entries": old_entries,
    }


def set_ai_context_section(content, entries, max_entries=30):
    info = get_ai_context_section(content)
    if not info:
        return content
    combined = "\n\n".join(entries[:max_entries])
    new_section = AI_CTX_MARKER_START + "\n" + combined + "\n" + AI_CTX_MARKER_END
    end_after = info["end_idx"] + len(AI_CTX_MARKER_END)
    return content[: info["start_idx"]] + new_section + content[end_after:]


def ensure_ai_context_skeleton(ai_context_md, project_context=""):
    if os.path.isfile(ai_context_md):
        return
    parent = os.path.dirname(ai_context_md)
    os.makedirs(parent, exist_ok=True)
    bg = (project_context or "").strip()
    if len(bg) > AI_CONTEXT_BACKGROUND_MAX:
        bg = bg[: AI_CONTEXT_BACKGROUND_MAX] + "..."
    if not bg or "\u5f85\u9996\u6b21" in bg:
        bg = "\u5f85\u9996\u6b21 commit \u540e\u81ea\u52a8\u751f\u6210\u9879\u76ee\u80cc\u666f\u3002"
    skeleton = (
        "# AI Project Context\n\n"
        "<!-- AUTO-GENERATED by git-commit-ai-analyzer -->\n\n"
        "## Background\n\n"
        "{bg}\n\n"
        "## Recent Changes\n\n"
        "{start}\n\n{end}\n"
    ).format(bg=bg, start=AI_CTX_MARKER_START, end=AI_CTX_MARKER_END)
    write_text_utf8(ai_context_md, skeleton)


def build_file_summaries(repo_root, files, commit_sha=None):
    """\u7528\u6cd5: \u4e3a AI prompt \u6784\u5efa\u6587\u4ef6\u6458\u8981\u5217\u8868"""
    summaries = []
    for fp in files:
        details = get_file_change_detail(repo_root, fp, commit_sha=commit_sha)
        summaries.append(
            {
                "path": fp,
                "module": get_module_name(fp),
                "functions": details.get("functions") or [],
                "assign_changes": details.get("assign_changes") or [],
            }
        )
    return summaries


def parse_ai_analysis_sections(ai_text):
    """\u7528\u6cd5: \u4ece AI \u5206\u6790\u6587\u672c\u63d0\u53d6 Why/Impact/Verify"""
    why_parts = []
    impact = ""
    verify = ""
    if not ai_text:
        return why_parts, impact, verify
    for line in ai_text.splitlines():
        s = line.strip()
        if re.match(r"^- \u4e3b\u7ebf\d", s):
            why_parts.append(re.sub(r"^- \u4e3b\u7ebf\d+\uff08[^)]+\uff09\uff1a\s*", "", s))
        elif s.startswith("- \u5f71\u54cd\u8bc4\u4f30\uff1a"):
            impact = s.split("\uff1a", 1)[-1].strip()
        elif s.startswith("- \u56de\u5f52\u5efa\u8bae\uff1a"):
            verify = s.split("\uff1a", 1)[-1].strip()
    return why_parts, impact, verify


def build_ai_context_entry(context_meta):
    """\u7528\u6cd5: \u751f\u6210 AI_CONTEXT.md \u5355\u6761\u6781\u7b80\u8bb0\u5f55"""
    entry_id = context_meta.get("entry_id") or "unknown"
    commit_sha = context_meta.get("commit_sha") or ""
    author = context_meta.get("author") or "unknown"
    date_str = context_meta.get("date") or ""
    files = context_meta.get("files") or []
    ai_text = context_meta.get("ai_text") or ""

    if commit_sha:
        title_key = commit_sha[:8]
        title = "### {} \u00b7 {} \u00b7 {}".format(title_key, date_str[:10], author)
    else:
        title_key = entry_id
        title = "### {} \u00b7 {} \u00b7 {}".format(entry_id, date_str[:10], author)

    file_refs = ", ".join("`{}`".format(f) for f in files[:8])
    if len(files) > 8:
        file_refs += ", ..."

    why_parts, impact, verify = parse_ai_analysis_sections(ai_text)
    why = " ; ".join(why_parts[:2]) if why_parts else "\u89c1 PROJECT.md \u8be6\u60c5"
    if not impact:
        impact = "\u89c1 PROJECT.md"
    if not verify:
        verify = "\u89c1 PROJECT.md"

    lines = [title]
    if file_refs:
        lines.append("- **Files**: {}".format(file_refs))
    lines.append("- **Why**: {}".format(why))
    lines.append("- **Impact**: {}".format(impact))
    lines.append("- **Verify**: {}".format(verify))
    lines.append("")
    lines.append("---")
    return "\n".join(lines), title_key


def update_ai_context_md(ai_context_md, context_meta, project_context, cfg, log_fn):
    """\u7528\u6cd5: \u66f4\u65b0 AI_CONTEXT.md \u6781\u7b80\u6761\u76ee"""
    if not cfg.get("ai_context_enabled", True):
        return False

    ensure_ai_context_skeleton(ai_context_md, project_context)
    entry_body, title_key = build_ai_context_entry(context_meta)
    entry_id = context_meta.get("entry_id") or ""

    content = read_text_utf8(ai_context_md)
    bg = (project_context or "").strip()
    if len(bg) > AI_CONTEXT_BACKGROUND_MAX:
        bg = bg[: AI_CONTEXT_BACKGROUND_MAX] + "..."
    if bg and "\u5f85\u9996\u6b21" not in bg:
        if "## Background" in content:
            content = re.sub(
                r"## Background\n\n[\s\S]*?\n## Recent Changes",
                "## Background\n\n" + bg + "\n\n## Recent Changes",
                content,
                count=1,
            )

    info = get_ai_context_section(content)
    if not info:
        log_fn("AI_CONTEXT.md markers not found")
        return False

    prefixes = []
    if entry_id:
        prefixes.append("### {}".format(entry_id))
    if context_meta.get("commit_sha"):
        prefixes.append("### {}".format(context_meta["commit_sha"][:8]))
    prefixes.append("### {}".format(title_key))

    filtered = [
        e
        for e in info["old_entries"]
        if not any(e.startswith(p) for p in prefixes if p)
    ]
    max_n = cfg.get("max_ai_context_entries", 30)
    content = set_ai_context_section(content, [entry_body] + filtered, max_n)
    write_text_utf8(ai_context_md, content)
    log_fn("AI_CONTEXT.md updated entry={}".format(entry_id or title_key))
    return True


def remove_ai_context_entries_by_prefix(ai_context_md, remove_prefixes, log_fn):
    if not os.path.isfile(ai_context_md) or not remove_prefixes:
        return False
    content = read_text_utf8(ai_context_md)
    info = get_ai_context_section(content)
    if not info:
        return False
    filtered = [
        e
        for e in info["old_entries"]
        if not any(e.startswith(p) for p in remove_prefixes if p)
    ]
    if len(filtered) == len(info["old_entries"]):
        return False
    cfg = load_config(os.path.dirname(os.path.dirname(ai_context_md)))
    max_n = cfg.get("max_ai_context_entries", 30)
    content = set_ai_context_section(content, filtered, max_n)
    write_text_utf8(ai_context_md, content)
    if log_fn:
        log_fn("AI_CONTEXT.md \u5df2\u79fb\u9664\u6761\u76ee: " + ", ".join(sorted(remove_prefixes)))
    return True


def patch_ai_context_after_commit(ai_context_md, entry_id, commit_sha, log_fn):
    """\u7528\u6cd5: post-commit \u540e\u628a commit \u77ed hash \u5199\u56de AI_CONTEXT \u6807\u9898"""
    if not os.path.isfile(ai_context_md) or not entry_id or not commit_sha:
        return
    content = read_text_utf8(ai_context_md)
    old_title = "### {}".format(entry_id)
    idx = content.find(old_title)
    if idx < 0:
        return
    line_end = content.find("\n", idx)
    if line_end < 0:
        return
    old_line = content[idx:line_end]
    if commit_sha[:8] in old_line and entry_id not in old_line:
        return
    parts = [p.strip() for p in old_line.lstrip("#").strip().split("\u00b7")]
    date_part = parts[1] if len(parts) > 1 else ""
    author_part = parts[2] if len(parts) > 2 else "unknown"
    new_title = "### {} \u00b7 {} \u00b7 {}".format(commit_sha[:8], date_part, author_part)
    content = content[:idx] + new_title + content[line_end:]
    write_text_utf8(ai_context_md, content)
    if log_fn:
        log_fn("AI_CONTEXT.md \u5df2\u5199\u5165 commit={}".format(commit_sha[:8]))


def normalize_path(p):
    return (p or "").replace("\\", "/").strip()


def test_ignored_file(file_path, ignore_patterns):
    normalized = normalize_path(file_path)
    for pattern in ignore_patterns:
        try:
            if re.search(pattern, normalized):
                return True
        except re.error:
            if normalized == pattern:
                return True
    return False


def get_module_name(file_path):
    normalized = normalize_path(file_path)
    if not normalized:
        return "UNKNOWN"
    parts = normalized.split("/")
    if len(parts) >= 2 and parts[0] == "SourceCode":
        return "SourceCode/{}".format(parts[1])
    if len(parts) >= 2:
        return "{}/{}".format(parts[0], parts[1])
    return parts[0]


def test_useful_code_line(line):
    t = line.strip()
    if not t:
        return False
    if "\ufffd" in t:
        return False
    if len(t) > SAMPLE_LINE_RAW_MAX_LEN:
        return False
    if re.match(r"^[\{\}\(\);\s]+$", t):
        return False
    if re.match(r"^(//|/\*|\*|#)", t):
        return False
    if re.match(r"^<Data>", t, re.IGNORECASE):
        return False
    hex_chars = len(re.findall(r"[0-9A-Fa-f]", t))
    if len(t) >= 32 and hex_chars * 100 // len(t) >= 70:
        return False
    return True


def truncate_sample_line(line, max_len=SAMPLE_LINE_MAX_LEN):
    """\u7528\u6cd5: \u622a\u65ad PROJECT.md \u5199\u5165\u7528\u7684 diff \u6837\u672c\u884c\uff0c\u907f\u514d\u5355\u884c\u8fc7\u957f"""
    if not line:
        return line
    if len(line) <= max_len:
        return line
    omitted = len(line) - max_len
    return line[:max_len] + "... (\u5df2\u622a\u65ad {} \u5b57\u7b26)".format(omitted)


def test_ide_layout_file(file_path):
    """\u7528\u6cd5: \u5224\u65ad\u662f\u5426\u4e3a Keil IDE \u4e2a\u4eba\u5e03\u5c40\u6587\u4ef6"""
    return bool(IDE_LAYOUT_FILE_RE.search(normalize_path(file_path)))


def get_function_name_from_context(ctx_line):
    if not ctx_line:
        return ""
    matches = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", ctx_line)
    return matches[-1] if matches else ""


def get_assign_info(line):
    if not line or "=" not in line:
        return None
    t = line.strip()
    if t.startswith(("if ", "while ", "for ")):
        return None
    parts = line.split("=", 1)
    if len(parts) != 2:
        return None
    lhs = parts[0].strip()
    rhs = parts[1].strip().rstrip(";")
    if not lhs or not rhs:
        return None
    return {"lhs": re.sub(r"\s+", " ", lhs), "rhs": re.sub(r"\s+", " ", rhs)}


def get_file_change_detail(repo_root, file_path, commit_sha=None):
    if test_ide_layout_file(file_path):
        return {
            "functions": [],
            "added_samples": ["(IDE \u5e03\u5c40\u6587\u4ef6\uff0c\u5df2\u7701\u7565 diff \u7ec6\u8282)"],
            "deleted_samples": [],
            "assign_changes": [],
        }

    try:
        if commit_sha:
            out = run_git_capture(repo_root, "show", commit_sha, "--unified=0", "--", file_path, timeout=60)
        else:
            out = run_git_capture(repo_root, "diff", "--cached", "--unified=0", "--", file_path, timeout=60)
        diff_lines = out.splitlines()
    except Exception:
        diff_lines = []

    function_set = []
    added_samples = []
    deleted_samples = []

    for line in diff_lines:
        m = re.match(r"^@@ .* @@\s*(.*)$", line)
        if m:
            fn = get_function_name_from_context(m.group(1).strip())
            if fn and fn not in function_set:
                function_set.append(fn)
            continue
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            content = line[1:].strip()
            if test_useful_code_line(content) and len(added_samples) < 2:
                added_samples.append(content)
        elif line.startswith("-"):
            content = line[1:].strip()
            if test_useful_code_line(content) and len(deleted_samples) < 2:
                deleted_samples.append(content)

    assign_changes = []
    for a in added_samples:
        a_info = get_assign_info(a)
        if not a_info:
            continue
        for d in deleted_samples:
            d_info = get_assign_info(d)
            if not d_info:
                continue
            if a_info["lhs"] == d_info["lhs"] and a_info["rhs"] != d_info["rhs"]:
                assign_changes.append(
                    "{}: {} -> {}".format(a_info["lhs"], d_info["rhs"], a_info["rhs"])
                )
                break
        if len(assign_changes) >= 2:
            break

    return {
        "functions": function_set[:3],
        "added_samples": [truncate_sample_line(s) for s in added_samples],
        "deleted_samples": [truncate_sample_line(s) for s in deleted_samples],
        "assign_changes": assign_changes,
    }


def get_smart_truncated_diff(repo_root, files, max_lines_per_file, max_total_bytes, commit_sha=None):
    sb = []
    total_len = 0
    for f in files:
        try:
            if commit_sha:
                out = run_git_capture(repo_root, "show", commit_sha, "--unified=3", "--", f, timeout=60)
            else:
                out = run_git_capture(repo_root, "diff", "--cached", "--unified=3", "--", f, timeout=60)
            raw = out.splitlines()
        except Exception:
            continue
        if not raw:
            continue
        if len(raw) > max_lines_per_file:
            half = max_lines_per_file // 2
            omitted = len(raw) - max_lines_per_file
            take = raw[:half] + ["... (\u4e2d\u95f4\u5df2\u7701\u7565 {} \u884c) ...".format(omitted)] + raw[-half:]
        else:
            take = raw
        for line in take:
            sb.append(line)
            total_len += len(line) + 1
            if total_len >= max_total_bytes:
                sb.append("... (\u6574\u4f53\u5df2\u8fbe\u4e0a\u9650\uff0c\u5269\u4f59\u6587\u4ef6\u88ab\u622a\u65ad) ...")
                return "\n".join(sb)
        sb.append("")
    return "\n".join(sb)


def find_python():
    import shutil

    if sys.platform == "win32":
        candidates = ("py", "python", "python3")
    else:
        candidates = ("python3", "python", "py")
    for cand in candidates:
        p = shutil.which(cand)
        if not p:
            continue
        if sys.platform == "win32" and "WindowsApps" in p.replace("\\", "/"):
            continue
        return p
    return None


def format_ai_model_table_row(llm_info, used_ai):
    """\u7528\u6cd5: \u751f\u6210 PROJECT.md \u8868\u683c\u4e2d\u7684 AI Model \u884c"""
    if not used_ai:
        return "| AI Model | \u5206\u6790\u5931\u8d25 |"
    profile = llm_info.get("profile_name") or "default"
    model = llm_info.get("model") or "?"
    return "| AI Model | {} / {} |".format(profile, model)


def format_entry_meta_rows(entry_id, commit_sha=None):
    """\u7528\u6cd5: \u751f\u6210 Entry ID / Staged Tree / Commit \u8bf4\u660e\u884c"""
    rows = ["| Entry ID | {} |".format(entry_id)]
    if entry_id.startswith("staged-"):
        tree_short = entry_id[7:]
        rows.append(
            "| Staged Tree | {} (`git write-tree` \u524d8\u4f4d\uff0c\u975e commit hash) |".format(tree_short)
        )
    if commit_sha:
        rows.append("| Commit | {} |".format(commit_sha))
    else:
        rows.append("| Commit | (\u7b56\u7565A\u9ed8\u8ba4\u4e0d\u56de\u5199 commit hash) |")
    return rows


def prepend_ai_model_to_analysis(ai_text, llm_info):
    """\u7528\u6cd5: \u5728\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\u5757\u9996\u884c\u6ce8\u660e\u6240\u7528\u5927\u6a21\u578b"""
    if not ai_text or not llm_info:
        return ai_text
    profile = llm_info.get("profile_name") or "default"
    model = llm_info.get("model") or "?"
    marker = "**\u4e2d\u6587\u5de5\u7a0b\u5206\u6790\uff08AI\uff09**"
    note = "- \u5206\u6790\u6a21\u578b\uff1a{} / {}\n".format(profile, model)
    if note.strip() in ai_text:
        return ai_text
    if marker in ai_text:
        return ai_text.replace(marker, marker + "\n" + note.rstrip(), 1)
    return note + ai_text


def patch_project_md_after_commit(project_md, entry_id, commit_sha, log_fn):
    """\u7528\u6cd5: post-commit \u540e\u628a commit hash \u5199\u56de PROJECT.md \u5bf9\u5e94\u6761\u76ee"""
    if not os.path.isfile(project_md) or not entry_id or not commit_sha:
        return
    content = read_text_utf8(project_md)
    title = "### {}".format(entry_id)
    idx = content.find(title)
    if idx < 0:
        return
    title_line_end = content.find("\n", idx)
    if title_line_end < 0:
        return
    new_title = "### {} \u00b7 commit {}".format(entry_id, commit_sha[:12])
    if "\u00b7 commit" not in content[idx:title_line_end]:
        content = content[:idx] + new_title + content[title_line_end:]

    commit_row = "| Commit | {} |".format(commit_sha)
    pending_row = "| Commit | (\u63d0\u4ea4\u540e\u7531 post-commit \u5199\u5165) |"
    if pending_row in content:
        content = content.replace(pending_row, commit_row, 1)
    else:
        field_hdr = "| Field | Value |"
        pos = content.find(field_hdr, idx)
        if pos >= 0:
            line_end = content.find("\n", pos)
            if line_end >= 0 and commit_row not in content[idx:idx + 2000]:
                content = content[: line_end + 1] + commit_row + "\n" + content[line_end + 1 :]

    write_text_utf8(project_md, content)
    if log_fn:
        log_fn("PROJECT.md \u5df2\u5199\u5165 commit={} \u5230 entry={}".format(commit_sha[:8], entry_id))


def invoke_ai_analysis(
    repo_root,
    added_files,
    modified_files,
    deleted_files,
    meta,
    project_context,
    script_dir,
    timeout_sec,
    log_fn,
    commit_sha=None,
):
    py_script = os.path.join(script_dir, "ai_analyze.py")
    if not os.path.isfile(py_script):
        log_fn("ai_analyze.py \u4e0d\u5b58\u5728\uff0c\u8df3\u8fc7 AI \u5206\u6790")
        return None

    py_cmd = find_python()
    if not py_cmd:
        log_fn("\u672a\u627e\u5230 python \u89e3\u91ca\u5668\uff0c\u8df3\u8fc7 AI \u5206\u6790")
        return None

    initialize_llm_env(log_fn)
    from llm_env import resolve_llm_config, format_llm_log_label

    llm_cfg = resolve_llm_config()
    llm_label = format_llm_log_label(llm_cfg)
    if not llm_cfg.get("api_key"):
        log_fn("config.user.json \u672a\u914d\u7f6e api_key\uff0c\u8df3\u8fc7 AI \u5206\u6790\uff08{}\uff09".format(llm_label))
        return None
    if not llm_cfg.get("base_url") or not llm_cfg.get("model"):
        log_fn("config.user.json \u9700\u586b\u5199 base_url \u548c model\uff0c\u8df3\u8fc7 AI \u5206\u6790\uff08{}\uff09".format(llm_label))
        return None

    all_files = list(added_files) + list(modified_files) + list(deleted_files)
    cfg = load_config(repo_root)
    file_summaries = build_file_summaries(repo_root, all_files, commit_sha=commit_sha)
    diff_text = get_smart_truncated_diff(
        repo_root,
        all_files,
        cfg.get("diff_max_lines_per_file", 120),
        cfg.get("diff_max_total_bytes", 24000),
        commit_sha=commit_sha,
    )
    if not diff_text.strip():
        log_fn("\u65e0\u6709\u6548 diff\uff0c\u8df3\u8fc7 AI \u5206\u6790")
        return None

    payload = {
        "files_added": added_files,
        "files_modified": modified_files,
        "files_deleted": deleted_files,
        "file_summaries": file_summaries,
        "diff_text": diff_text,
        "meta": meta,
        "project_context": project_context,
        "repo_root": repo_root,
    }

    tmp_dir = tempfile.gettempdir()
    in_file = os.path.join(tmp_dir, "ai_in_{}.json".format(uuid.uuid4().hex))
    try:
        with open(in_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        log_fn(
            "\u8c03\u7528 AI \u5206\u6790\uff0c{}\uff0cpython={}\uff0ctimeout={}s".format(
                llm_label, py_cmd, timeout_sec
            )
        )
        env = os.environ.copy()
        env.setdefault("GIT_COMMIT_AI_ANALYZER_HOME", get_tool_home())
        r = subprocess.run(
            [py_cmd, py_script, in_file],
            capture_output=True,
            timeout=timeout_sec,
            env=env,
        )
        stderr_text = (r.stderr or b"").decode("utf-8", errors="replace")
        stdout_text = (r.stdout or b"").decode("utf-8", errors="replace")

        if r.returncode != 0:
            brief = ""
            for ln in stderr_text.splitlines():
                if ln.strip():
                    brief = ln.strip()[:300]
                    break
            log_fn(
                "AI \u5206\u6790\u5931\u8d25\uff0c{}\uff0cExitCode={}\uff0c\u539f\u56e0={}".format(
                    llm_label, r.returncode, brief
                )
            )
            return None
        if not stdout_text.strip():
            log_fn("AI \u8f93\u51fa\u4e3a\u7a7a\uff0c{}".format(llm_label))
            return None
        log_fn("AI \u5206\u6790\u6210\u529f\uff0c{}\uff0c\u957f\u5ea6={}".format(llm_label, len(stdout_text)))
        return {
            "text": stdout_text.strip(),
            "profile_name": llm_cfg.get("profile_name") or "",
            "model": llm_cfg.get("model") or "",
            "base_url": llm_cfg.get("base_url") or "",
        }
    except subprocess.TimeoutExpired:
        log_fn("AI \u5206\u6790\u8d85\u65f6\uff0c{}\uff0c{}s".format(llm_label, timeout_sec))
        return None
    except Exception as e:
        log_fn("AI \u5206\u6790\u5f02\u5e38\uff0c{}\uff0c{}".format(llm_label, e))
        return None
    finally:
        if os.path.isfile(in_file):
            try:
                os.remove(in_file)
            except Exception:
                pass


def load_commit_map(path):
    if not os.path.isfile(path):
        return {"entries": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return {"entries": obj.get("entries") or []}
    except Exception:
        return {"entries": []}


def save_commit_map(path, mp):
    write_text_utf8(path, json.dumps({"entries": mp.get("entries") or []}, ensure_ascii=False, indent=2))


def save_pending(path, entry_id, date_str):
    write_text_utf8(
        path,
        json.dumps({"entry_id": entry_id, "date": date_str}, ensure_ascii=False),
    )


def finish_commit_map_record(repo_root, commit_map_file, pending_file, log_fn):
    if not os.path.isfile(pending_file):
        log_fn("FinishCommitMap: \u65e0 pending \u6761\u76ee\uff0c\u8df3\u8fc7")
        return
    try:
        with open(pending_file, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception:
        log_fn("FinishCommitMap: pending \u89e3\u6790\u5931\u8d25")
        try:
            os.remove(pending_file)
        except Exception:
            pass
        return
    head_sha = run_git(repo_root, "rev-parse", "HEAD")
    if not head_sha:
        log_fn("FinishCommitMap: \u65e0\u6cd5\u8bfb\u53d6 HEAD")
        return
    mp = load_commit_map(commit_map_file)
    new_entry = {
        "commit": head_sha,
        "entry_id": pending.get("entry_id"),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    entries = [new_entry] + [e for e in mp["entries"] if e.get("entry_id") != pending.get("entry_id")]
    cfg = load_config()
    max_n = cfg.get("max_commit_map_entries", 100)
    mp["entries"] = entries[:max_n]
    save_commit_map(commit_map_file, mp)
    try:
        os.remove(pending_file)
    except Exception:
        pass
    log_fn(
        "FinishCommitMap: commit={} entry={}".format(
            head_sha[:8], pending.get("entry_id")
        )
    )
    if os.environ.get("GIT_COMMIT_AI_ANALYZER_PATCH_AFTER_COMMIT", "").strip() == "1":
        project_md = os.path.join(repo_root, ".git-commit-ai-analyzer", "PROJECT.md")
        if not os.path.isfile(project_md):
            project_md = os.path.join(repo_root, ".git-commit-analyzer", "PROJECT.md")
        patch_project_md_after_commit(project_md, pending.get("entry_id"), head_sha, log_fn)
        ai_context_md = os.path.join(os.path.dirname(project_md), "AI_CONTEXT.md")
        patch_ai_context_after_commit(ai_context_md, pending.get("entry_id"), head_sha, log_fn)
    else:
        log_fn("FinishCommitMap: \u5df2\u8df3\u8fc7 post-commit \u6587\u6863\u56de\u5199")


def test_commit_reachable(repo_root, commit_sha):
    if not commit_sha:
        return False
    try:
        r = subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit_sha, "HEAD"],
            cwd=repo_root,
            capture_output=True,
            timeout=30,
        )
        return r.returncode == 0
    except Exception:
        return False


def remove_orphan_entries(repo_root, doc_path, commit_map_file, log_fn):
    if not os.path.isfile(doc_path) or not os.path.isfile(commit_map_file):
        return False
    mp = load_commit_map(commit_map_file)
    if not mp["entries"]:
        return False
    orphan_ids = set()
    kept = []
    for rec in mp["entries"]:
        if test_commit_reachable(repo_root, rec.get("commit")):
            kept.append(rec)
        else:
            orphan_ids.add(rec.get("entry_id"))
    if not orphan_ids:
        return False
    content = read_text_utf8(doc_path)
    info = get_recent_section(content)
    if not info:
        return False
    filtered = []
    for entry in info["old_entries"]:
        keep = True
        for oid in orphan_ids:
            if oid and re.search(r"(?m)^### " + re.escape(str(oid)) + r"\b", entry):
                keep = False
                break
        if keep:
            filtered.append(entry)
    if len(filtered) == len(info["old_entries"]):
        return False
    log_fn("\u5df2\u6e05\u7406\u5df2\u64a4\u56de\u63d0\u4ea4\u7684\u6761\u76ee: " + ", ".join(sorted(orphan_ids)))
    new_content = set_recent_section(content, filtered)
    write_text_utf8(doc_path, new_content)
    mp["entries"] = kept
    save_commit_map(commit_map_file, mp)

    ai_context_md = os.path.join(os.path.dirname(doc_path), "AI_CONTEXT.md")
    remove_prefixes = ["### {}".format(oid) for oid in orphan_ids if oid]
    remove_ai_context_entries_by_prefix(ai_context_md, remove_prefixes, log_fn)
    return True


def get_project_context(project_md, repo_root, log_fn):
    fm, _ = parse_frontmatter(read_text_utf8(project_md)) if os.path.isfile(project_md) else ({}, "")
    ctx = (fm.get("project_context") or "").strip()
    if ctx and len(ctx) > 20 and "\u5f85\u9996\u6b21" not in ctx:
        return ctx
    try:
        from project_profile import ensure_project_context

        return ensure_project_context(repo_root, project_md, log_fn)
    except Exception as e:
        log_fn("project_profile \u5931\u8d25: {}".format(e))
        return ctx or ""


def build_change_entry(
    repo_root,
    entry_id,
    commit_author,
    commit_date,
    added_files,
    modified_files,
    deleted_files,
    added_count,
    modified_count,
    deleted_count,
    total_files,
    insertions,
    deletions,
    module_list,
    project_context,
    script_dir,
    cfg,
    log_fn,
    commit_sha=None,
):
    changes = []
    title = "### {}".format(entry_id)
    if commit_sha:
        title = "### {} \u00b7 commit {}".format(entry_id, commit_sha[:12])
    changes.append(title)
    changes.append("")
    changes.append("| Field | Value |")
    changes.append("|-------|-------|")
    for row in format_entry_meta_rows(entry_id, commit_sha=commit_sha):
        changes.append(row)
    changes.append("| Author | {} |".format(commit_author))
    changes.append("| Date | {} |".format(commit_date))
    changes.append("| Added | {} |".format(added_count))
    changes.append("| Modified | {} |".format(modified_count))
    changes.append("| Deleted | {} |".format(deleted_count))
    changes.append("| Files | {} |".format(total_files))
    changes.append("| Insertions | {} |".format(insertions))
    changes.append("| Deletions | {} |".format(deletions))
    changes.append("| Modules | {} |".format(len(module_list)))
    changes.append("")

    ai_meta = {
        "entry_id": entry_id,
        "author": commit_author,
        "date": commit_date,
        "files_total": total_files,
        "insertions": insertions,
        "deletions": deletions,
        "modules": "\u3001".join(module_list),
        "project_context": project_context,
    }
    ai_pack = invoke_ai_analysis(
        repo_root,
        added_files,
        modified_files,
        deleted_files,
        ai_meta,
        project_context,
        script_dir,
        cfg.get("ai_timeout_sec", 200),
        log_fn,
        commit_sha=commit_sha,
    )
    llm_info = ai_pack
    ai_text = (ai_pack or {}).get("text") if ai_pack else None
    changes.append(format_ai_model_table_row(llm_info, bool(ai_text)))
    changes.append("")

    if ai_text:
        ai_text = prepend_ai_model_to_analysis(ai_text, llm_info)
        changes.append(ai_text)
        changes.append("")
        changes.append("> \u6587\u4ef6\u660e\u7ec6\u89c1\u4e0b\u65b9 Modified/Added \u5217\u8868\u3002")
        changes.append("")
    else:
        log_fn("AI \u5206\u6790\u672a\u6210\u529f\uff0c\u5199\u5165\u300c\u5206\u6790\u5931\u8d25\u300d")
        changes.append("\u5206\u6790\u5931\u8d25\u3002")
        changes.append("")

    if module_list:
        changes.append("**Modules**")
        for m in module_list:
            changes.append("  - {}".format(m))
        changes.append("")

    def _append_file_section(title, files, count, show_del=False):
        if not files:
            return
        changes.append("**{}** ({})".format(title, count))
        for fp in files:
            details = get_file_change_detail(repo_root, fp, commit_sha=commit_sha)
            mod = get_module_name(fp)
            changes.append("  - {}  [{}]".format(fp, mod))
            if details["functions"]:
                changes.append("    - Touch: {}".format(" | ".join(details["functions"])))
            if details["assign_changes"]:
                changes.append("    - Change: {}".format(" ; ".join(details["assign_changes"])))
            if details["added_samples"]:
                changes.append("    - Add: {}".format(" ; ".join(details["added_samples"])))
            if show_del and details["deleted_samples"]:
                changes.append("    - Del: {}".format(" ; ".join(details["deleted_samples"])))
        changes.append("")

    _append_file_section("Added", added_files, added_count)
    _append_file_section("Modified", modified_files, modified_count, show_del=True)
    if deleted_files:
        changes.append("**Deleted** ({})".format(deleted_count))
        for fp in deleted_files:
            changes.append("  - {}  [{}]".format(fp, get_module_name(fp)))
        changes.append("")
    changes.append("---")
    context_meta = {
        "entry_id": entry_id,
        "commit_sha": commit_sha or "",
        "author": commit_author,
        "date": commit_date,
        "files": list(added_files) + list(modified_files) + list(deleted_files),
        "ai_text": ai_text or "",
    }
    return "\n".join(changes), context_meta


def update_document(
    doc_path,
    change_body,
    entry_id,
    max_entries,
    log_fn,
):
    content = read_text_utf8(doc_path)
    info = get_recent_section(content)
    if not info:
        log_fn("Markers not found in {}".format(doc_path))
        return False
    entry_title = "### {}".format(entry_id)
    all_entries = [change_body] + [
        e
        for e in info["old_entries"]
        if e != change_body and not e.startswith(entry_title)
    ]
    content = set_recent_section(content, all_entries, max_entries)
    write_text_utf8(doc_path, content)
    log_fn("Recent Changes section updated in {}".format(os.path.basename(doc_path)))
    return True


def list_cached_names(repo_root, diff_filter):
    out = run_git(repo_root, "diff", "--cached", "--diff-filter={}".format(diff_filter), "--name-only")
    if not out:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def resolve_commit_sha(repo_root, ref):
    sha = run_git(repo_root, "rev-parse", "--verify", ref)
    return sha.strip() if sha else ""


def list_commit_names(repo_root, commit_sha, diff_filter):
    out = run_git(
        repo_root,
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "--diff-filter={}".format(diff_filter),
        "-r",
        commit_sha,
    )
    if not out:
        return []
    return [ln for ln in out.splitlines() if ln.strip()]


def get_commit_numstat(repo_root, commit_sha, ignore_patterns):
    insertions = 0
    deletions = 0
    try:
        out = run_git_capture(repo_root, "show", commit_sha, "--numstat", "--format=", timeout=60)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            fp = parts[2]
            if test_ignored_file(fp, ignore_patterns):
                continue
            if parts[0].isdigit():
                insertions += int(parts[0])
            if parts[1].isdigit():
                deletions += int(parts[1])
    except Exception:
        pass
    return insertions, deletions


def get_commit_author_date(repo_root, commit_sha):
    author = run_git(repo_root, "show", "-s", "--format=%an", commit_sha) or "unknown"
    date_str = run_git(repo_root, "show", "-s", "--format=%ci", commit_sha)
    if not date_str:
        try:
            date_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        except Exception:
            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return author, date_str


def commit_map_has_entry(mp, commit_sha, entry_id):
    for rec in mp.get("entries") or []:
        if rec.get("commit") == commit_sha:
            return True
        if entry_id and rec.get("entry_id") == entry_id:
            return True
    return False


def record_commit_map_entry(commit_map_file, commit_sha, entry_id, log_fn):
    mp = load_commit_map(commit_map_file)
    if commit_map_has_entry(mp, commit_sha, entry_id):
        log_fn("Backfill: commit-map \u5df2\u6709\u8bb0\u5f55\uff0c\u8df3\u8fc7\u6620\u5c04")
        return
    new_entry = {
        "commit": commit_sha,
        "entry_id": entry_id,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    entries = [new_entry] + [e for e in mp["entries"] if e.get("entry_id") != entry_id]
    cfg = load_config()
    max_n = cfg.get("max_commit_map_entries", 100)
    mp["entries"] = entries[:max_n]
    save_commit_map(commit_map_file, mp)
    log_fn("Backfill: commit-map \u5df2\u8bb0\u5f55 commit={} entry={}".format(commit_sha[:8], entry_id))


def run_backfill_commit(
    repo_root,
    commit_ref,
    project_md,
    commit_map_file,
    script_dir,
    cfg,
    log_fn,
    force=False,
):
    commit_sha = resolve_commit_sha(repo_root, commit_ref)
    if not commit_sha:
        log_fn("Backfill: \u65e0\u6548 commit \u5f15\u7528: {}".format(commit_ref))
        return 1
    if not test_commit_reachable(repo_root, commit_sha):
        log_fn("Backfill: commit \u4e0d\u5728\u5f53\u524d HEAD \u5386\u53f2\u4e2d: {}".format(commit_sha[:8]))
        return 1

    entry_id = "commit-" + commit_sha[:8]
    mp = load_commit_map(commit_map_file)
    existing_entry_id = ""
    for rec in mp.get("entries") or []:
        if rec.get("commit") == commit_sha and rec.get("entry_id"):
            existing_entry_id = rec.get("entry_id")
            break
    if existing_entry_id:
        entry_id = existing_entry_id
    if commit_map_has_entry(mp, commit_sha, entry_id) and not force:
        log_fn("Backfill: \u5df2\u5206\u6790\u8fc7 commit {} (entry={})".format(commit_sha[:8], entry_id))
        return 0
    if force and os.path.isfile(project_md):
        content = read_text_utf8(project_md)
        info = get_recent_section(content)
        if info:
            remove_ids = {entry_id}
            if existing_entry_id and existing_entry_id != entry_id:
                remove_ids.add(existing_entry_id)
            remove_ids.add("commit-" + commit_sha[:8])
            filtered = [
                e
                for e in info["old_entries"]
                if not any(e.startswith("### {}".format(rid)) for rid in remove_ids if rid)
            ]
            if len(filtered) != len(info["old_entries"]):
                write_text_utf8(project_md, set_recent_section(content, filtered))
                log_fn("Backfill: \u5df2\u79fb\u9664\u65e7 entry={}".format(entry_id))
            ai_context_md = os.path.join(os.path.dirname(project_md), "AI_CONTEXT.md")
            remove_prefixes = ["### {}".format(rid) for rid in remove_ids if rid]
            remove_prefixes.append("### {}".format(commit_sha[:8]))
            remove_ai_context_entries_by_prefix(ai_context_md, remove_prefixes, log_fn)

    cfg = load_config(repo_root)
    ignore_patterns = cfg.get("ignore_patterns") or []
    added_raw = list_commit_names(repo_root, commit_sha, "A")
    modified_raw = list_commit_names(repo_root, commit_sha, "M")
    deleted_raw = list_commit_names(repo_root, commit_sha, "D")

    added_files = [f for f in added_raw if not test_ignored_file(f, ignore_patterns)]
    modified_files = [f for f in modified_raw if not test_ignored_file(f, ignore_patterns)]
    deleted_files = [f for f in deleted_raw if not test_ignored_file(f, ignore_patterns)]

    added_count = len(added_files)
    modified_count = len(modified_files)
    deleted_count = len(deleted_files)
    total_files = added_count + modified_count + deleted_count

    if total_files == 0:
        log_fn("Backfill: \u65e0\u6709\u6548\u6587\u4ef6\u53d8\u66f4\uff08\u5ffd\u7565\u89c4\u5219\u540e\u4e3a\u7a7a\uff09")
        return 0

    insertions, deletions = get_commit_numstat(repo_root, commit_sha, ignore_patterns)
    commit_author, commit_date = get_commit_author_date(repo_root, commit_sha)

    module_set = set()
    for f in added_files + modified_files + deleted_files:
        module_set.add(get_module_name(f))
    module_list = sorted(module_set)

    log_fn(
        "Backfill: commit={} Entry={} Added={} Modified={} Deleted={} +{} -{}".format(
            commit_sha[:8],
            entry_id,
            added_count,
            modified_count,
            deleted_count,
            insertions,
            deletions,
        )
    )

    ensure_project_md_skeleton(project_md)
    project_context = get_project_context(project_md, repo_root, log_fn)

    change_body, context_meta = build_change_entry(
        repo_root,
        entry_id,
        commit_author,
        commit_date,
        added_files,
        modified_files,
        deleted_files,
        added_count,
        modified_count,
        deleted_count,
        total_files,
        insertions,
        deletions,
        module_list,
        project_context,
        script_dir,
        cfg,
        log_fn,
        commit_sha=commit_sha,
    )

    if not update_document(
        project_md,
        change_body,
        entry_id,
        cfg.get("max_recent_entries", 50),
        log_fn,
    ):
        return 1

    ai_context_md = os.path.join(os.path.dirname(project_md), "AI_CONTEXT.md")
    update_ai_context_md(ai_context_md, context_meta, project_context, cfg, log_fn)

    record_commit_map_entry(commit_map_file, commit_sha, entry_id, log_fn)
    log_fn("Backfill: PROJECT.md \u5df2\u8865\u5199 entry={}".format(entry_id))
    return 0


def main():
    parser = argparse.ArgumentParser(description="git-commit-ai-analyzer update_project")
    parser.add_argument("--repo", default="", help="repository root")
    parser.add_argument("--prune-only", action="store_true")
    parser.add_argument("--finish-commit-map", action="store_true")
    parser.add_argument(
        "--backfill-commit",
        default="",
        help="analyze an existing commit and append entry to PROJECT.md",
    )
    parser.add_argument(
        "--backfill-force",
        action="store_true",
        help="replace existing backfill entry for the same commit",
    )
    args = parser.parse_args()

    repo_root = args.repo or os.getcwd()
    repo_root = os.path.abspath(repo_root)
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        return 0

    for _dis in (".git-commit-ai-analyzer.disabled", ".git-commit-analyzer.disabled"):
        if os.path.isfile(os.path.join(repo_root, _dis)):
            return 0

    tool_home = get_tool_home()
    script_dir = os.path.join(tool_home, "scripts")
    analyzer_dir = os.path.join(repo_root, ".git-commit-ai-analyzer")
    local_dir = os.path.join(analyzer_dir, ".local")
    project_md = os.path.join(analyzer_dir, "PROJECT.md")
    log_file = os.path.join(local_dir, "update-project.log")
    commit_map_file = os.path.join(local_dir, "commit-map.json")
    pending_file = os.path.join(local_dir, ".pending-entry.json")

    def log_fn(msg):
        append_log(log_file, msg)

    try:
        os.makedirs(local_dir, exist_ok=True)
    except Exception:
        return 0

    ensure_gitignore_analyzer_local(repo_root, log_fn)
    ensure_gitignore_local(repo_root, log_fn)

    if args.finish_commit_map:
        log_fn("===== FinishCommitMap =====")
        finish_commit_map_record(repo_root, commit_map_file, pending_file, log_fn)
        return 0

    cfg = load_config(repo_root)

    if args.backfill_commit:
        log_fn("===== BackfillCommit =====")
        return run_backfill_commit(
            repo_root,
            args.backfill_commit,
            project_md,
            commit_map_file,
            script_dir,
            cfg,
            log_fn,
            force=args.backfill_force,
        )

    log_fn("===== git-commit-ai-analyzer Started =====")
    ignore_patterns = cfg.get("ignore_patterns") or []

    pruned = remove_orphan_entries(repo_root, project_md, commit_map_file, log_fn)

    if args.prune_only:
        if pruned:
            log_fn("PruneOnly: PROJECT.md / AI_CONTEXT.md \u5df2\u66f4\u65b0")
        else:
            log_fn("PruneOnly: \u65e0\u9700\u6e05\u7406")
        return 0

    staged_tree = run_git(repo_root, "write-tree")
    if not staged_tree:
        log_fn("No staged tree, exit")
        return 0

    entry_id = "staged-" + staged_tree[:8]
    commit_author = run_git(repo_root, "config", "user.name") or "unknown"
    try:
        commit_date = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    except Exception:
        commit_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log_fn("Entry={} Author={}".format(entry_id, commit_author))

    added_raw = list_cached_names(repo_root, "A")
    modified_raw = list_cached_names(repo_root, "M")
    deleted_raw = list_cached_names(repo_root, "D")

    added_files = [f for f in added_raw if not test_ignored_file(f, ignore_patterns)]
    modified_files = [f for f in modified_raw if not test_ignored_file(f, ignore_patterns)]
    deleted_files = [f for f in deleted_raw if not test_ignored_file(f, ignore_patterns)]

    added_count = len(added_files)
    modified_count = len(modified_files)
    deleted_count = len(deleted_files)
    total_files = added_count + modified_count + deleted_count

    if total_files == 0:
        log_fn("No relevant file changes after ignore rules, skip")
        return 0

    insertions = 0
    deletions = 0
    try:
        out = run_git_capture(repo_root, "diff", "--cached", "--numstat", timeout=60)
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            fp = parts[2]
            if test_ignored_file(fp, ignore_patterns):
                continue
            if parts[0].isdigit():
                insertions += int(parts[0])
            if parts[1].isdigit():
                deletions += int(parts[1])
    except Exception:
        pass

    module_set = set()
    for f in added_files + modified_files + deleted_files:
        module_set.add(get_module_name(f))
    module_list = sorted(module_set)

    log_fn(
        "Added={} Modified={} Deleted={} Files={} +{} -{}".format(
            added_count,
            modified_count,
            deleted_count,
            total_files,
            insertions,
            deletions,
        )
    )

    ensure_project_md_skeleton(project_md)
    project_context = get_project_context(project_md, repo_root, log_fn)

    change_body, context_meta = build_change_entry(
        repo_root,
        entry_id,
        commit_author,
        commit_date,
        added_files,
        modified_files,
        deleted_files,
        added_count,
        modified_count,
        deleted_count,
        total_files,
        insertions,
        deletions,
        module_list,
        project_context,
        script_dir,
        cfg,
        log_fn,
    )

    log_fn("Change body built")

    if not update_document(
        project_md,
        change_body,
        entry_id,
        cfg.get("max_recent_entries", 50),
        log_fn,
    ):
        return 0

    ai_context_md = os.path.join(analyzer_dir, "AI_CONTEXT.md")
    update_ai_context_md(ai_context_md, context_meta, project_context, cfg, log_fn)

    save_pending(pending_file, entry_id, commit_date)
    log_fn("PROJECT.md written successfully, pending entry={}".format(entry_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
