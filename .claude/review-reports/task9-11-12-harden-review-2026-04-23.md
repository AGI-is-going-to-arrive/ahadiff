# Harden Review: Task 9 / 11 / 12 (Lesson + Eval + Ratchet)

**Date**: 2026-04-23
**HEAD**: 6655c9c
**Reviewers**: Claude Opus 4.6 (3 parallel agents) + Codex CLI (2 parallel agents: standard + adversarial)
**Verdict**: **CONDITIONAL GO**

---

## Scope

### Modified tracked files
- `src/ahadiff/cli.py` (+305 lines — new commands: score, verify, export-results; learn extended)
- `src/ahadiff/lesson/__init__.py` (+30 lines)
- `tests/unit/test_git_capture.py` (+24 lines)

### New untracked files
- `src/ahadiff/eval/__init__.py`, `rubric.yaml`, `rubric.py`, `gates.py`, `deterministic.py`, `evaluator.py`, `results.py`, `ratchet.py`
- `src/ahadiff/lesson/generator.py`, `scaffolding.py`, `schemas.py`
- `prompts/lesson_generate.md`, `lesson_hint.md`, `lesson_compact.md`
- `src/ahadiff/prompts/lesson_generate.md`, `lesson_hint.md`, `lesson_compact.md`
- `tests/unit/test_evaluator.py`, `test_gates.py`, `test_results.py`, `test_ratchet.py`, `test_lesson_generator.py`

---

## 1. Findings

### HIGH (9)

#### H-1: `_score_or_verify_run` 在 ratchet 判定前写入 score.json

- **位置**: `src/ahadiff/cli.py:1129`
- **问题**: `write_score_report()` 在 `decide_learn_ratchet()` (L1130) 和 `append_result()` (L1135) 之前执行
- **触发条件**: `decide_learn_ratchet` 或 `append_result` 抛异常（如 git 命令失败、SQLite 磁盘满）
- **后果**: score.json 存在但无 finalized.json / SQLite 行；重试不加 `--force` 会拒绝覆盖
- **测试覆盖**: 无
- **修复**: 将 `write_score_report` 移到 `append_result` 之后
- **发现者**: Claude Eval Review (C-2), Codex Adversarial (M-2)

#### H-2: `_insert_result_event` 用 SELECT+INSERT 存在并发竞态

- **位置**: `src/ahadiff/eval/results.py:196-237`
- **问题**: 两进程同时 SELECT 均为空，然后双 INSERT → 第二个抛 IntegrityError → 被包装为 StorageError
- **触发条件**: 两个 CLI 进程同时对同一 run 执行 score/verify
- **修复**: 改用 `INSERT OR IGNORE` + 检查 `cursor.rowcount`
- **测试覆盖**: 无并发测试
- **发现者**: Claude Eval Review (H-1)

#### H-3: TSV 追加和 finalized.json 写入不受幂等保护

- **位置**: `src/ahadiff/eval/results.py:77-89`
- **问题**: 当 `sqlite_inserted=False`（重复 event_id）时，TSV 仍追加重复行，finalized.json 仍重写
- **触发条件**: 同一 run 执行两次 `score`/`verify`
- **修复**: guard TSV append 和 finalized write 在 `sqlite_inserted` 后面
- **测试覆盖**: 幂等测试只检查 SQLite row count，不检查 TSV 和 finalized
- **发现者**: Claude Eval Review (H-2), Codex Review (M-6), Codex Adversarial (H-3) — 三路交叉确认

#### H-4: Prompt-schema 不匹配导致 LLM 输出时 Pydantic crash

- **位置**: `prompts/lesson_hint.md:29`, `prompts/lesson_compact.md:28`, `src/ahadiff/lesson/schemas.py:22`
- **问题**: hint/compact prompts 指令写 "say so in \`Not Proven\` instead of guessing"，但 LessonHint/LessonCompact 无 `not_proven` 字段，且 `extra="forbid"`
- **触发条件**: LLM 按 prompt 指令在 JSON 中添加 `not_proven` 键
- **附加风险**: prompt 还提到 `Misconceptions`/`Quiz`/`Walkthrough` 字段（L32-34），这些也不在 hint/compact schema 中
- **修复**: 方案 A: 给 LessonHint/LessonCompact 加 `not_proven: list[str] = Field(default_factory=list)`；方案 B: 从 hint/compact prompt 中移除对不存在字段的引用
- **测试覆盖**: 无（`_FakeLessonProvider` 返回精确匹配的 schema，不触发 mismatch）
- **发现者**: Claude Lesson Review (F-5), Codex Review (H-3), Codex Adversarial (M-1) — 三路交叉确认

#### H-5: Degraded comparison 无 floor check，总是返回 keep

