# Task 16 — Improve Loop: 全方位交叉审查报告

> 日期：2026-04-24
> 审查模型：Claude Opus 4.6（总编排 + 3 独立审查）+ Codex CLI（3 独立审查）
> 审查范围：当前 working tree 未提交改动（Stage 5 / Task 16）
> 方法：两轮交叉审查（Round 1: 8 路并行；Round 2: 4 路并行验证+遗漏搜索）

---

## 1. 审查范围

| 类型 | 文件 | 变更量 |
|------|------|--------|
| Modified | `src/ahadiff/cli.py` | +130 行 |
| Modified | `src/ahadiff/eval/results.py` | +10 行 |
| Modified | `CLAUDE.md` / `README.md` / `README.en.md` | 文档同步 |
| New | `src/ahadiff/improve/{__init__,loop,program}.py` | 核心 improve loop |
| New | `prompts/improve_program.md` + `src/ahadiff/prompts/improve_program.md` | improve 状态机 prompt |
| New | `tests/unit/test_improve_loop.py` | 初审时 4 个测试用例；修复后 14 个见第 9 节 |

---

## 2. Findings（按严重级别排序）

### High — 必须修复

**H-1. `lesson_hint.md` 不在代码白名单中**
- 位置：`src/ahadiff/improve/program.py:16-25`
- 描述：`_MUTABLE_PROMPT_BY_DIMENSION` 只映射 4 个文件（`claim_extract.md`, `quiz_generate.md`, `lesson_generate.md`, `lesson_compact.md`），但 `contract-freeze.md:178`、`CLAUDE.md:180`、`prompts/improve_program.md` 三处文档均声明可写 prompt 为 5 个（含 `lesson_hint.md`）
- 影响：`validate_mutable_prompt_name("lesson_hint.md")` 会抛 `InputError`，improve loop 无法改写 `lesson_hint.md`
- 触发条件：任何维度试图映射到 `lesson_hint.md` 时
- 来源：Claude Round 1 + Codex Round 1 adversarial + Claude Round 2 contract audit + Codex Round 2 verify — **四方一致 CONFIRMED**
- 修复建议：在 `_MUTABLE_PROMPT_BY_DIMENSION` 中增加映射（或在文档中收窄为 4 个）

