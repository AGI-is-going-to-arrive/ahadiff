# Task 15 Cross-Review Report — review.sqlite + FSRS-6 + Review CLI

> 生成时间: 2026-04-24
> 审查轮次: R1 + R2 (两轮全方位对抗性交叉审查)
> 审查模型: Claude Opus 4.6 (主线 + 5 Claude 子代理) + Codex CLI (2 Codex 子代理)
> 目标范围: Stage 4 / Task 15 后端，不含前端/serve/improve runtime

## 0. 改动范围

### 已修改文件 (tracked)

| 文件 | 变更 |
|------|------|
| `pyproject.toml` | +1 行 (添加 `fsrs>=6.3.1,<7` 依赖) |
| `src/ahadiff/cli.py` | +428/-0 行 (新增 review/mark/db/regenerate CLI 命令) |
| `src/ahadiff/eval/results.py` | +6/-213 行 (SQLite 操作收口到 review/database.py) |
| `uv.lock` | +14 行 (fsrs 依赖锁) |

### 新增文件 (untracked)

| 文件 | 行数 | 职责 |
|------|------|------|
| `src/ahadiff/review/__init__.py` | 75 | 模块公开 API |
| `src/ahadiff/review/database.py` | 1115 | review.sqlite schema/migration/CRUD |
| `src/ahadiff/review/scheduler.py` | 202 | FSRS-6 调度算法 |
| `src/ahadiff/review/schemas.py` | 49 | DTO (ReviewAnswer/DueReviewCard/ReviewUpdate/ReviewDbCheck) |
| `src/ahadiff/review/signal.py` | 43 | mark_claim_wrong 学习信号 |
| `tests/unit/test_review.py` | 639 | 16 个单元测试 |

## 1. 审查矩阵

### R1 (第一轮)

| 代理 | 类型 | 维度 | C | H | M | L |
|------|------|------|---|---|---|---|
| Claude Schema Reviewer | Claude 子代理 | Schema/Migration/FSRS/CLI/Results 30+ 检查点 | 0 | 1 | 1 | 4 |
| Codex Standard Review | Codex 插件 | 正确性/迁移/安全/类型 | 0 | 3 | 4 | 4 |
| Codex Adversarial Review | Codex 插件 | 12 个攻击面 | (派发到后台) | - | - | - |
| Claude 主线审查 | 主线 | 独立逐行审查 | 0 | 0 | 2 | 2 |

### R2 (第二轮对抗性)

| 代理 | 类型 | 维度 | C | H | M | L |
|------|------|------|---|---|---|---|
| Codex SQLite Attack | Codex 插件 | 7 个 SQLite 攻击场景 | 0 | 0 | 2 | 2 |
| Codex FSRS State Attack | Codex 插件 | 7 个 FSRS 状态机攻击 | 0 | 0 | 3 | 0 |
| Claude CLI Integration | Claude 子代理 | CLI + 跨模块 + R1 fact-check | 0 | 2 | 2 | 0 |
| Claude Contract Drift | Claude 子代理 | 7 维合规矩阵 | 0 | 0 | 2 | 1 |
| Claude SQL Param Count | Claude 子代理 | 17 条 SQL 机械验证 | 0 | 0 | 0 | 0 |
| Claude Runtime Path | 主线独立 | 17 运行时路径执行 | 0 | 0 | 0 | 0 |
| Claude R1 Fix Verify | 主线独立 | 3 项 R1 修复回归检查 | 0 | 0 | 0 | 0 |

## 2. 已修复 Findings (R1 + R2 共 9 项)

### R1 修复 (4 项)

#### R1-H1 [High] cards DDL 缺少 stale_reason 列

- **文件**: `src/ahadiff/review/database.py:740`
- **发现来源**: Claude Schema Reviewer + Codex Standard
- **描述**: contract-freeze 3.4 要求 `stale_reason` 作为 ReviewCard 最小字段，但 `_ensure_cards_schema` 的 CREATE TABLE 中缺少此列
- **触发条件**: 尝试将 stale 状态的卡片写入数据库
- **影响**: stale 卡片无法持久化其 stale_reason
- **修复**: 在 cards DDL 添加 `stale_reason TEXT` 列
- **验证**: `PRAGMA table_info(cards)` 确认列存在；安装态 smoke 通过
- **测试覆盖**: test_initialize_review_db_creates_full_schema_and_pragmas 新增 stale_reason 列断言