- **位置**: `src/ahadiff/eval/ratchet.py:63-69`
- **问题**: degraded run 评分 20 vs baseline 90 仍得 `keep`，无最低下限
- **后果**: 质量严重退步的 degraded run 被静默保留
- **修复**: 添加 minimum floor（如 baseline * 0.5），低于 floor 的 degraded run 返回 `keep_degraded` 或 `discard`
- **测试覆盖**: 有 degraded keep 的正向测试，但无 floor 边界测试
- **发现者**: Claude Eval Review (H-3)

#### H-6: `compute_prompt_version()` 在 wheel 安装下始终返回 "no-prompts"

- **位置**: `src/ahadiff/eval/results.py:154-158`
- **问题**: 只扫 workspace `prompts/` 目录，wheel 安装后该目录不存在
- **后果**: `result_events.prompt_version` 失去追踪意义，VCR cassette key 因固定值 "no-prompts" 而不区分 prompt 变更
- **修复**: 增加 `importlib.resources` 回退路径，或使用打包时预计算的 prompt hash
- **测试覆盖**: 无 wheel 运行时测试
- **发现者**: Codex Review (H-2)

#### H-7: `select_baseline_event()` 不过滤 event_type，score 事件污染 learn ratchet

- **位置**: `src/ahadiff/eval/ratchet.py:75-88`
- **问题**: 手动 `ahadiff score` 产生的事件会被选为 learn ratchet 基线
- **后果**: 手动评分后的 learn 流程可能错误判定 keep/discard
- **修复**: 添加 `event_type` 参数，`decide_learn_ratchet` 传入 `"learn"` 过滤
- **测试覆盖**: 无混合 event_type 测试
- **发现者**: Codex Review (H-4)

#### H-8: `_project_root()` 在 wheel 安装下路径错误，scoring 全链路崩溃

- **位置**: `src/ahadiff/eval/evaluator.py:119-120`
- **问题**: `Path(__file__).resolve().parents[3]` 在 source checkout 下正确指向项目根，但在 wheel/pip 安装到 site-packages 后指向错误位置
- **后果**: `compute_eval_bundle_version()` 找不到 eval bundle 文件 → scoring/lesson 全链路 FileNotFoundError
- **修复**: 使用 `importlib.resources` 定位 eval bundle 文件，或使用 `__file__` 相对路径 + 回退
- **测试覆盖**: 无 wheel 运行时测试
- **发现者**: Claude Eval Review (M-5), Codex Review (H-1) — 双路交叉确认，经我验证升级为 HIGH

#### H-9: Lesson 多文件写入非原子，无回滚机制

- **位置**: `src/ahadiff/lesson/generator.py:259-288`
- **问题**: `write_lesson_artifacts()` 顺序写入 full/hint/compact/misconception/not_proven，中途失败留下混合态
- **触发条件**: `overwrite=False` + 文件已存在（部分），或磁盘空间不足
- **修复**: 写入临时子目录 → 全部成功后 rename 到目标位置；或在入口检查所有目标文件不存在
- **测试覆盖**: 无部分失败测试
- **发现者**: Codex Adversarial (H-2)

---

### MEDIUM (12)

#### M-1: Provider 失败时半成品 run 目录无清理

- **位置**: `src/ahadiff/cli.py:678-757`
- **问题**: `write_input_artifacts()` 在 LLM 调用前执行，provider 失败后 run 目录残留。`maint clean-orphans` 只清 `.tmp` 后缀
- **发现者**: Claude CLI Review (A-2)

#### M-2: `_extract_json_object_text` 只处理顶层 fence

- **位置**: `src/ahadiff/lesson/schemas.py:163-169`
- **问题**: LLM 返回 "Here is the lesson:\n```json\n{...}\n```" 时解析失败，因为 fence 不在第一行
- **修复**: 参考 `claims/extract.py` 的更健壮提取器，搜索第一个 `{`
- **发现者**: Claude Lesson Review (F-4)

#### M-3: 零 verified claims 无 guard 即进入 lesson generation

- **位置**: `src/ahadiff/cli.py:710-744`
- **问题**: 空 claims.jsonl 传入 LLM 生成无证据 lesson，无 warning 或质量 gate
- **发现者**: Claude Lesson Review (F-12)

#### M-4: `_score_or_verify_run` 绕过 network-drive guard

- **位置**: `src/ahadiff/cli.py:1124`
- **问题**: `workspace_root = run_path.parent.parent.parent` 未走 `assert_local_repo_path()`
- **发现者**: Claude CLI Review (B-3)

#### M-5: `rubric.yaml` 实际是 JSON 但文件名暗示 YAML

