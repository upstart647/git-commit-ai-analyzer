# git-commit-ai-analyzer global installer (Windows PowerShell)
# Usage:
#   irm https://raw.githubusercontent.com/upstart647/git-commit-ai-analyzer/main/install.ps1 | iex
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"

$DefaultRepo = "https://github.com/upstart647/git-commit-ai-analyzer.git"
$RepoUrl = if ($env:GIT_COMMIT_AI_ANALYZER_REPO) { $env:GIT_COMMIT_AI_ANALYZER_REPO } else { $DefaultRepo }
$InstallDir = if ($env:GIT_COMMIT_AI_ANALYZER_HOME) { $env:GIT_COMMIT_AI_ANALYZER_HOME } else { Join-Path $env:USERPROFILE ".git-commit-ai-analyzer" }

function Resolve-ScriptDir {
    if ($env:GIT_COMMIT_AI_ANALYZER_LOCAL -and (Test-Path (Join-Path $env:GIT_COMMIT_AI_ANALYZER_LOCAL "hooks"))) {
        return $env:GIT_COMMIT_AI_ANALYZER_LOCAL
    }
    $inv = $MyInvocation.PSCommandPath
    if ($inv -and (Test-Path $inv)) {
        $dir = Split-Path -Parent $inv
        if ((Test-Path (Join-Path $dir "hooks")) -and (Test-Path (Join-Path $dir "scripts"))) {
            return $dir
        }
    }
    return $null
}

Write-Host "=== git-commit-ai-analyzer install ==="

$ScriptDir = Resolve-ScriptDir
if (-not $ScriptDir) {
    Write-Host "Remote install -> $InstallDir"
    if (Test-Path (Join-Path $InstallDir ".git")) {
        Write-Host "Updating existing clone..."
        git -C $InstallDir pull --ff-only
    }
    elseif (Test-Path $InstallDir) {
        Write-Error "ERROR: $InstallDir exists but is not a git repo."
    }
    else {
        git clone $RepoUrl $InstallDir
    }
    $ScriptDir = $InstallDir
}
else {
    Write-Host "Local install from: $ScriptDir"
}

$HooksDir = Join-Path $ScriptDir "hooks"
if (-not (Test-Path $HooksDir)) {
    Write-Error "ERROR: hooks dir not found: $HooksDir"
}

git config --global core.hooksPath ($HooksDir -replace '\\', '/')
Write-Host "OK: core.hooksPath -> $(git config --global core.hooksPath)"

$py = $null
foreach ($c in @("py", "python", "python3")) {
    $found = Get-Command $c -ErrorAction SilentlyContinue
    if ($found) {
        if ($found.Source -notmatch "WindowsApps") {
            $py = $found.Source
            break
        }
    }
}

if (-not $py) {
    Write-Host "WARN: Python not found. Install Python 3.10+"
}
else {
    Write-Host "OK: python -> $py"
    $req = Join-Path $ScriptDir "requirements.txt"
    if (Test-Path $req) {
        & $py -m pip install -r $req -q
    }
    else {
        & $py -m pip install httpx -q
    }
    & $py -m py_compile (Join-Path $ScriptDir "scripts\update_project.py") (Join-Path $ScriptDir "scripts\ai_analyze.py") (Join-Path $ScriptDir "scripts\prompt_config.py")
    Write-Host "Scripts: syntax OK"
}

$UserCfg = Join-Path $ScriptDir "config.user.json"
$UserExample = Join-Path $ScriptDir "config.user.json.example"
if (-not (Test-Path $UserCfg) -and (Test-Path $UserExample)) {
    Copy-Item $UserExample $UserCfg
    Write-Host "Created $UserCfg (please edit api_key, base_url, model)"
}
elseif (Test-Path $UserCfg) {
    Write-Host "User config: $UserCfg"
}

Write-Host ""
Write-Host "=== LLM configuration ==="
Write-Host "Edit: $UserCfg"
Write-Host "Use active + profiles (JSON has no comments). Switch model by changing active."
Write-Host ""
Write-Host "Optional env override (prefixed): GIT_COMMIT_AI_ANALYZER_API_KEY, _BASE_URL, _MODEL, ..."
Write-Host ""
Write-Host "Disable in a repo: New-Item .git-commit-ai-analyzer.disabled -ItemType File"
Write-Host "Manual prune after git reset:"
Write-Host "  py $ScriptDir\scripts\update_project.py --repo . --prune-only"
Write-Host "Done."
