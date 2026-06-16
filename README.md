# git-commit-ai-analyzer

一个面向 Git 仓库的全局 Hook 工具。

安装一次后，任意本地 Git 仓库在执行 `git commit` 时都会自动调用兼容 OpenAI 协议的 HTTP API，生成中文工程分析摘要，并写入仓库内的：

- `.git-commit-ai-analyzer/PROJECT.md` — 详细版，供工程师阅读
- `.git-commit-ai-analyzer/AI_CONTEXT.md` — 极简版，供 Cursor / Codex 等 AI 快速了解项目

- 不依赖 IDE
- 默认不阻断 commit
- 支持多模型配置
- MIT 开源

仓库地址：`https://github.com/upstart647/git-commit-ai-analyzer.git`

## 适用场景

- 希望在每次提交后自动沉淀“这次为什么改、影响什么、建议回归什么”
- 希望给 AI 或新同事提供项目上下文，而不是只看零散 diff
- 希望跨仓库复用同一套 Git Hook，而不是每个项目单独配置

## 工作方式

安装脚本会做两件事：

1. 将工具安装到 `~/.git-commit-ai-analyzer`
2. 将 Git 全局 `core.hooksPath` 指向该工具内的 `hooks/`

之后你在任意本地 Git 仓库执行 `git commit` 时，Hook 会自动运行分析脚本，并把结果写入当前仓库的 `.git-commit-ai-analyzer/PROJECT.md` 与 `AI_CONTEXT.md`。

## 双文件输出

| 文件 | 读者 | 内容 |
|------|------|------|
| `PROJECT.md` | 人类工程师 | 元数据、AI 分析（含涉及文件）、Modules、逐文件 diff 样本 |
| `AI_CONTEXT.md` | AI Agent | 项目背景 + 最近 N 条极简摘要（Files / Why / Impact / Verify） |

**建议**：在 Cursor 中优先 `@AI_CONTEXT.md` 或将其加入规则；需要看具体 diff 时再读 `PROJECT.md`。

默认保留条数：`PROJECT.md` 50 条，`AI_CONTEXT.md` 30 条（可配置）。

## 环境要求

- `Git`
- `Python 3.10+`
- 可用的 `pip`
- 一个兼容 OpenAI Chat Completions 接口的大模型服务

如果缺少 LLM 配置，工具仍会尽量生成简要模板内容，不会因为未配置模型而阻断提交。

## 快速开始

### 方式 1：一键安装

| 平台 | 命令 |
|------|------|
| Linux / macOS / **Windows Git Bash** | `curl -fsSL https://raw.githubusercontent.com/upstart647/git-commit-ai-analyzer/main/install.sh \| bash` |
| **Windows PowerShell** | `irm https://raw.githubusercontent.com/upstart647/git-commit-ai-analyzer/main/install.ps1 \| iex` |

安装完成后，继续编辑：

```text
~/.git-commit-ai-analyzer/config.user.json
```

然后在任意 Git 仓库中提交一次测试：

```bash
git add .
git commit -m "测试提交"
```

### 方式 2：本地克隆后安装

```bash
git clone https://github.com/upstart647/git-commit-ai-analyzer.git
cd git-commit-ai-analyzer
bash install.sh
```

```powershell
git clone https://github.com/upstart647/git-commit-ai-analyzer.git
cd git-commit-ai-analyzer
powershell -ExecutionPolicy Bypass -File install.ps1
```

默认安装目录：

```text
~/.git-commit-ai-analyzer
```

## 配置说明

工具目录里有两个配置文件：

| 文件 | 谁修改 | 作用 | 是否包含敏感信息 |
|------|------|------|------|
| `config.user.json` | 你自己 | 模型配置，例如 `api_key`、`base_url`、`model` | 是，不要提交 |
| `config.default.json` | 一般不用改 | 工具默认行为，例如 diff 截断和忽略规则 | 否 |

重点记住：

- LLM 相关配置只写 `config.user.json`
- `config.user.json` 必须是合法 JSON
- JSON 不支持注释
- `config.user.json` 不要提交到 Git

首次安装时，如果 `config.user.json` 不存在，会自动由 `config.user.json.example` 复制一份。

## 推荐的多模型配置

推荐使用 `active + profiles` 结构管理多个模型：

```json
{
  "active": "deepseek",
  "profiles": {
    "deepseek": {
      "api_key": "sk-你的密钥",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
      "chat_path": "/v1/chat/completions",
      "max_tokens": 32768,
      "timeout": 180
    },
    "openai": {
      "api_key": "sk-另一把密钥",
      "base_url": "https://api.openai.com",
      "model": "gpt-4o-mini",
      "chat_path": "/v1/chat/completions",
      "max_tokens": 32768,
      "timeout": 180
    }
  }
}
```

切换模型时，只需要修改：

```json
"active": "openai"
```

### 字段说明

顶层字段：

| 字段 | 必填 | 说明 |
|------|------|------|
| `active` | 是* | 当前启用的 profile 名称，必须和 `profiles` 中的键一致 |
| `profiles` | 是* | 多个模型配置集合，键名可自定义 |

\* 使用多 profile 格式时必填；如果你仍使用旧版单组扁平字段格式，则不需要 `active` / `profiles`。