- **位置**: `src/ahadiff/eval/rubric.yaml:1`, `rubric.py:36`
- **问题**: 文件内容是纯 JSON，但扩展名为 `.yaml`；`load_rubric()` 使用 `json.loads()`
- **风险**: YAML 编辑器可能添加注释或改变格式导致 `json.loads()` 失败；eval bundle hash 计算基于文件字节，格式变化会静默改变 hash
- **注**: Claude Eval Review 报为 Critical，经我验证降级 — JSON 是 YAML 子集，YAML 改动后 json.loads() 会给出清晰错误而非静默腐坏
- **发现者**: Claude Eval Review (C-1)

#### M-6: finalized.json 写入与 SQLite commit 非原子

- **位置**: `src/ahadiff/eval/results.py:258-279`
- **问题**: SQLite commit 成功后磁盘满导致 finalized.json 缺失，run 对 serve API 不可见
- **发现者**: Claude Eval Review (M-4)

#### M-7: `_project_root()` 用 `Path(__file__).parents[3]` 在 wheel 安装下失败（已升级为 H-8）

- 见 H-8

#### M-8: results.py 的 DB 连接跳过 SQLite 版本门禁

- **位置**: `src/ahadiff/eval/results.py:282-294`
- **问题**: contract-freeze 要求 SQLite >= 3.51.3（WAL-reset bug fix），此处 `_connect_result_db()` 未检查版本
- **发现者**: Codex Review (H-5)

#### M-9: `finalized.json` 硬编码 `"score_path": "score.json"` 忽略 `--output` 参数

- **位置**: `src/ahadiff/eval/results.py:269`
- **问题**: 用户传 `--output /tmp/my-score.json` 后，finalized.json 仍指向 `score.json`
- **发现者**: Codex Review (M-8), Codex Adversarial (L-1)

#### M-10: `secret_leak` / `injection_unresolved` gates 的 detail 文本在失败时仍显示 "no ... detected"

- **位置**: `src/ahadiff/eval/gates.py:91-98`
- **问题**: `detail` 字符串不随 `passed` 状态变化，失败时诊断信息误导用户
- **发现者**: Codex Review (M-9)

#### M-11: 缺少 lesson/quiz 时评分仍可达 PASS（82 > 80 阈值）

- **位置**: `src/ahadiff/eval/deterministic.py:96-149`, `rubric.yaml:2-31`
- **问题**: conciseness(8) + quiz_transfer(10) = 18 分缺失，其余 6 维满分 = 82 > 80
- **注**: Codex Adversarial 报 HIGH，我降为 MEDIUM — 应通过前置 guard 在评分前拦截而非改阈值
- **发现者**: Codex Adversarial (H-1)

#### M-12: `export-results` 命令未获取 repo lock

- **位置**: `src/ahadiff/cli.py:1219-1237`
- **问题**: 与并发 `score`/`verify` 可能交叉写入 TSV
- **发现者**: Codex Adversarial (M-3)

---

### LOW (8)

| ID | 位置 | 说明 | 发现者 |
|----|------|------|--------|
| L-1 | `tests/unit/test_git_capture.py` | ruff format 不通过 | Test Runner |
| L-2 | `src/ahadiff/eval/deterministic.py:216-224` | `_spec_alignment_score` 有 spec 时得 6.0，无 spec 时得 10.0（反向激励） | Claude Eval Review |
| L-3 | `src/ahadiff/eval/results.py:165` | `compute_prompt_version` 用 uuid5 不一致于 SHA-256 | Claude Eval Review |
| L-4 | — | `score` 命令无独立 CLI 测试 | Claude CLI Review |
| L-5 | `src/ahadiff/lesson/scaffolding.py` | Scaffolding 未接入 generation flow（v0.1 intentional） | Claude Lesson Review |
| L-6 | — | `--lang` 未暴露给 CLI learn 命令 | Claude Lesson Review |
| L-7 | `src/ahadiff/eval/ratchet.py:119-124` | `_looks_like_commitish` 启发式宽松 | Claude Eval Review |
| L-8 | `src/ahadiff/cli.py:1123,1157-1216` | score/verify 共享默认输出 score.json，连续执行需 --output | Codex Adversarial |

---

## 2. Codex Cross-Review Summary

### Claude 独有发现

- H-1 score.json 写入顺序（虽然 Codex Adversarial 也发现但评为 Medium）
- H-2 SELECT+INSERT 并发竞态
- H-5 degraded 无 floor check
- M-1 provider 失败残留
- M-2 JSON fence 脆弱
- M-3 零 claims 无 guard
- M-4 network-drive guard bypass
- M-6 finalized 非原子

### Codex 独有发现

- H-6 prompt_version wheel 失效
- H-7 baseline event_type 未过滤
- H-9 lesson 写入非原子
- M-8 SQLite 版本门禁缺失
- M-10 gates detail 误导
- M-11 无 lesson 仍可 PASS
- M-12 export-results 无 lock

### 多源交叉确认

