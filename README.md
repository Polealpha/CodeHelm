# CodeHelm

CodeHelm  An autonomous engine that steers software projects from idea to shipment.

- [English Manual](#manual-en)
- [中文版手册](#manual-zh)

---

<a id="manual-en"></a>
## English Manual

[Jump to 中文版](#manual-zh)

## 1. What It Is

CodeHelm is a local-first continuous engineering runtime. You provide a goal, and it plans tasks, splits features, executes implementation, runs validation, and persists state for long-running iteration.

Core loop:

`PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> COMMIT -> NEXT`

## 2. Install and Start

Install (recommended):

```powershell
pip install -e .
```

Start interactive UI:

```powershell
codehelm
```

Alternatives:

```powershell
caasys
python -m caasys.cli
```

## 3. Recommended New-Project Workflow

Use a dedicated folder per project.

```powershell
mkdir E:\projects\my-agent-project
cd E:\projects\my-agent-project

codehelm init --objective "Build a stock assistant for CN A-share"
codehelm set-model --implementation-backend codex --model gpt-5.3-codex --reasoning-effort xhigh
codehelm interactive
```

Then type your task directly in the prompt.

## 4. Root Isolation and Persistence

All runtime state is written under `--root`.
Default `--root` is current directory `.`.

Persistent files include:

- `AGENT_STATUS.md`
- `AGENT_POLICY.md`
- `feature_list.json`
- `progress.log`
- `.caasys/state.json`
- `.caasys/policy.json`

If you switch folders (or pass a different `--root`), state does not mix.

## 5. Interactive Usage

Prompt example:

```text
codehelm>
```

The header always shows `root=...` so you can confirm where plan/state files are being written.

You can type task text directly, or use slash commands.

Common slash commands:

- `/help`
- `/model`
- `/model <model_id> [low|medium|high|xhigh]`
- `/language`
- `/language en|zh`
- `/agents [limit]`
- `/agents all [limit]`
- `/run`
- `/plan <task text>`
- `/mode single|parallel`
- `/auto on|off`
- `/verbose on|off`
- `/status`
- `/features`
- `/policy`
- `/clear`
- `/quit`

Chinese aliases:

- `/帮助` `/模型` `/语言` `/进程` `/运行` `/计划` `/模式` `/自动` `/详细` `/状态` `/任务` `/策略` `/清屏` `/退出`

Iteration mode prompt before loop:

- `1` Auto stop decision (recommended)
- `2` Manual max iterations

Planning default in interactive mode:

- New planned features default to `parallel_safe=true`
- Disable with `--no-parallel-safe`

## 6. Models and Backends

Backend behavior:

- `codex`: use Codex for implementation
- `shell`: use implementation commands in features
- `auto`: shell when implementation commands exist, otherwise codex

Set model/backend:

```powershell
codehelm set-model --implementation-backend codex --model gpt-5.3-codex --reasoning-effort xhigh
```

For new roots, `codex_skip_git_repo_check` defaults to `true` to avoid trusted-directory blocking.

## 7. Non-Interactive CLI

Initialize and inspect:

```powershell
codehelm --root . init --objective "Ship milestone 1"
codehelm --root . status
codehelm --root . features
codehelm --root . policy
```

Plan and run:

```powershell
codehelm --root . plan-task --task-id T-001 --description "Build user auth and dashboard"
codehelm --root . iterate
codehelm --root . iterate-parallel --teams 2 --max-features 2
codehelm --root . run-project --mode parallel --teams 2 --max-iterations 10
```

Process view:

```powershell
codehelm --root . agents
codehelm --root . agents --all --limit 80
```

Quality gate:

```powershell
codehelm --root . quality-gate
codehelm --root . quality-gate --dry-run
```

## 8. Browser Validation and OSWorld

Browser validation:

```powershell
codehelm --root . browser-validate --url http://127.0.0.1:3000 --backend http --expect-text "Dashboard"
```

OSWorld run:

```powershell
codehelm --root . osworld-run --backend auto --steps-file examples/osworld_steps.sample.json --dry-run
```

## 9. Local API Server

```powershell
codehelm --root . serve --host 127.0.0.1 --port 8787
```

Endpoints:

- `GET /health`
- `GET /status`
- `GET /policy`
- `GET /quality-gate`
- `POST /iterate`
- `POST /iterate-parallel`
- `POST /run-project`
- `POST /browser-validate`
- `POST /osworld-run`
- `POST /plan-task`
- `POST /set-model`

## 10. Troubleshooting

If it still runs in old folder:

- Check your shell alias/function for hardcoded `--root`
- Or always run with explicit root:

```powershell
codehelm --root E:\projects\new-one interactive
```

If you see `quality_gate_failed`:

```powershell
codehelm --root . quality-gate
```

Then fix reported failures.

If a task was planned in wrong folder and the folder is a git repo:

```powershell
git restore -- AGENT_STATUS.md AGENT_POLICY.md feature_list.json progress.log
```

## 11. Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## 12. Project Layout

```text
.
|- src/caasys/
|  |- agents.py
|  |- browser.py
|  |- cli.py
|  |- engine.py
|  |- models.py
|  |- orchestrator.py
|  |- server.py
|  `- storage.py
|- tests/
|- AGENT_STATUS.md
|- AGENT_POLICY.md
|- feature_list.json
|- progress.log
`- .caasys/
```

## 13. Naming Notes

- Package/module name remains `caasys` (compatibility)
- Product and CLI title are `CodeHelm`

## 14. Open Source

Before publishing, review and update:

- `LICENSE` (MIT)
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `.github/workflows/ci.yml`
- `.github/ISSUE_TEMPLATE/`
- `.github/pull_request_template.md`

If your GitHub org/user and contact addresses differ, replace placeholders:

- `https://github.com/Polealpha/CodeHelm`
- `polealpha@163.com`
- `polealpha@163.com`

---

<a id="manual-zh"></a>
## 中文版手册

[跳转到 English Manual](#manual-en)

## 1. 系统简介

CodeHelm 是一个本地优先（local-first）的持续构建系统。你输入目标，它会自动规划任务、拆分特性、分配执行、运行验证，并把过程状态持久化，支持跨会话续跑。

核心循环：

`PLAN -> IMPLEMENT -> RUN -> OBSERVE -> FIX -> COMMIT -> NEXT`

## 2. 安装与启动

推荐安装：

```powershell
pip install -e .
```

启动交互界面：

```powershell
codehelm
```

备用命令：

```powershell
caasys
python -m caasys.cli
```

## 3. 推荐流程（新项目）

建议每个项目单独目录运行，避免状态污染。

```powershell
mkdir E:\projects\my-agent-project
cd E:\projects\my-agent-project

codehelm init --objective "Build a stock assistant for CN A-share"
codehelm set-model --implementation-backend codex --model gpt-5.3-codex --reasoning-effort xhigh
codehelm interactive
```

进入交互后可直接输入任务文本。

## 4. 目录隔离与状态持久化

CodeHelm 所有运行状态都写在 `--root` 指向目录。
默认 `--root` 是当前目录 `.`。

常见状态文件：

- `AGENT_STATUS.md`
- `AGENT_POLICY.md`
- `feature_list.json`
- `progress.log`
- `.caasys/state.json`
- `.caasys/policy.json`

换目录或切换 `--root` 后，状态互不影响。

## 5. 交互模式

提示符示例：

```text
codehelm>
```

顶部常驻栏会显示 `root=...`，可直接确认当前写入目录。

你可以直接输入任务，也可用 slash 命令。

常用命令：

- `/help`
- `/model`
- `/model <model_id> [low|medium|high|xhigh]`
- `/language`
- `/language en|zh`
- `/agents [limit]`
- `/agents all [limit]`
- `/run`
- `/plan <task text>`
- `/mode single|parallel`
- `/auto on|off`
- `/verbose on|off`
- `/status`
- `/features`
- `/policy`
- `/clear`
- `/quit`

中文别名：

- `/帮助` `/模型` `/语言` `/进程` `/运行` `/计划` `/模式` `/自动` `/详细` `/状态` `/任务` `/策略` `/清屏` `/退出`

执行循环前会询问迭代模式：

- `1` 自动判停（推荐）
- `2` 手动输入最大迭代次数

交互模式下，规划默认：

- 新特性默认 `parallel_safe=true`
- 可用 `--no-parallel-safe` 关闭

## 6. 模型与后端

后端策略：

- `codex`：走 Codex 执行实现
- `shell`：优先执行 feature 中 implementation commands
- `auto`：有 implementation commands 用 shell，否则 codex

设置示例：

```powershell
codehelm set-model --implementation-backend codex --model gpt-5.3-codex --reasoning-effort xhigh
```

新目录默认启用 `codex_skip_git_repo_check=true`，避免首次运行被 trusted-directory 检查拦截。

## 7. 命令行模式（非交互）

初始化与查看：

```powershell
codehelm --root . init --objective "Ship milestone 1"
codehelm --root . status
codehelm --root . features
codehelm --root . policy
```

规划与执行：

```powershell
codehelm --root . plan-task --task-id T-001 --description "Build user auth and dashboard"
codehelm --root . iterate
codehelm --root . iterate-parallel --teams 2 --max-features 2
codehelm --root . run-project --mode parallel --teams 2 --max-iterations 10
```

进程查看：

```powershell
codehelm --root . agents
codehelm --root . agents --all --limit 80
```

门禁检查：

```powershell
codehelm --root . quality-gate
codehelm --root . quality-gate --dry-run
```

## 8. 浏览器验证与 OSWorld

Browser Validate：

```powershell
codehelm --root . browser-validate --url http://127.0.0.1:3000 --backend http --expect-text "Dashboard"
```

OSWorld：

```powershell
codehelm --root . osworld-run --backend auto --steps-file examples/osworld_steps.sample.json --dry-run
```

## 9. 本地 API 服务

```powershell
codehelm --root . serve --host 127.0.0.1 --port 8787
```

接口：

- `GET /health`
- `GET /status`
- `GET /policy`
- `GET /quality-gate`
- `POST /iterate`
- `POST /iterate-parallel`
- `POST /run-project`
- `POST /browser-validate`
- `POST /osworld-run`
- `POST /plan-task`
- `POST /set-model`

## 10. 常见问题

换目录后仍跑到旧目录：

- 检查 shell 别名/函数是否写死了 `--root`
- 或直接显式指定：

```powershell
codehelm --root E:\projects\new-one interactive
```

出现 `quality_gate_failed`：

```powershell
codehelm --root . quality-gate
```

根据输出修复。

误在错误目录规划任务（且目录是 git 仓库）：

```powershell
git restore -- AGENT_STATUS.md AGENT_POLICY.md feature_list.json progress.log
```

## 11. 测试

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## 12. 项目结构

```text
.
|- src/caasys/
|  |- agents.py
|  |- browser.py
|  |- cli.py
|  |- engine.py
|  |- models.py
|  |- orchestrator.py
|  |- server.py
|  `- storage.py
|- tests/
|- AGENT_STATUS.md
|- AGENT_POLICY.md
|- feature_list.json
|- progress.log
`- .caasys/
```

## 13. 命名说明

- Python 包名仍为 `caasys`（兼容历史）
- 产品与 CLI 标题为 `CodeHelm`

## 14. 开源发布前检查

发布前请确认并按需修改：

- `LICENSE`（MIT）
- `CONTRIBUTING.md`
- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
- `.github/workflows/ci.yml`
- `.github/ISSUE_TEMPLATE/`
- `.github/pull_request_template.md`

如果你的 GitHub 组织/用户名和联系邮箱不同，请替换占位符：

- `https://github.com/Polealpha/CodeHelm`
- `polealpha@163.com`
- `polealpha@163.com`