#### R1-H2 [High] finalize_targeted_verify_event TOCTOU gap

- **文件**: `src/ahadiff/review/database.py:274-337`
- **发现来源**: Codex Standard Review
- **描述**: 函数在两个独立 `connect_review_db()` 连接间执行 SELECT + INSERT，并发进程可在两次连接间修改源事件
- **触发条件**: 两个进程同时调用 finalize_targeted_verify_event（虽然 repo_write_lock 缓解了风险）
- **影响**: 潜在竞态条件，可能导致基于过时数据的 keep_final 事件
- **修复**: 将 INSERT 移入与 SELECT 相同的 `with connect_review_db()` 块内
- **验证**: 运行时原子性测试确认 read+write 在同一连接；R2 CLI Integration 代理交叉确认修复正确

#### R1-H3 [High] regenerate_cmd 使用硬编码路径

- **文件**: `src/ahadiff/cli.py:1072`
- **发现来源**: Codex Standard Review
- **描述**: `run_path.parent.parent / "review.sqlite"` 硬编码了目录层级假设
- **触发条件**: 目录结构与假设不一致时（例如未来重构）
- **影响**: review.sqlite 路径可能错误
- **修复**: 改用 `_state_dir_for_root(root, has_git_repo=has_git_repo) / "review.sqlite"`
- **验证**: 路径等价性数学证明 + R2 代理交叉确认

#### R1-M1 [Medium] import_cards_from_jsonl 始终将 stale_reason 写为 NULL

- **文件**: `src/ahadiff/review/database.py:428`
- **发现来源**: Codex Standard Review
- **描述**: INSERT 语句中 stale_reason 使用 NULL 字面量而非 `card.stale_reason` 参数
- **触发条件**: 导入 stale 状态的 ReviewCard
- **影响**: stale_reason 丢失
- **修复**: 改为参数绑定 `card.stale_reason`
- **验证**: SQL 参数计数 21?/21 params MATCH

### R2 修复 (5 项)

#### R2-H1 [High] 单个损坏 cards.jsonl 崩溃整个 review 命令

- **文件**: `src/ahadiff/review/database.py:436-453`, `src/ahadiff/cli.py:1127`
- **发现来源**: Claude CLI Integration
- **描述**: `import_cards_from_runs` 遍历所有 `runs/*/quiz/cards.jsonl`，任一文件的 JSON 解析失败都会抛出 InputError 终止整个 `ahadiff review` 命令
- **触发条件**: 创建 `.ahadiff/runs/run-bad/quiz/cards.jsonl`，内容为 `{invalid`，然后运行 `ahadiff review`
- **影响**: 用户无法查看/复习任何到期卡片
- **修复**: `import_cards_from_runs` 新增 `on_error: Callable[[Path, Exception], None] | None` 回调参数；CLI 层传入 warning 回调，错误降级为 stderr 警告
- **验证**: 函数签名检查确认 `on_error` 参数存在

#### R2-M1 [Medium] restore_review_db 崩溃窗口

- **文件**: `src/ahadiff/review/database.py:142-148`
- **发现来源**: Codex SQLite Attack
- **描述**: 原代码先 `_remove_sqlite_sidecars(db_path)` 再 `temp_path.replace(db_path)`。如果进程在两步之间崩溃，原始 DB 的 WAL 文件已被删除但 DB 主文件仍在，导致 uncheckpointed 数据丢失
- **触发条件**: `restore_review_db` 执行过程中被 SIGKILL
- **影响**: 潜在数据丢失（WAL 中未 checkpoint 的事务）
- **修复**: 移除 replace 前的 sidecar 删除，仅保留 replace 后的清理。SQLite WAL salt 机制保证旧 sidecar 不会被 replay 到新 DB
- **验证**: 安装态源码检查确认 `restore_review_db` 只有 1 次 `_remove_sqlite_sidecars` 调用

