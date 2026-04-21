# AhaDiff v0.1 修复闭合 Canonical Checklist（29 项）

> 生成时间：2026-04-21（Round 8 终极审查产出）
> 用途：所有 GO 判定对此清单而非 changelog 叙述。每项需确认已落地文档 + 目标 Task + 验收标准

---

## Critical（Task 0 前/期间修复）— 4 项

| ID | 来源 | 问题 | 已落地文档 | 目标 Task | 验收标准 | 状态 |
|----|------|------|-----------|----------|---------|------|
| FIX-01 | Gemini R7 | i18n/Theme 切换导致 DiffView 全量 re-render | stages-4-9.md Task 13 step 6/14 | Task 13 | React DevTools Profiler 验证语言切换不触发 DiffView re-render | ✅ 已下沉 |
| FIX-02 | Gemini R7 | 移动端 Diff-Claim 双向联动被 Drawer 遮挡 | stages-4-9.md Task 14 step 3 | Task 14 | 375px 视口 Mini-Panel 弹出且 Diff 可滚动 | ✅ 已下沉 |
| FIX-03 | Round 7 | eval_bundle_hash 算法未冻结 | kickoff.md Task 0 step 4 | Task 0 | SHA-256 sorted byte concat 伪代码可执行 | ✅ 已下沉 |
| FIX-04 | Round 7 | improve 状态机 keep/targeted_verify 混用 | stages-4-9.md Task 12 step 7 | Task 12 | keep=仅 learn, targeted_verify→keep_final=仅 improve | ✅ 已下沉 |

## High（对应 Task 启动前修复）— 8 项

| ID | 来源 | 问题 | 已落地文档 | 目标 Task | 验收标准 | 状态 |
|----|------|------|-----------|----------|---------|------|
| FIX-05 | Round 7 | Layer 6 Task 14.5 同层依赖 Task 15 | stages-4-9.md 并行分组 Layer 6a/6b | Task 14.5 | DAG 标注 6b 串行 | ✅ 已下沉 |
| FIX-06 | Round 7 | cherry-pick→status 写入顺序未冻结 | stages-4-9.md Task 12 step 7 | Task 12 | 禁止先写 status 再 cherry-pick | ✅ 已下沉 |
| FIX-07 | Round 7 | crash-atomicity: concepts/audit write-to-temp-then-rename | stages-4-9.md Task 10 step 9, kickoff.md Task 7 step 12 | Task 10/7 | write-to-temp-then-rename 伪代码存在 | ✅ 已下沉 |
| FIX-08 | Round 7 | 前端 Zustand 原子 i18n store 约束 | stages-4-9.md Task 13 step 6 | Task 13 | Zustand store 而非 Context | ✅ 已下沉 |
| FIX-09 | Round 7 | 防 FOUC head JS | stages-4-9.md Task 13 step 8 | Task 13 | < 500 bytes 阻塞脚本 | ✅ 已下沉 |
| FIX-10 | Round 7 | token 估算 per-adapter | kickoff.md Task 7 step 15 | Task 7 | tiktoken/len÷4/×1.1 策略表存在 | ✅ 已下沉 |
| FIX-11 | Round 7 | 撤架命名统一 full\|hint\|compact | stages-4-9.md Task 9 step 8 + Task 14 step 2 | Task 9/14 | 枚举为 full\|hint\|compact | ✅ 已下沉 |
| FIX-12 | Round 7 | Stage 4 纳入 Task 15, Stage 5 纳入 Task 14.5 | CLAUDE.md Stage 划分表 | — | 表格与 DAG 一致 | ✅ 已下沉 |

## Medium（各 Task 启动前修复）— 12 项