**H-2. `session_id` 路径穿越漏洞**
- 位置：`src/ahadiff/improve/program.py:72-73`
- 描述：`improve_session_file(state_dir, session_id)` 直接拼接 `session_id` 到路径，无路径分隔符或 `..` 校验。`--resume "../../etc/passwd"` 可逃逸 state_dir 读取任意 JSON 文件
- 影响：读取 state_dir 外部任意 JSON → 如果解析成功，`worktree_path` 字段可用于后续 `shutil.rmtree` 删除任意目录
- 触发条件：`ahadiff improve --resume "../../<path>"`
- 来源：Codex Round 1 adversarial (ADV-003/004) + Codex Round 2 verify — **CONFIRMED（实测验证）**
- 修复建议：在 `improve_session_file()` 中校验 `session_id` 不含 `/`、`\`、`..`，或使用 `resolve()` 后检查父级

**H-3. `_run_replay_learn_subprocess` 无 `timeout` 参数**
- 位置：`src/ahadiff/improve/loop.py:528`
- 描述：`subprocess.run()` 无 `timeout=`，如果 LLM endpoint 不响应或子进程挂起，improve loop 无限阻塞
- 影响：进程永久挂起，持有 `repo_write_lock`，阻止同 repo 所有其他 ahadiff 命令
- 触发条件：LLM endpoint 不响应、网络断开、子进程死锁
- 来源：Claude Round 1 主线 + Codex Round 2 find-missed — **两方一致 CONFIRMED**
- 修复建议：添加合理 `timeout`（如 1800s/30min），超时后杀子进程并清理 worktree

### Medium — 建议修复

**M-1. 中断时 double `append_result` 产生同一 run 两条 event**
- 位置：`src/ahadiff/improve/loop.py:238` + `loop.py:291`
- 描述：L238 写 `targeted_verify`/`discard`，L291 在 `interrupt.requested` 时再写 `crash`。两次调用生成不同 `event_id`，均成功插入 DB
- 影响：同一 run_id 出现两条 event（如 `targeted_verify` + `crash`），`finalized.json` 被第二次调用覆盖为 crash 状态
- 触发条件：用户在 round 完成后、下一 round 开始前按 Ctrl+C
- 来源：Claude Round 1 + Codex Round 1 adversarial + Codex Round 2 verify — **三方 CONFIRMED**
- 修复建议：在 L290 的 interrupt 检查中，若本 round 已完成 append_result，直接 break 不再写 crash event

**M-2. Discarded run 被写入 `finalized.json`**
- 位置：`src/ahadiff/improve/loop.py:238`（`append_result` 默认 `write_finalized=True`）
- 描述：即使 `status="discard"`，`finalized.json` 也会被写入 imported_run_path
- 影响：设计瑕疵。`_select_anchor_event` 通过 `_BASELINE_STATUSES` 过滤 `discard`，不会选为 anchor。但多余的 finalized 标记可能误导人类检查
- 触发条件：每次 discard 路径
- 来源：Claude Round 1 deep review + Codex Round 2 verify — **CONFIRMED，但降级为 Low 实际影响**
- 修复建议：`status == "discard"` 时传 `write_finalized=False`

**M-3. 非 atomic 双文件写入**
- 位置：`src/ahadiff/improve/loop.py:465-466`
- 描述：`_mutate_prompt_in_worktree` 先写 `prompts/<name>` 再写 `src/ahadiff/prompts/<name>`，如果进程在两次写入之间崩溃，worktree 内两处 prompt 不一致
- 影响：不一致的 worktree prompt → `git commit` 提交不一致状态 → cherry-pick 后主分支也不一致
- 触发条件：进程在 L465 和 L466 之间被 SIGKILL
- 来源：Claude Round 2 line audit (F3) — **新发现**
- 修复建议：先写两个 temp 文件，再做两次 replace

**M-4. `_cherry_pick_prompt_commit` 无法区分冲突和非冲突失败**
- 位置：`src/ahadiff/improve/loop.py:571-589`
- 描述：cherry-pick 返回非零时一律当作冲突处理，包括 invalid SHA、empty commit 等非冲突失败。`cherry-pick --abort` 在非冲突场景下也会失败（但被 `check=False` 吞掉）
- 影响：非冲突失败被报告为 "pending conflict"，用户收到错误引导
- 触发条件：git cherry-pick 因非冲突原因失败（如 empty commit）
- 来源：Claude Round 2 line audit (F6) — **新发现，实测确认 `cherry-pick --abort` 在无 cherry-pick 状态时返回 128**

**M-5. 子进程事件写入独立 review.sqlite（worktree 内），不可见于主 DB**
- 位置：`src/ahadiff/improve/loop.py:522` + `src/ahadiff/eval/results.py:175-176`
- 描述：子进程 `ahadiff learn` 在 worktree 的 `.ahadiff/review.sqlite` 中写入 learn event。主 loop 在 `_copy_candidate_run_to_state` 后重新评估并写入主 DB，所以主 DB 有正确的 improve event。但 worktree 中的 learn event 成为孤儿
- 影响：不影响正确性（主 loop 会独立评估和写入），但 worktree 中的 review.sqlite 是多余的孤儿数据
- 触发条件：每次 improve round
- 来源：Codex Round 2 find-missed (1b) — **新发现，验证确认不影响正确性但是资源浪费**

**M-6. `git worktree remove --force` 失败后 `shutil.rmtree` 导致 git worktree 注册表脏**
- 位置：`src/ahadiff/improve/loop.py:371-376`
- 描述：如果 `git worktree remove --force` 失败但 `shutil.rmtree` 成功，`.git/worktrees/<name>/` 仍有注册记录但对应目录已删除
- 影响：`git worktree list` 显示幽灵条目。多次累积可能阻止同名 worktree 重新创建
- 触发条件：并发 git 操作持有 `.git/` 锁、或 git worktree remove 因其他原因失败
- 来源：Codex Round 2 find-missed — **新发现**
- 修复建议：rmtree 之后调用 `git worktree prune`

### Low

**L-1. 测试覆盖不足**
- 位置：`tests/unit/test_improve_loop.py`（仅 4 个测试）
- 缺失场景：crash recovery / resume、invalid session JSON、multi-round (rounds > 1)、`_InterruptController`、worktree 创建失败、cherry-pick 真实冲突（非 monkeypatch）、LLM 返回无效 JSON、子进程超时
- 来源：Codex Round 2 find-missed — **CONFIRMED**

**L-2. `--rounds` 无上限限制**
- 位置：`src/ahadiff/cli.py:1243`
- 描述：`min=1` 但无 max，`--rounds 999999` 理论上可行
- 来源：Codex Round 1 adversarial + Round 2 verify — **CONFIRMED，Low 实际影响**

**L-3. `_InterruptController` 在非主线程崩溃**
- 位置：`src/ahadiff/improve/loop.py:89`
- 描述：`signal.signal()` 只能在主线程调用。当前所有调用路径均在主线程，但未来 API server 场景需注意
- 来源：Codex Round 1 adversarial + Claude Round 2 line audit

**L-4. Windows `shutil.rmtree` / `shutil.copytree` 文件锁干扰**
- 位置：`loop.py:376`, `loop.py:565`
- 描述：Windows 上文件被其他进程（杀毒、git index.lock）持有时静默失败或异常
- 来源：跨平台审计

**L-5. Windows MAX_PATH 超限**
- 位置：`loop.py:361`
- 描述：worktree 路径含 UUID，深层嵌套 repo 可能超 260 字符
- 来源：跨平台审计 + Codex Round 1 adversarial

**L-6. LLM response content 未过滤 null 字节**
- 位置：`loop.py:462`
- 描述：`normalized_content = content.rstrip() + "\n"` 不过滤 `\x00`
- 来源：Claude Round 1 主线 + Codex Round 2 find-missed

**L-7. `__init__.py` `__all__` 缺少 2 个已导入符号**
- 位置：`src/ahadiff/improve/__init__.py`
- 描述：`update_improve_session` 和 `validate_mutable_prompt_name` 被 import 但不在 `__all__` 中
- 来源：Claude Round 2 contract audit

### Info

**I-1. `_InterruptController._requested` GIL-free 可见性**
- 位置：`loop.py:97-98`
- 描述：读 `_requested` 未加锁。CPython GIL 保护下安全，future no-GIL 可能有问题
- 来源：Claude Round 2 line audit

**I-2. `phase25_attempted` 字段存在但未使用**
- 描述：`ImproveSessionState.phase25_attempted` 已预留但 `run_improve_loop` 从未读写。CLAUDE.md 已注明 Phase 2.5 延期到 Task 17
- 来源：Claude Round 2 contract audit

---

## 3. 上轮发现验证结果

| 上轮 ID | Round 2 裁决 | 说明 |
|---------|-------------|------|
| H-1 lesson_hint | **CONFIRMED** | 四方一致 |
| H-2 session_id traversal | **CONFIRMED** | 实测确认 |
| H-3→M keep_final | **FALSE POSITIVE** | Task 17 范围，非 Task 16 |
| M-1 double append | **CONFIRMED** | 三方一致 |
| M-3→M-2 finalized on discard | **CONFIRMED** but **降级 Low** | `_BASELINE_STATUSES` 过滤 discard |
| M-4 worktree orphan | **NEEDS NUANCE** | 不自动清理但 resume 会检测 |
| M-5 rounds cap | **CONFIRMED Low** | 合理 |
| ADV-002 prompt pollution | **FALSE POSITIVE（维持）** | learn 不写 src/ahadiff/prompts/ |
| ADV-006 TOCTOU | **FALSE POSITIVE（维持）** | repo_write_lock 保护 |
| ADV-010 cards.jsonl | **FALSE POSITIVE（维持）** | evaluator 不读 cards.jsonl |
| ADV-011 cherry-pick TOCTOU | **FALSE POSITIVE（维持）** | repo_write_lock 保护 |

---

## 4. 交叉审查裁决

### 来源覆盖矩阵

| Finding | Claude R1 | Codex R1 Adv | Claude R2 Line | Claude R2 Contract | Codex R2 Verify | Codex R2 Missed |
|---------|-----------|--------------|----------------|--------------------|-----------------|-----------------|
| H-1 | ✓ | ✓ | — | ✓ | ✓ | — |
| H-2 | — | ✓ | — | — | ✓ | — |
| H-3 | ✓ | — | — | — | — | ✓ |
| M-1 | ✓ | ✓ | ✓dup | — | ✓ | — |
| M-2 | ✓ | — | — | — | ✓ | — |
| M-3 | — | — | ✓ | — | — | — |
| M-4 | — | — | ✓ | — | — | — |
| M-5 | — | — | — | — | — | ✓ |
| M-6 | — | — | — | — | — | ✓ |
| L-1 | — | — | — | — | — | ✓ |

### 误报清洗

| 被标记为问题 | 最终裁决 | 原因 |
|-------------|---------|------|
| ADV-002 prompt pollution | **FALSE POSITIVE** | learn 不写 src/ahadiff/prompts/；白名单保护 |
| ADV-005 keep_final | **FALSE POSITIVE** | Task 17 范围 |
| ADV-006 TOCTOU | **FALSE POSITIVE** | repo_write_lock 保护整个序列 |
| ADV-010 cards.jsonl | **FALSE POSITIVE** | evaluator.py 不读 cards.jsonl |
| ADV-011 cherry-pick TOCTOU | **FALSE POSITIVE** | 锁保护 |
| F5 directory replace | **FALSE POSITIVE** | destination 不存在时 replace 正常工作（实测） |
| F4 argv injection | **降级 Info** | list mode + positional binding 无注入风险 |

---

## 5. Tests Run

以下为初审时的实测结果；修复后的结果见第 9 节。

| 命令 | 结果 | 方式 |
|------|------|------|
| `pytest tests/unit/test_improve_loop.py tests/unit/test_results.py tests/unit/test_review.py -q` | **46 passed** | macOS live |
| `pytest tests/unit -q` | **387 passed** | macOS live |
| `ruff format --check src tests` | **109 files already formatted** | macOS live |
| `ruff check src tests` | **All checks passed** | macOS live |
| `pyright` | **0 errors, 0 warnings** | macOS live |
| `uv build --wheel` | **Successfully built** | macOS live |
| `python -m ahadiff improve --help` | **正常输出** | macOS live |
| `prompt_version worktree test` | **Hash 随 worktree 变更** | macOS live |
| `session_id path traversal test` | **逃逸确认** | macOS live |
| `cherry-pick invalid SHA test` | **abort 返回 128** | macOS live |

---

## 6. Cross-Platform Audit

### macOS（live verified）
- 全部测试通过，CLI 可用，wheel 构建成功
- signal/pathlib/subprocess/atomic-rename 均正常

### Linux（static audit only）
- 0 WILL BREAK，0 MAY BREAK
- `start_new_session=True` 行为与 macOS 一致

### Windows（static audit only）
- 0 WILL BREAK
- 4 MAY BREAK：SIGINT 可靠性（非 console）、`shutil.rmtree` 文件锁、MAX_PATH 超限、`shutil.copytree` 文件锁
- `_detached_subprocess_kwargs()` 的 `CREATE_NEW_PROCESS_GROUP` 处理正确

---

## 7. 契约一致性审计

| 检查项 | 结果 |
|--------|------|
| A. 可写 prompt 白名单（5 vs 4） | **MISMATCH** → H-1 |
| B. `improve_program.md` immutability | MATCH |
| C. cherry-pick/worktree 行为 | MATCH |
| D. Phase 2.5 触发逻辑 | MATCH（已注明延期） |
| E. `phase25_attempted` 使用 | MATCH（预留字段，Task 17） |
| F. git worktree 隔离 | MATCH |
| G. event_type/status 契约 | MATCH |
| H. README 描述准确性 | MATCH |
| I. CLAUDE.md changelog | MATCH |
| J. `__all__` exports vs 使用 | **MISMATCH** → L-7 |

---

## 8. Final Recommendation

### **CONDITIONAL GO**

**必须在合并前修复（3 High）：**
1. **H-1**：`lesson_hint.md` 白名单对齐（代码或文档择一修正）
2. **H-2**：`session_id` 路径穿越校验
3. **H-3**：`subprocess.run` 添加 `timeout` 参数

**建议修复（6 Medium，不阻塞合并）：**
1. M-1：interrupt 后不再 double append
2. M-2：discard 时 `write_finalized=False`
3. M-3：dual prompt write 改为 temp+replace
4. M-4：cherry-pick 失败类型区分
5. M-5：worktree DB 孤儿 / `git worktree prune`
6. M-6：git worktree 注册表脏检测

**后续 Task 17+ 处理（7 Low + 2 Info）：**
- 测试覆盖扩充（crash recovery、multi-round、interrupt）
- rounds 上限
- null 字节过滤
- Windows 兼容性加固
- `__all__` 补齐
- GIL-free 可见性
- `phase25_attempted` 接入

---

## 9. Post-fix Addendum（本次 Codex 修复后）

> 说明：上面的 Findings 保留初审原文；本节只记录修复后的当前真值。

### 已修复或已收口

- H-1 已修复：`lesson_hint.md` 已进入 5 个 mutable prompt 白名单，`prompts/improve_program.md` 仍保持 immutable，不属于可写面
- H-2 已修复：`session_id` 现在只允许简单文件名，拒绝空值、`.`、`..`、前导点和路径穿越；session 文件名与 payload 中的 `session_id` 都会校验
- H-3 已修复：replay subprocess 现在有 30 分钟 timeout，超时会转成 `InputError`
- M-1 已修复：已完成 round 后收到 interrupt 只停止后续 round，不再追加第二条 crash event
- M-2 已修复：`discard` 不写 `finalized.json`；pending conflict 也不写 `finalized.json`
- M-3 已修复：两个 prompt 副本改为 temp + replace 写入
- M-4 已修复：cherry-pick 非冲突失败会抛 `InputError`，不再伪装成 pending conflict
- M-6 已修复：worktree fallback 清理后会执行 `git worktree prune`
- L-2 已修复：`ahadiff improve --rounds` 限制为 1..20
- L-3 已修复：非主线程安装 interrupt handler 时 no-op
- L-6 已修复：LLM 返回内容含 null byte 时拒绝写入
- 额外补强：volatile `git_staged` / `git_unstaged` / `git_staged_unstaged` replay 改为使用保存的 `patch.diff`，避免 clean worktree 下重放成空 diff
- 额外补强：pending conflict run 不写 finalized，也不会作为下一轮 improve baseline；resume 时遇到 pending worktree 会先拒绝继续
- 额外补强：worktree 路径改为 `.ahadiff/improve/wt/<12hex>-rN`，降低深路径超长风险

### 仍属于后续范围

- Task 17 的自动 targeted verification、`keep_final` 决策和 Phase 2.5 rewrite runtime 仍未实现；当前已有的是 Task 16 写 `targeted_verify` event，以及 Task 15 提供的手动 `db finalize-targeted` 入口
- Windows 文件锁 / MAX_PATH 仍主要是静态审计风险，本轮未做真实 Windows 运行验证
- `phase25_attempted` 仍是 session 字段预留，Task 17 接入

### 修复后实测

| 命令 | 结果 | 方式 |
|------|------|------|
| `pytest tests/unit/test_improve_loop.py -q` | **14 passed** | macOS live |
| `pytest tests/unit/test_improve_loop.py tests/unit/test_results.py tests/unit/test_review.py -q` | **56 passed** | macOS live |
| `pytest tests/unit -q` | **397 passed** | macOS live |
| `ruff format --check src tests` | **109 files already formatted** | macOS live |
| `ruff check src tests` | **All checks passed** | macOS live |
| `pyright` | **0 errors, 0 warnings** | macOS live |
| `uv build --wheel` | **Successfully built** | macOS live |
| `python -m ahadiff improve --help` | **正常输出，`--rounds` 显示 1..20** | macOS live |

---

## 附录：审查来源

| ID | 角色 | 类型 | 关键发现数 |
|----|------|------|-----------|
| Claude R1 主线 | 编排+独立审查 | 手动精读 | 5 |
| Claude R1 深度审查 | 独立 agent | 后台并行 | 8 |
| Claude R1 跨平台审计 | 独立 agent | 后台并行 | 4 MAY BREAK |
| Codex R1 对抗审查 | Codex agent | 后台并行 | 14 |
| Codex R2 验证 | Codex agent | 后台并行 | 11 项验证 |
| Codex R2 遗漏搜索 | Codex agent | 后台并行 | 8 新发现 |
| Claude R2 逐行审计 | 独立 agent | 后台并行 | 9 新发现 |
| Claude R2 契约审计 | 独立 agent | 后台并行 | 3 MISMATCH |

误报率：7/33 = 21%（经交叉验证清除）