#### R2-M7 [Medium → 实际影响 High] scaffolding 参数传递断裂

- **文件**: `src/ahadiff/review/scheduler.py:72-78,112-118`
- **发现来源**: Codex FSRS State Attack
- **描述**: `review_fsrs_card` 和 `snapshot_card_state` 将 `recent_successes` 作为 dict 键传入 `compute_scaffolding_level` 的 `fsrs_state` 参数，但该函数期望它作为独立的 `recent_successes` keyword 参数。dict 内的值被 `parse_fsrs_state` 解析后丢弃，`recent_successes` 始终使用默认值 0
- **触发条件**: 任何 FSRS 复习或卡片导入
- **影响**: **撤架系统完全失效**：`compute_scaffolding_level` 中 `stability >= 14 and recent_successes >= 2` 永远为 False，卡片永远无法从 hint 进入 compact 级别
- **修复**: 将 `recent_successes` 从 dict 移到独立的 keyword 参数
- **验证**:
  - 修复前: `compute_scaffolding_level(fsrs_state={..., "recent_successes": 2}, recent_successes=0)` → `recent_successes=0` → 永远 hint
  - 修复后: `compute_scaffolding_level(fsrs_state={...}, recent_successes=2)` → compact
  - 运行时测试确认 compact 首次可达

#### R2-M8 [Medium] normalize_fsrs_state 空字符串静默创建新 Card

- **文件**: `src/ahadiff/review/scheduler.py:49-63`
- **发现来源**: Codex FSRS State Attack
- **描述**: Python 中空字符串 `""` 是 falsy，`if fsrs_state:` 判断为 False，走入创建新 Card 分支。这意味着 DB 中的损坏空字符串会被静默重置，而不是报错
- **触发条件**: 数据库中 fsrs_state 列包含空字符串
- **影响**: 调度状态静默重置，复习间隔回到初始值
- **修复**: 在 truthy 检查前显式检测空字符串并 raise InputError
- **验证**: `normalize_fsrs_state("")` 现在 raise `InputError("fsrs_state must not be an empty string; use None for a new card")`

## 3. 原未修复 Findings 状态同步 (2026-04-24 当前真值)

### 已修复 / 已过期同步 (11 项)

| ID | 当前状态 | 说明 |
|----|---------|------|
| R2-H2 | ✅ 已修复 | `tests/unit/test_review.py` + `tests/unit/test_review_scheduler_extra.py` 现已直接覆盖 `rating_for_answer`、`normalize_fsrs_state` 边界、`default_weights_json`、`default_scheduler_parameters`、`snapshot_card_state`、`scheduler_version`，并补齐 `record_card_review` / `set_card_queue_state` / `finalize_targeted_verify_event` 的负路径 |
| R2-M2 | ✅ 已修复 | `make_uuid7()` 改为进程内单调 UUID v7 生成，并由 `database.py` / `results.py` / `signal.py` 统一复用 |
| R2-M3 | ✅ 已修复 | fresh DB 的 `cards` DDL 已补 `card_state CHECK`；existing DB 通过 trigger 拒绝非法状态写入 |
| R2-M4 | ✅ 已修复 | fresh DB 的 `source_ref/file_id/display_path/hunk_id/hunk_hash` 已改为 `NOT NULL`；existing DB 通过 trigger 拒绝 `NULL` 写入 |
| R2-M5 | ✅ 已修复 | `rollback_result_event` 改为在同一 SQLite 连接内完成 `DELETE + SELECT export rows`，消除原始 double-connection TOCTOU |
| R2-M6 | ✅ 已修复 | `regenerate --only quiz` 新增 quiz/cards 回滚保护；`evaluate_run` 失败会恢复旧 artifacts；`FAIL/no-cards` 会删除陈旧 `cards.jsonl` 并将该 run 的 active cards 标记为 `stale + staleness_unknown` |
| R2-M9 | ✅ 已修复 | scheduler 对 py-fsrs 缺失 `stability/difficulty` 改为 fail-fast，不再静默降级成 `0.0` |
| R1-M2 | ✅ 已修复 | `import_results_tsv_lossy` 现在单连接整文件导入；坏行或 duplicate lossy identity 会整批回滚，不再逐行开连接 / partial commit |
| R2-L2 | ✅ 已修复 | `backup_review_db` 对缺失 `review.sqlite` 改为显式报错，不再静默备份空库 |
| R2-L3 | ✅ 已修复 | `connect_review_db()` 不再自动 `mkdir`；仅 `initialize_review_db()` 和 lossy import 这类显式初始化入口允许创建父目录，普通连接在 parent 缺失时直接失败 |
| R1-L3 | ✅ 已修复 | UUID v7 逻辑已从三处重复实现收敛到 `database.py::make_uuid7()` |