| Finding | 确认源数 | 置信度 |
|---------|---------|--------|
| H-3 TSV 不幂等 | 3 路 (Claude Eval + Codex Review + Codex Adversarial) | 最高 |
| H-4 Prompt-schema drift | 3 路 (Claude Lesson + Codex Review + Codex Adversarial) | 最高 |
| H-8 _project_root wheel | 2 路 (Claude Eval + Codex Review) | 高 |
| H-1 score.json 顺序 | 2 路 (Claude Eval + Codex Adversarial) | 高 |

### 冲突与裁决

| 冲突点 | Claude 评级 | Codex 评级 | 裁决 | 理由 |
|--------|:----------:|:----------:|:----:|------|
| rubric.yaml 是 JSON | Critical | 未提及 | Medium | JSON 是 YAML 子集，改动后 json.loads 会明确报错 |
| score.json 写入顺序 | High | Medium (adversarial) | High | 有 --force 恢复路径但用户体验差 |
| _project_root wheel | Medium | High | High | 双路确认，wheel 是主要安装方式 |
| 无 lesson 仍 PASS | 未发现 | High (adversarial) | Medium | 应前置 guard 而非改阈值 |

---

## 3. Tests Actually Run

| 命令 | 结果 |
|------|------|
| `env PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest tests/unit/test_evaluator.py test_gates.py test_results.py test_ratchet.py test_lesson_generator.py test_git_capture.py -v` | **64 passed** (3.78s) |
| `env PYTEST_ADDOPTS='-p no:cacheprovider' uv run pytest tests/unit -q` | **306 passed** (6.28s) |
| `uv run ruff check src tests` | **PASS** |
| `uv run ruff format --check src tests` | **FAIL** — `tests/unit/test_git_capture.py` 需格式化 |
| `uv run pyright` | **PASS** — 0 errors, 0 warnings |
| `uv build --wheel` | **PASS** — `ahadiff-0.1.0a0-py3-none-any.whl` |
| Wheel 内容验证 | **PASS** — eval/, lesson/, prompts/ 全部包含 |
| Smoke: `ahadiff learn --patch ... --dry-run` | **PASS** — learnability 0.684 |
| Smoke: `ahadiff learn --patch ...` (real, port 8318 openai) | **PASS** — 4 claims + 3 lessons 生成 |

### 未运行

- Windows live test（无环境）
- Linux live test（无环境）
- Wheel 安装后运行时测试（未做 pip install + 运行验证）
- 并发压力测试

---

## 4. Cross-Platform Assessment

| 平台 | 方式 | 状态 | 说明 |
|------|------|------|------|
| **macOS** | Live 测试 | **PASS** | 306 tests + smoke 全通过 (Darwin 25.4.0) |
| **Windows** | 静态审查 | **有风险** | pathlib 使用正确；`os.replace()` 可能因 antivirus 持锁失败；`mkstemp+unlink+write` 有 TOCTOU；SQLite WAL 在网络盘不安全（有 guard） |
| **Linux** | 静态审查 | **低风险** | 无已知特异问题；temp 文件权限 0o600 安全 |

---

## 5. Residual Risks

| 风险 | 归属 | 说明 |
|------|------|------|
| review.sqlite 完整 CRUD + migration | Task 15 | 当前只有 bootstrap DDL，不应误报 |
| Quiz generation pipeline | Task 10 | 未实现，不应误报 |
| improve loop + Phase 2.5 | Task 16 | 未实现 |
| serve API + viewer | Task 14/14.5 | 未实现 |
| FSRS SRS 调度 | Task 10 | 未实现 |
| `--lang` CLI 标志 | i18n overlay | 已知缺失，计划实现 |
| Wheel 运行时验证 | Stage 4 gate | 当前 source checkout 开发，wheel 问题不影响开发流 |

---

## 6. Verdict

### **CONDITIONAL GO**

| 维度 | 统计 |
|------|------|
| Critical | 0 |
| High | 9 |
| Medium | 12 |
| Low | 8 |

### 修复优先级

| 优先级 | 范围 | Findings | 截止点 |
|--------|------|----------|--------|
| **P0** | 运行时 crash 风险 | H-1 写入顺序, H-2 竞态, H-3 TSV 幂等, H-4 prompt-schema, H-9 lesson 原子性 | 下次 commit 前 |
| **P1** | 语义正确性 | H-5 degraded floor, H-6 prompt_version, H-7 event_type filter, H-8 _project_root | Stage 4 gate 前 |
| **P2** | 健壮性 | M-1~M-12 | Stage 4 gate 前 |
| **P3** | 代码质量 | L-1~L-8 | 随时 |

### 进入下一 Stage 条件

1. P0 全部修复 + 对应测试补齐
2. P1 全部修复
3. `ruff format tests/unit/test_git_capture.py`
4. 重跑 `uv run pytest tests/unit -q` 确认无回归
