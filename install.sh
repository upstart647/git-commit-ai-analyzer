#!/usr/bin/env bash
# git-commit-ai-analyzer global installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/upstart647/git-commit-ai-analyzer/main/install.sh | bash
#   bash install.sh   (from a local clone)

set -e

DEFAULT_REPO="https://github.com/upstart647/git-commit-ai-analyzer.git"
REPO_URL="${GIT_COMMIT_AI_ANALYZER_REPO:-$DEFAULT_REPO}"
INSTALL_DIR="${GIT_COMMIT_AI_ANALYZER_HOME:-$HOME/.git-commit-ai-analyzer}"

_resolve_script_dir() {
  if [ -n "${GIT_COMMIT_AI_ANALYZER_LOCAL:-}" ] && [ -d "$GIT_COMMIT_AI_ANALYZER_LOCAL/hooks" ]; then
    echo "$GIT_COMMIT_AI_ANALYZER_LOCAL"
    return 0
  fi
  local src="${BASH_SOURCE[0]:-}"
  if [ -n "$src" ] && [ -f "$src" ]; then
    local dir
    dir="$(cd "$(dirname "$src")" && pwd)"
    if [ -d "$dir/hooks" ] && [ -d "$dir/scripts" ]; then
      echo "$dir"
      return 0
    fi
  fi
  return 1
}

echo "=== git-commit-ai-analyzer install ==="

SCRIPT_DIR=""
if _resolve_script_dir; then
  SCRIPT_DIR="$(_resolve_script_dir)"
  echo "Local install from: $SCRIPT_DIR"
else
  echo "Remote install -> $INSTALL_DIR"
  if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Updating existing clone..."
    git -C "$INSTALL_DIR" pull --ff-only || true
  elif [ -d "$INSTALL_DIR" ]; then
    echo "ERROR: $INSTALL_DIR exists but is not a git repo."
    echo "Remove it or set GIT_COMMIT_AI_ANALYZER_HOME to another path."
    exit 1
  else
    git clone "$REPO_URL" "$INSTALL_DIR"
  fi
  SCRIPT_DIR="$INSTALL_DIR"
fi

HOOKS_DIR="$SCRIPT_DIR/hooks"
echo "Tool home: $SCRIPT_DIR"

PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1; then
    case "$(command -v "$cand")" in
      *WindowsApps*) continue ;;
    esac
    PY="$cand"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "[WARN] Python 3 not found. Install Python 3.10+ before hooks work."
else
  echo "Python: $($PY --version 2>&1)"
  if ! "$PY" -m pip install -r "$SCRIPT_DIR/requirements.txt" -q 2>/dev/null; then
    "$PY" -m pip install httpx
  fi
  echo "httpx: OK"
  "$PY" -m py_compile "$SCRIPT_DIR/scripts/update_project.py" "$SCRIPT_DIR/scripts/ai_analyze.py" "$SCRIPT_DIR/scripts/prompt_config.py"
  echo "Scripts: syntax OK"
fi

ENV_FILE="$HOME/.config/git-commit-ai-analyzer/env"
USER_CFG="$SCRIPT_DIR/config.user.json"
USER_EXAMPLE="$SCRIPT_DIR/config.user.json.example"
if [ ! -f "$USER_CFG" ] && [ -f "$USER_EXAMPLE" ]; then
  cp "$USER_EXAMPLE" "$USER_CFG"
  echo "Created $USER_CFG (please edit api_key, base_url, model)"
elif [ -f "$USER_CFG" ]; then
  echo "User config: $USER_CFG"
fi

git config --global core.hooksPath "$HOOKS_DIR"
echo ""
echo "Installed global hooksPath:"
git config --global --get core.hooksPath
echo ""

echo "=== LLM configuration ==="
echo "Edit: $USER_CFG"
echo "Use active + profiles in JSON (JSON has no comments)."
echo "  active: profile name to use"
echo "  profiles.<name>.api_key / base_url / model (required)"
echo ""
echo "Optional env override (prefixed, unlikely to conflict):"
echo "  GIT_COMMIT_AI_ANALYZER_API_KEY / _BASE_URL / _MODEL / ..."
echo ""
echo "Per-repo opt-out: touch <repo>/.git-commit-ai-analyzer.disabled"
echo "Done."