### 已由第 10 节 addendum 覆盖，不应再视为未修复 (1 项)

| ID | 当前状态 | 说明 |
|----|---------|------|
| R1-M5 | 🟡 已过期 / 前序已修复 | 已由第 10 节 `R3-H1` 的 schema v2 migration 覆盖：`CURRENT_SCHEMA_VERSION=2` 且旧 `cards` 表会显式 `ALTER TABLE ... ADD COLUMN stale_reason TEXT` |

### 仍未修复 (2 项，均为 Low / 可接受保留)

| ID | 保留原因 |
|----|---------|
| R2-L1 | `cards.id` vs contract `card_id` 属有意 drift；当前 SQL / 代码 /测试全部围绕 `id` 展开，重命名只会扩大迁移面 |
| R1-M3 | `_ensure_schema()` 仍是每连接执行 DDL 的性能债；当前不影响正确性，且缓存/跳过策略需要单独评估连接生命周期与迁移可见性 |

## 4. Debunked Findings (经验证为非 bug)

| 攻击假设 | 验证结果 | 来源 |
|---------|---------|------|
| SQLite DDL 在 BEGIN EXCLUSIVE 内不参与事务 | **NOT A BUG**: SQLite DDL 是事务性的，ROLLBACK 可撤销 CREATE TABLE。经 Codex 实验性验证 | Codex SQLite Attack |
| `cursor.rowcount` 在 `with` 退出后无效 | **NOT A BUG**: `__exit__` 调用 commit() 不关闭连接，cursor 对象的 rowcount 属性存活。经实验验证 | Codex SQLite Attack |
| `_temporary_sibling_path` mkstemp→unlink TOCTOU | **Acceptable**: repo_write_lock 下风险可忽略，mkstemp 随机后缀使碰撞概率极低 | Codex SQLite Attack |
| `record_card_review` 三条 DML 非原子 | **NOT A BUG**: Python sqlite3 默认 isolation_level 使用隐式事务，`with` 块内所有 DML 原子提交 | Codex FSRS State |
| lossy TSV import 污染 ratchet 基线 | **Acceptable**: `--i-understand-this-is-lossy` 警告已明确；导入事件带 `event_type=imported_from_tsv` 和 `eval_bundle_version=imported_from_tsv` 标记 | Claude 主线 |
| `set_card_queue_state` 允许重复 archive | **Acceptable**: 幂等行为，不造成数据错误 | Claude 主线 |

## 5. R1 修复 Fact-Check (R2 交叉验证)

| R1 修复 | R2 验证方法 | 结果 |
|---------|-----------|------|
| R1-H1: stale_reason 列 | DDL 行号确认 (L740) + INSERT 参数计数 (21?/21) + 安装态 PRAGMA 检查 | ✅ 确认正确 |
| R1-H2: finalize TOCTOU | 单连接代码确认 (L274-337) + 运行时原子性测试 | ✅ 确认正确 |
| R1-H3: regenerate 路径 | `_state_dir_for_root` 代码确认 (L1072) + 路径等价性证明 | ✅ 确认正确 |
| R1-M1: stale_reason NULL | `card.stale_reason` 参数确认 (L428) | ✅ 确认正确 |
| R1 修复引入回归 | 17 条 SQL 参数计数全 MATCH + 351 tests + 17 运行时路径 | ✅ 零回归 |