每个 `profiles.<名称>` 内支持：

| 字段 | 必填 | 说明 |
|------|------|------|
| `api_key` | 是 | Bearer Token |
| `base_url` | 是 | API 根地址，例如 `https://api.openai.com` |
| `model` | 是 | 模型 ID，例如 `gpt-4o-mini` |
| `chat_path` | 否 | 默认 `/v1/chat/completions` |
| `max_tokens` | 否 | 输出 token 上限，默认 `32768` |
| `timeout` | 否 | 请求超时秒数，默认 `180` |

### 自定义分析提示词（分层）

除模型配置外，`config.user.json` 还支持以下**顶层**字段（与 `profiles` 同级）：

| 字段 | 说明 |
|------|------|
| `prompt_extra` | 追加到默认提示词末尾，例如强调领域术语 |
| `prompt_override` | 可选，整段替换默认提示词 head（需含 `{project_context}` 占位符） |
| `project_context_extra` | 追加到仓库背景描述 |
| `ai_context_enabled` | 是否生成 `AI_CONTEXT.md`，默认 `true` |
| `max_ai_context_entries` | AI 极简历史条数，默认 `30` |

**仓库级**配置（可提交到业务仓库）：复制本仓库的 `repo-config.json.example` 为：

```text
<你的业务仓库>/.git-commit-ai-analyzer/config.json
```

示例：

```json
{
  "prompt_extra": "本项目为国标直流充电桩固件。分析时请说明影响的协议模块、保护链路与采样通道。",
  "project_context_extra": "技术栈：C/Keil，目录 SourceCode/Main、protocol_*。",
  "max_ai_context_entries": 30
}
```

合并优先级：**内置默认 → 全局 `config.user.json` → 仓库 `config.json`**（后者覆盖同名字段）。

## 可选环境变量覆盖

如果需要在 CI 或临时场景中覆盖配置，可使用以下带前缀的环境变量：

- `GIT_COMMIT_AI_ANALYZER_API_KEY`
- `GIT_COMMIT_AI_ANALYZER_BASE_URL`
- `GIT_COMMIT_AI_ANALYZER_MODEL`
- `GIT_COMMIT_AI_ANALYZER_CHAT_PATH`
- `GIT_COMMIT_AI_ANALYZER_MAX_TOKENS`
- `GIT_COMMIT_AI_ANALYZER_TIMEOUT`

默认以配置文件为准；只有在你明确设置环境变量时，才会覆盖对应字段。

## 日常使用

安装并配置完成后，日常使用就是普通的 Git 提交：

```bash
git add .
git commit -m "你的提交说明"
```

典型输出：

| 路径 | 说明 |
|------|------|
| `.git-commit-ai-analyzer/PROJECT.md` | 详细工程分析，建议提交到仓库 |
| `.git-commit-ai-analyzer/AI_CONTEXT.md` | AI 极简上下文，建议提交到仓库 |
| `.git-commit-ai-analyzer/.local/update-project.log` | 本地日志，不建议提交 |

单仓库禁用：

```bash
touch .git-commit-ai-analyzer.disabled
```

Windows PowerShell：

```powershell
New-Item .git-commit-ai-analyzer.disabled -ItemType File
```

## 手动命令

手动清理失效条目：

```bash
python3 ~/.git-commit-ai-analyzer/scripts/update_project.py --repo . --prune-only
```

回填某次历史提交：

```bash
python3 ~/.git-commit-ai-analyzer/scripts/update_project.py --repo . --backfill-commit <sha> --backfill-force
```

## 部署到另一台电脑

如果你准备在另一台电脑继续使用，推荐流程如下：

1. 安装 `Git` 和 `Python 3.10+`
2. 运行本 README 中的一键安装命令
3. 配置目标电脑上的 `~/.git-commit-ai-analyzer/config.user.json`
4. 在任意 Git 仓库执行一次测试提交

如果只是你自己的多台电脑之间迁移，也可以私下复制以下文件到新电脑：

- `~/.git-commit-ai-analyzer/config.user.json`

注意：

- `config.user.json` 含密钥，不要提交到公开仓库
- 复制配置文件属于私人迁移行为，不适合写入开源仓库

## 卸载

如果你不再使用该工具，可按以下方式卸载：

1. 恢复 Git 全局 Hook 配置
2. 删除本地工具目录

示例：

```bash
git config --global --unset core.hooksPath
rm -rf ~/.git-commit-ai-analyzer
```

Windows PowerShell：

```powershell
git config --global --unset core.hooksPath
Remove-Item -Recurse -Force $HOME\.git-commit-ai-analyzer
```

## 风险与限制

- 该工具会修改 Git 全局 `core.hooksPath`，如果你原本已经有全局 Hook，请先确认是否允许覆盖
- 该工具面向兼容 OpenAI Chat Completions 的接口，不保证适配所有非标准服务
- 网络不稳定、接口限流或配置错误时，分析内容可能退化为简要模板
- 如果某个仓库不希望启用，可在仓库根目录创建 `.git-commit-ai-analyzer.disabled`

## License

MIT，详见 [LICENSE](LICENSE)。
