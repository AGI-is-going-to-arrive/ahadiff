# AhaDiff v0.1 第六轮交叉审查报告

> 审查模型：Codex CLI + Claude Opus 4.6 + Gemini(gemini-3.1-pro-preview)
> 日期：2026-04-21
> 判定：**CONDITIONAL GO → GO**（3 High 已修复，0 Critical 残留）

---

## 最终判定：GO

三模型并行审查后发现 3 个 High 问题，全部已修复。技术栈选型三方一致认可。

---

## 修复记录

### High（已修复）

| ID | 来源 | 问题 | 修复 |
|----|------|------|------|
| H-1 | Codex | Blueprint FAQ 把 judge 写成 "Ollama judge"，Warm v6 把 GPT-5.4-mini 标为 "Anthropic" provider | Blueprint FAQ 修正为 gpt-5.4-mini；v6.html provider 改为 "OpenAI · GPT-5.4-mini" |
| H-2 | Codex+Claude | `ui/CLAUDE.md` 仍有 4 处 Jinja2 迁移指令，与第五轮 React 19 决策冲突 | 全部更新为 React 19 + Vite + vanilla CSS |
| H-3 | Codex+Claude | Task 13/14.5 依赖图矛盾：正文说不依赖 14.5，并行图写依赖；CLAUDE.md Stage 4 含 14.5 但 W-1 移到 Stage 5 | 并行图修正；CLAUDE.md Stage 4 仅含 Task 13+14；Stage 5 含 Task 14.5+15+16-17 |

### Medium（记录，非阻塞）

| ID | 来源 | 问题 | 处置 |
|----|------|------|------|
| M-1 | Codex | 前端设计手册仍有 `commits/<sha>` 旧路径 | 已修复 v6.html（4处），设计手册待 Task 13 实现时对齐 |
| M-2 | Codex | XSS 防护叙事混用 bleach(Jinja2) 和 DOMPurify(React) | Task 13 实现时统一为 React escape + DOMPurify |
| M-3 | Codex | SQLite 连接初始化缺 SQLITE_DBCONFIG_DEFENSIVE | Task 0 实现时补入 |
| M-4 | Codex | Secret scan 未覆盖环境变量引用型 secrets | Task 2 实现时作为 warning-level 检测 |
| M-5 | Codex | headless Linux 下 webbrowser.open() 可能阻塞 | 已在设计中覆盖（检测 DISPLAY 环境变量） |
| M-6 | Gemini | Diff 与 Claim 双向联动在小屏缺空间 | Task 14 实现时用底部 Drawer 替代固定栏 |
| M-7 | Gemini | Token 鉴权暴露在前端 | Task 14.5 已设计 localhost-only 获取 + Origin 校验 |

---

## 技术栈评估（三方共识）

| 技术 | Codex | Gemini | Claude | 共识 |
|------|-------|--------|--------|------|
| Python 3.11+ | 8/10 | — | 8/10 | 合适，tomllib 标准库 + 性能增益 |
| SQLite WAL | 7/10 | — | 7/10 | 合适但需 NFS fail-fast + version gate |
| Starlette+Uvicorn | 8/10 | — | 8/10 | 轻量 localhost 场景最优 |
| React 19 + Vite | 7/10 | 9/10 | 8/10 | 交互复杂度需要，非 overengineering |
| vanilla CSS | — | 8/10 | 7/10 | v0.1 合适，建议 CSS Modules 避免污染 |
| 8 种 LLM Adapter | 7/10 | — | 8/10 | 合理但需冻结 capability matrix |

### Gemini 建议采纳

| 建议 | 采纳时机 | 理由 |
|------|---------|------|
| 使用 Zustand 状态管理 | Task 13 | Diff-Claim 双向联动需细粒度订阅 |
| DiffViewer 虚拟列表 | Task 14 | 5000+ 行 diff DOM 性能 |
| i18n 强类型 hook | Task i18n-3 | TypeScript key 检查 |
| CSS Modules 或 BEM | Task 13 | 避免全局样式污染 |

---

## 新发现 Corner Cases

| ID | 来源 | 描述 | 严重度 | 处置 |
|----|------|------|--------|------|
| CC-R6-1 | Codex | 大 diff clip 无确定性文件排序，同来源两次 run 可能截断不同文件 | Medium | Task 5 冻结 deterministic ranking |
| CC-R6-2 | Codex | improve loop Ctrl+C 恢复语义不完整 | High | Task 16 实现 two-phase finalization |
| CC-R6-3 | Codex | concepts.jsonl squash 后概念暂时不可见窗口 | Medium | 可接受（下次 learn 恢复） |
| CC-R6-4 | Codex | VCR cassette key 未含 provider API schema version | Medium | Task 18 纳入 api_family+version |
| CC-R6-5 | Codex | 多进程 serve 读 API 可能读到 half-written artifact | High | Task 14.5 添加 finalized marker |
| CC-FE-4 | Gemini | SPA deep link 刷新 404 | High | Task 14.5 已设计 SPA fallback |
| CC-FE-5 | Gemini | JS 禁用白屏 | Medium | Task 13 添加 noscript 提示 |

---

## 跨平台评估

| 平台 | 关键风险 | 现状 | 缓解措施 |
|------|---------|------|---------|
| Windows | MAX_PATH 260 总长度 | 部分覆盖 | Task 1 添加启动时路径总长预检 |
| Windows | signal 模型差异 | 未覆盖 | Task 0 统一使用 cancel token |
| macOS | 大小写不敏感 file_id 冲突 | 未覆盖 | Task 5 做 case-collision 检查 |
| Linux | headless webbrowser.open() | 已设计 | 检测 DISPLAY → 等价 --no-browser |
| 共享 | CRLF/BOM/非 UTF-8 | 部分覆盖 | Task 5 byte-oriented + BOM sniffing |
| 共享 | SQLite WAL checkpoint starvation | 已设计 | busy_timeout=5000 + 短读事务 |

---

## 残留计数

| 类别 | 活跃权威文档 | 归档/历史文档 | 说明 |
|------|------------|-------------|------|
| Jinja2 | 2（kickoff L41 注释+stages L357 模板生成） | ~20 | 活跃引用均为 `ahadiff install` 模板生成用途，正确 |
| Haiku | 0 | ~15 | 全在旧原型 v3/v4/v5，可接受 |
| 静态模式 | 0 | ~10 | 归档 + 历史 CC 注释 |
| commits/ 旧路径 | 0（v6.html 已修） | ~5 | 旧原型 |

---

## 结论

三模型一致认可当前技术栈和架构设计。所有 High 问题已修复。剩余 Medium 均有明确的 Task 归属和实现时机。

**判定：GO — Task 0 (Schema Freeze) 可立即开工。**