## 6. Contract Compliance Matrix

### result_events DDL vs contract-freeze 3.3: 14/14 合规 ✅

### cards DDL vs contract-freeze 3.4

| Contract 字段 | DDL 列 | 状态 |
|--------------|--------|------|
| card_id | id (重命名) | ⚠️ Low drift |
| concept | concept TEXT NOT NULL | ✅ |
| run_id | run_id TEXT NOT NULL | ✅ |
| source_ref | source_ref TEXT (nullable) | ⚠️ Medium drift |
| fsrs_state | fsrs_state TEXT NOT NULL | ✅ |
| scaffolding_level | scaffolding_level TEXT NOT NULL DEFAULT 'full' | ✅ |
| last_rating | last_rating INTEGER | ✅ |
| card_state | card_state TEXT NOT NULL DEFAULT 'active' (no CHECK) | ⚠️ Medium drift |
| stale_reason | stale_reason TEXT | ✅ (R1 修复) |
| peeked_this_session | 不持久化 (Field exclude=True) | ✅ 合规 |
| file_id | file_id TEXT (nullable) | ⚠️ Medium drift |
| display_path | display_path TEXT (nullable) | ⚠️ Medium drift |
| hunk_id | hunk_id TEXT (nullable) | ⚠️ Medium drift |
| hunk_hash | hunk_hash TEXT (nullable) | ⚠️ Medium drift |
| symbol | symbol TEXT | ✅ (contract 允许 null) |
| change_kind | change_kind TEXT | ✅ (contract: deleted/renamed/null) |

### RunStatus 枚举: 8/8 合规 ✅
### CardState 枚举: 4/4 合规 ✅
### TERMINAL_RUN_STATUSES: 6/6 合规 ✅
### RATCHET_COUNTED_STATUSES: 3/3 合规 ✅
### FSRS 契约: 全部合规 ✅ (desired_retention=0.9, maximum_interval=365, opaque weights)
### Crash recovery (BEGIN EXCLUSIVE): 合规 ✅
### result_events 索引: 5/5 合规 ✅

## 7. 测试命令和真实结果

```
$ uv run pytest tests/unit/test_review.py -q
16 passed in 0.61s

$ uv run pytest tests/unit/test_review.py tests/unit/test_results.py tests/unit/test_ratchet.py \
    tests/unit/test_quiz_generator.py tests/unit/test_lesson_generator.py -q
52 passed in 1.70s

$ uv run ruff check src tests
All checks passed!

$ uv run ruff format --check src tests
104 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations

$ uv run pytest tests/unit -q
351 passed in 7.84s

$ uv build --wheel
Successfully built dist/ahadiff-0.1.0a0-py3-none-any.whl
```

### 安装态 Smoke 测试

```
$ .venv/bin/python -m venv smoke_env
$ smoke_env/bin/pip install ahadiff-0.1.0a0-py3-none-any.whl + deps

验证项:
1. import ahadiff.review.initialize_review_db          → PASS
2. import ahadiff.review.check_review_db               → PASS
3. import ahadiff.review.import_results_tsv_lossy       → PASS
4. import ahadiff.review.review_fsrs_card               → PASS
5. review.sqlite schema_version = 1                     → PASS
6. stale_reason 列存在                                  → PASS
7. lossy import 写入 1 条 imported_from_tsv event        → PASS
8. event_id_unique = True                               → PASS
9. FSRS review hard → rating=2                          → PASS
10. import_cards_from_runs 有 on_error 参数             → PASS
11. restore_review_db 只有 1 次 sidecar 清理            → PASS
12. normalize_fsrs_state("") → InputError               → PASS
13. scaffolding compact 级别可达                         → PASS
```

## 8. Codex 核查清单

以下是建议 Codex CLI 核查的关键检查点：

### 必须验证的修复 (9 项)