| ID | 来源 | 问题 | 已落地文档 | 目标 Task | 状态 |
|----|------|------|-----------|----------|------|
| FIX-13 | Round 6 | 大 diff deterministic ranking（CC-R6-1） | — | Task 5 | ⚠️ **未下沉** |
| FIX-14 | Round 6 | improve Ctrl+C 恢复（CC-R6-2） | — | Task 16 | ⚠️ **未下沉** |
| FIX-15 | Round 6 | VCR cassette key 含 api_family+version（CC-R6-4） | — | Task 18 | ⚠️ **未下沉** |
| FIX-16 | Round 6 | 多进程 serve 读 half-written artifact（CC-R6-5） | — | Task 14.5 | ⚠️ **未下沉** |
| FIX-17 | Codex R8 | SQLITE_DBCONFIG_DEFENSIVE | — | Task 0 | ⚠️ **未下沉** |
| FIX-18 | Codex R8 | Windows cancel token | — | Task 7 | ⚠️ **未下沉** |
| FIX-19 | Round 7 | concepts.jsonl 并发写入 serve+learn | stages-4-9.md Task 10 step 9 | Task 10 | ✅ repo_write_lock 保护 |
| FIX-20 | Round 7 | Windows 长路径 + Chinese 路径名预检 | kickoff.md Task 1 step 7 | Task 1 | ✅ 网络路径检测 |
| FIX-21 | Round 5 | locale BCP47 归一化（CC-NEW-1） | corner-cases-closure-8.md | Task i18n-0 | ✅ 闭合方案含代码 |
| FIX-22 | Round 5 | 混合语言检测+重试（CC-NEW-2） | corner-cases-closure-8.md | Task i18n-2 | ✅ 闭合方案含代码 |
| FIX-23 | Round 5 | evidence anchor file_id 分离（CC-NEW-3） | corner-cases-closure-8.md | Task i18n-0 | ✅ 闭合方案含代码 |
| FIX-24 | Round 5 | idempotency_key 幂等（CC-NEW-4） | corner-cases-closure-8.md | Task 14.5 | ✅ 闭合方案含代码 |

## Low（实施时处理）— 5 项

| ID | 来源 | 问题 | 已落地文档 | 目标 Task | 状态 |
|----|------|------|-----------|----------|------|
| FIX-25 | Round 5 | 概念 term_key 去重（CC-NEW-5） | stages-4-9.md Task 10 step 8 | Task 10 | ✅ 已下沉 |
| FIX-26 | Round 5 | archive bomb DoS（CC-NEW-6） | corner-cases-closure-8.md | Task 2 | ✅ 闭合方案 |
| FIX-27 | Round 5 | SSR/API 语言不一致（CC-NEW-7） | corner-cases-closure-8.md | Task 14.5 | ✅ 闭合方案 |
| FIX-28 | Round 4 | CC-GAP-2 网络中断需 Task 7 处理 | kickoff.md Task 7 step 10 | Task 7 | ✅ 异常处理表 |
| FIX-29 | Codex R8 | macOS case-insensitive file_id collision | — | Task 6 | ⚠️ **未下沉** |

---

## 统计

| 状态 | 数量 |
|------|------|
| ✅ 已下沉到 Task | 22 |
| ⚠️ 未下沉（需补入） | **7** |
| 总计 | 29 |

## 7 项未下沉修复的目标 Task 分配

| ID | 问题 | 补入 Task | 补入位置 |
|----|------|----------|---------|
| FIX-13 | 大 diff deterministic ranking | Task 5 step 5 | `degraded_flags` 策略后新增确定性排序 |
| FIX-14 | improve Ctrl+C two-phase finalization | Task 16 step 7 | improve 隔离策略补充 |
| FIX-15 | VCR key 含 api_family_version | Task 18 VCR 管理 | cassette 级四元组扩展为五元组 |
| FIX-16 | serve 读 half-written artifact finalized marker | Task 14.5 step 1 后 | 新增 run finalize 协议 |
| FIX-17 | SQLITE_DBCONFIG_DEFENSIVE | Task 0 step 20 | 统一连接初始化补充 |
| FIX-18 | Windows cancel token | Task 7 step 10 | 异常处理决策表补充 |
| FIX-29 | macOS case-insensitive file_id collision | Task 6 step 4 | symbol extraction 补充 |
