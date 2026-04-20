# AI CLI/IDE 规则文件完整对照表

> 调研日期：2026-04-20
> 数据来源：各工具官方文档 + GitHub + Web Search
> 用途：`ahadiff install <target>` 命令需要写入正确的规则文件

---

## 完整对照表

| 工具 | 类型 | 规则文件路径 | 格式 | 发现机制 | 备注 |
|------|------|-------------|------|---------|------|
| **Claude Code** | CLI | `CLAUDE.md`（项目根） | Markdown | 启动时自动读取；支持嵌套目录 | Anthropic 专有格式，不支持 AGENTS.md |
| **Codex CLI** | CLI | `AGENTS.md`（项目根） | Markdown | 启动时从 `~/.codex/` → git root → cwd 逐级读取 | Linux Foundation AAIF 开放标准；支持 `AGENTS.override.md` |
| **Gemini CLI** | CLI | `GEMINI.md`（项目根） | Markdown | 从 `~/.gemini/` → git root → subdirs 层级读取；支持 `@file.md` import | 可配置 `context.fileName` 改用 AGENTS.md |
| **OpenCode** | CLI | `AGENTS.md`（项目根） | Markdown | 优先 AGENTS.md，fallback 到 CLAUDE.md | Go 二进制；agent 定义在 `.opencode/agents/*.md` |
| **Cursor** | IDE | `.cursor/rules/*.mdc`（新）或 `.cursorrules`（旧） | MDC/Markdown | 新版用 `.cursor/rules/` 目录；旧版单文件 `.cursorrules` | `.cursorrules` 将废弃，迁移到 `.cursor/rules/` |
| **GitHub Copilot** | IDE/CLI | `.github/copilot-instructions.md` | Markdown | 自动检测；支持 `.github/instructions/*.instructions.md` 路径匹配 | 支持 org/repo/personal 三层优先级 |
| **Windsurf** | IDE | `.windsurf/rules/*.md`（当前推荐）；同时支持 `AGENTS.md` 零配置 | Markdown | Cascade agent 启动时加载 | `.windsurfrules` 已不推荐 |
| **Cline** | IDE 插件 | `.clinerules`（文件或目录） | Markdown | 自动读取；目录模式支持多文件 `.clinerules/*.md` | 支持 Memory Bank 集成 |
| **Amp** | CLI/IDE | `AGENTS.md`（项目根） | Markdown | 自动读取 AGENTS.md | Sourcegraph 出品；支持 `/agent` 自动生成 |
| **Aider** | CLI | `CONVENTIONS.md`（需显式加载） | Markdown | 通过 `--read CONVENTIONS.md` 或 `.aider.conf.yml` 配置 | 模型无关；需在配置中显式引用 |
| **Jules** | 异步 Agent | `AGENTS.md`（项目根） | Markdown | 克隆 repo 时自动读取 | Google 异步 coding agent；云端 VM 执行 |
| **Junie** | IDE 插件 | `AGENTS.md` | Markdown | JetBrains IDE 插件 | 走 AGENTS.md 标准 |

---

## 按标准分组

### AGENTS.md 标准（Linux Foundation AAIF）
采纳工具：Codex CLI, OpenCode, Amp, Jules, Junie, Cursor（兼容读取）, Gemini CLI（可配置）

### 专有格式
| 工具 | 专有文件 | 是否兼容 AGENTS.md |
|------|---------|:---:|
| Claude Code | `CLAUDE.md` | 否（有 3000+ upvotes 的 issue 要求支持） |
| Gemini CLI | `GEMINI.md` | 可配置为读取 AGENTS.md |
| Cursor | `.cursor/rules/*.mdc` | 兼容读取 AGENTS.md |
| Windsurf | `.windsurf/rules/*.md` | 兼容（支持 AGENTS.md 零配置） |
| Cline | `.clinerules` | 否 |
| Copilot | `.github/copilot-instructions.md` | 否 |
| Aider | `CONVENTIONS.md` | 否（需显式 --read） |

---

## AhaDiff `install` 命令映射

### 现有方案已覆盖（§20.1-20.4）

| 命令 | 写入文件 | 模板 | 状态 |
|------|---------|------|------|
| `ahadiff install claude` | `.claude/skills/ahadiff/SKILL.md` + `CLAUDE.md` 追加 | `claude/SKILL.md.j2` | ✅ 已设计 |
| `ahadiff install codex` | `AGENTS.md` | `codex/AGENTS.md.j2` | ✅ 已设计 |
| `ahadiff install cursor` | `.cursor/rules/ahadiff.mdc` | `cursor/ahadiff.mdc.j2` | ✅ 已设计 |
| `ahadiff install copilot` | `.github/copilot-instructions.md` + `.github/instructions/ahadiff.instructions.md` | `copilot/copilot-instructions.md.j2` | ✅ 已设计 |

### 新增目标（本次补充）

| 命令 | 写入文件 | 模板 | 优先级 |
|------|---------|------|:---:|
| `ahadiff install gemini` | `GEMINI.md`（追加 ahadiff 段落） | `gemini/GEMINI.md.j2` | P1 |
| `ahadiff install opencode` | `AGENTS.md`（复用 codex 模板）+ `.opencode/agents/ahadiff.md` | `opencode/ahadiff-agent.md.j2` | P1 |
| `ahadiff install windsurf` | `.windsurf/rules/ahadiff.md` | `windsurf/ahadiff-rule.md.j2` | P2 |
| `ahadiff install cline` | `.clinerules`（追加）或 `.clinerules/ahadiff.md` | `cline/clinerules.j2` | P2 |
| `ahadiff install amp` | `AGENTS.md`（复用 codex 模板） | 复用 `codex/AGENTS.md.j2` | P1 |
| `ahadiff install aider` | `.aider.conf.yml`（追加 read 项）+ `CONVENTIONS.md`（追加） | `aider/conventions.md.j2` | P2 |
| `ahadiff install jules` | `AGENTS.md`（复用 codex 模板） | 复用 `codex/AGENTS.md.j2` | P1 |

### 智能复用策略

```text
AGENTS.md 系工具共享一个模板：
  codex / opencode / amp / jules / junie → codex/AGENTS.md.j2

差异点只在附加文件：
  opencode → 额外写 .opencode/agents/ahadiff.md（subagent 定义）
  amp → 无额外文件
  jules → 无额外文件（异步 VM 会自动读 AGENTS.md）
```

---

## 写入安全规则

```text
1. --dry-run 默认显示将写入的文件列表和 diff 预览
2. 不覆盖已有规则文件内容，仅追加 AhaDiff 段落
3. 追加时用明确的分隔标记：
   <!-- AHADIFF:BEGIN --> ... <!-- AHADIFF:END -->
4. uninstall 时精确删除标记之间的内容
5. 不修改用户自定义规则
6. 文件不存在时才创建新文件
7. 每次写入记录到 .ahadiff/install.log
```

---

## 与现有方案 §20 的差异

```text
原方案 §20 覆盖：claude / codex / cursor / copilot（4 个）
本方案新增：gemini / opencode / windsurf / cline / amp / aider / jules（7 个）
总计：11 个目标

目录树变更（src/ahadiff/install/templates/）：
  新增：
    gemini/GEMINI.md.j2
    opencode/ahadiff-agent.md.j2
    windsurf/ahadiff-rule.md.j2
    cline/clinerules.j2
    aider/conventions.md.j2
  复用：
    codex/AGENTS.md.j2 → amp / jules / opencode 共用
```