1. `src/ahadiff/review/database.py:740` — `stale_reason TEXT` 列存在于 cards DDL
2. `src/ahadiff/review/database.py:401,428` — INSERT 中 stale_reason 列存在且参数绑定 `card.stale_reason`
3. `src/ahadiff/review/database.py:274-337` — finalize_targeted_verify_event 的 SELECT 和 INSERT 在同一个 `with connect_review_db()` 块
4. `src/ahadiff/cli.py:1072` — regenerate_cmd 使用 `_state_dir_for_root` 而非 `run_path.parent.parent`
5. `src/ahadiff/review/database.py:436-453` — `import_cards_from_runs` 有 `on_error` 参数，循环内有 try/except
6. `src/ahadiff/cli.py:1127` — CLI review_cmd 传入 `on_error=_on_card_import_error` 回调
7. `src/ahadiff/review/database.py:142-148` — restore_review_db 先 replace 后删 sidecar (只有 1 次 `_remove_sqlite_sidecars`)
8. `src/ahadiff/review/scheduler.py:72-78,112-118` — `compute_scaffolding_level` 的 `recent_successes` 作为 keyword 参数传递，不在 dict 内
9. `src/ahadiff/review/scheduler.py:49-51` — 空字符串 `""` 显式检测并 raise InputError

### 必须验证的 SQL 参数对齐 (关键 4 条)

1. `import_cards_from_jsonl` INSERT: 27 列, 6 literal, 21 `?`, 21 params → MATCH
2. `finalize_targeted_verify_event` INSERT: 14 列, 0 literal, 14 `?`, 14 params → MATCH
3. `record_card_review` UPDATE cards: 10 `?`, 10 params → MATCH
4. `sync_result_event` INSERT: 14 `?`, 14 params → MATCH

### 必须验证的合规项

1. SQLite 版本门禁 >= 3.51.3，backports {3.50.7, 3.44.6}
2. WAL mode + busy_timeout=5000 + trusted_schema=OFF + foreign_keys=ON + DBCONFIG_DEFENSIVE
3. backup_review_db 使用 sqlite3.Connection.backup() API
4. result_events 5 个索引全部存在
5. FSRS: desired_retention=0.9, maximum_interval=365
6. rating_for_answer: good→3, hard→2, wrong→1
7. peek guard: peeked_this_session + good = InputError

### 必须验证的不存在项 (防偷跑)

1. 无 serve/Starlette/Uvicorn 代码
2. 无 improve runtime 代码
3. 无前端/React/Vite 代码
4. 无 `ahadiff serve` 命令
5. 无 `ahadiff improve` 命令
6. `regenerate --only quiz` 不重跑 lesson

## 9. 最终判定

### GO

- **0 Critical**
- **R1 3 High + R2 1 High = 4 High 已修复**（stale_reason / finalize TOCTOU / hardcoded path / corrupt cards crash）
- **R2 1 High 未修复** = 测试债务（不阻塞 Task 14.5）
- **R1+R2 共修复 9 项**，全部经交叉验证确认正确，零回归
- **最重要修复**: R2-M7 scaffolding 参数断裂 — 此 bug 导致撤架系统完全失效
- **351 tests + ruff + pyright + wheel + 13 项安装态 smoke 全绿**
- 可以进入 Task 14.5 (Serve Backend)

## 10. Post-Codex Remediation Addendum (2026-04-24)

> 本节记录在上述 cross-review 之后，由 Codex CLI 真实复核发现并修复的 3 个遗漏问题。
> 第 9 节的初版 GO 结论在这些修复落地前并不成立；以下内容才是当前真值。

### 新增修复 (3 项)

#### R3-H1 [High] 旧版 cards 表缺少 stale_reason 列，升级后导入会直接失败

- **文件**: `src/ahadiff/review/database.py`
- **问题**: `CURRENT_SCHEMA_VERSION=1` 时没有对旧 `cards` 表执行显式 migration，但 `import_cards_from_jsonl()` 已无条件写 `stale_reason`
- **触发条件**: 旧 review.sqlite（`schema_version=1` 且 `cards` 无 `stale_reason`）执行卡片导入
- **实际故障**: `OperationalError: table cards has no column named stale_reason`
- **修复**:
  - `CURRENT_SCHEMA_VERSION` 升级到 `2`
  - 新增显式 schema migration，在旧 `cards` 表缺列时执行 `ALTER TABLE ... ADD COLUMN stale_reason TEXT`
- **验证**:
  - 新增回归测试 `test_import_cards_migrates_v1_cards_table_before_writing_stale_reason`
  - 临时旧 schema 复现已从崩溃变为成功导入

#### R3-M1 [Medium] review 命令仍会被 schema-invalid 的 cards.jsonl 打成 Unexpected error

- **文件**: `src/ahadiff/review/database.py`
- **问题**: 先前只将 JSON 解析错误收敛为 `InputError`；`ReviewCard.model_validate()` 抛出的 `ValidationError` 仍会穿透到 CLI 顶层
- **触发条件**: `cards.jsonl` 是合法 JSON，但字段缺失或字段值不满足 `ReviewCard` contract
- **修复**: `_load_review_cards()` 现在将 `ValidationError` 同样收敛为 `InputError`，由 `review_cmd` 统一降级为 warning
- **验证**:
  - 新增回归测试 `test_review_cli_warns_and_skips_schema_invalid_cards_jsonl`
  - 真实复现从 `exit code 2 + Unexpected error` 变为 `exit code 0 + stderr warning`

#### R3-M2 [Medium] regenerate/re-import 会为同一 run 累积旧 active 卡片

- **文件**: `src/ahadiff/review/database.py`
- **问题**: 原实现是纯 `INSERT OR IGNORE`，新的 `cards.jsonl` 导入时不会处理同一 `run_id` 下已不存在于最新 artifact 中的旧卡
- **触发条件**: 同一个 run 多次 regenerate quiz，且新旧 card_id 集合不一致
- **影响**: 旧 active 卡仍留在 review.sqlite，due queue 可见性失真
- **修复**:
  - 导入时对同一 `run_id` 执行同步语义
  - 新 card 正常插入
  - 已存在 card 更新元数据并保留用户队列控制态
  - 同 run 下已不在最新 artifact 中的旧 active 卡标记为 `stale + staleness_unknown`
- **验证**:
  - 新增回归测试 `test_import_cards_marks_missing_run_cards_stale_instead_of_leaving_duplicates`
  - 真实复现结果从 `('card-1', 'run-reg'), ('card-2', 'run-reg')` 变为 `('card-1', 'stale', 'staleness_unknown'), ('card-2', 'active', NULL)`

### 新增测试与最新真实结果

```
$ uv run pytest tests/unit/test_review.py -q
32 passed in 0.96s

$ uv run pytest tests/unit/test_results.py tests/unit/test_review_scheduler_extra.py -q
25 passed in 0.31s

$ uv run pytest tests/unit -q
383 passed in 9.70s

$ uv run ruff check src tests
All checks passed!

$ uv run ruff format --check src tests
105 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations
```

### 当前判定

- **补充发现的 1 High + 2 Medium 已全部修复**
- **Task 15 当前代码真值**:
  - 显式修复项 9/9 保持成立
  - 后补修复项 3/3 已落地并有回归测试
  - 原报告第 3 节的 High / Medium 已全部清空，仅剩 2 个 Low 保留项：`R2-L1` / `R1-M3`
  - 另有 3 个 Low 已顺手收口：`R2-L2` / `R2-L3` / `R1-L3`
  - `R1-M5` 已确认属于第 10 节 `R3-H1` 覆盖后的过期项，不应继续计入未修复
  - 本轮还补抓并修复了 1 个原报告未列出的 Medium：lossy TSV import 对同一 `run_id + timestamp` 的 duplicate identity 由静默塌缩改为显式失败并整批回滚
  - 初版报告中“corrupt cards crash 已完全修复”的表述过强，现已补齐到真实闭环
- **当前可进入 Task 14.5**，且第 3 节原列出的非阻塞技术债务已完成本轮同步收口
