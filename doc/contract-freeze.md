# AhaDiff v0.1 Contract Freeze

> Stage 0 / Task 0 的单一权威契约文档。
> 执行母表：`.claude/team-plan/ahadiff-v01-implementation-plan.md`
> 编纂裁决顺序：`CLAUDE.md` > `.claude/team-plan/ahadiff-v01-kickoff.md` > `.claude/team-plan/ahadiff-v01-stages-4-9.md`
> 本文签发后，具体契约以本文为准；其余文档降级为设计过程与排程说明。

---

## 1. 范围与边界

### 1.1 Stage 0 产物范围

Stage 0 只冻结“最小可 import + 可序列化”的 contracts 面，不提前进入后续开发。

- 文档权威源：`doc/contract-freeze.md`
- Python contract 面：
  - `src/ahadiff/contracts/claim_status.py`
  - `src/ahadiff/contracts/run_source.py`
  - `src/ahadiff/contracts/eval_bundle.py`
  - `src/ahadiff/contracts/event_log.py`
  - `src/ahadiff/contracts/error_types.py`
  - `src/ahadiff/contracts/orchestrator.py`
  - `src/ahadiff/contracts/serve_app.py`
- 聚合入口：
  - `src/ahadiff/__init__.py`
  - `src/ahadiff/contracts/__init__.py`
- 验收测试：
  - `tests/unit/test_contracts.py`

### 1.2 明确不在 Stage 0 内的内容

以下内容不允许提前偷跑：

- `pyproject.toml`、CLI 包装、依赖管理：属于 Stage 1 / Task 1
- `src/ahadiff/eval/*.py`、`src/ahadiff/eval/rubric.yaml` 的实际实现：属于 Stage 3 / Task 11
- SQLite 表结构/migration 落库：属于 Stage 4 / Task 15
- provider、Graphify、learnability 的运行时实现：属于后续 Stage；Stage 0 只冻结契约

### 1.3 Stage 命名口径

- 外层阶段只使用 `Stage 0-7`
- `Layer 0-3`、`Layer 6a/6b` 只保留给内部依赖 DAG
- 不再使用 `Stage 0-9`

### 1.4 Stage 0 Gate

- Stage 0 gate = `Codex + Claude`
- 不要求 Gemini 参与本阶段签核

---

## 2. 统一命名与枚举

### 2.1 统一字段命名

- `source_ref`：统一替代旧的 `head_sha`
- `privacy_mode`：统一使用 snake_case
- `eval_bundle_version`：统一替代把 `rubric_version` 当真相源的旧口径
- `scaffolding_level`：统一使用 `full | hint | compact`

### 2.2 ClaimStatus

`ClaimStatus = verified | weak | not_proven | contradicted | rejected`

`RejectReasonCode = file_not_in_patch | line_outside_hunk | symbol_not_found | hunk_id_mismatch | evidence_missing`

约束：

- `rejected` 仅用于 patch 外证据或不存在证据，不等价于 `contradicted`
- `status = rejected` 时 `reason_code` 必填；其他状态不得携带 `reason_code`
- Claim 记录的最小字段包含 `claim_id / run_id / text / status / reason_code / confidence / source_hunks`

### 2.3 RunStatus

`RunStatus = baseline | keep | discard | crash | targeted_verify | keep_final | phase25_rewrite | non_ratcheted`

冻结规则：

- `rollback` 已移除，不再允许回流
- `keep` 只用于 `learn` 链路
- `targeted_verify -> keep_final` 只用于 `improve` 链路
- `non_ratcheted` 仅用于无 git ancestry 的输入

终态集合：

- `baseline`
- `keep`
- `discard`
- `crash`
- `keep_final`
- `non_ratcheted`

计入 ratchet 的状态：

- `baseline`
- `keep`
- `keep_final`

Task 16 补充：

- `targeted_verify` 仍是 improve 链路的过渡态，不属于终态集合；成功 cherry-pick 后写出的 finalized `targeted_verify` 可以作为后续 improve baseline，`keep_final` 仍通过全 8 维 recheck 后的手动 `db finalize-targeted` 收口
- cherry-pick 冲突时允许写 `status=targeted_verify` 并在 `note_json` 中记录 `cherry_pick_pending=true`，但不得写 `finalized.json`，也不得被下一轮 improve 当作 baseline
- `discard` 不写 `finalized.json`

Task 17 补充：

- targeted verification 只比较目标维度 + `accuracy` + `evidence` + `safety_privacy` 四个维度的合计分；候选还必须通过 hard gates，才允许从 `discard` 升级为 `targeted_verify`
- Phase 2.5 只在同一 improve session 内连续两次 `discard` 后触发一次；触发时先写 `status=phase25_rewrite`，并在 `note_json` 中记录 `phase25=true`、`phase25_note`、`stash_ref` 与 `trigger_reason`
- Phase 2.5 的最终结果仍回到 improve 链路：通过写 `targeted_verify`，不通过写 `discard`；它不使用 learn 链路的 `keep`

### 2.4 CardState / StaleReason

`CardState = active | stale | archived | suspended`

`StaleReason = file_deleted | symbol_removed | line_drifted | staleness_unknown`

补充约束：

- `peeked_this_session` 是 session-local 标志，不持久化
- `staleness_unknown` 允许出现在 DTO 中，但不能因为“无 ancestry”就自动把卡片从 `active` 降为 `stale`
- rename/move 场景优先按 symbol 判定，路径漂移不直接等于 stale

### 2.5 其他冻结枚举

- `PrivacyMode = strict_local | redacted_remote | explicit_remote`
- `ScaffoldingLevel = full | hint | compact`
- `ReviewAnswer = good | hard | wrong`
- `Verdict = PASS | CAUTION | FAIL`

---

## 3. 核心 DTO 与 Schema

### 3.1 RunSource

`RunSource` 最小字段：

- `source_kind`: `git_ref | git_staged | git_staged_unstaged | git_unstaged | git_since | patch_file | patch_stdin | file_compare`
- `source_ref`: 统一来源标识
- `capability_level`: `1 | 2 | 3`
- `degraded_flags`: key 仅允许来自以下集合
  - `diff_clipped`
  - `binary_only`
  - `file_count_exceeded`
  - `token_exceeded`

说明：

- `source_kind` 的细粒度值是权威值；更粗的 `git / patch / file_compare` 只允许作为 UI 展示分组

### 3.2 EvaluationBundle

冻结的 bundle 成员正好 5 个：

- `src/ahadiff/eval/deterministic.py`
- `src/ahadiff/eval/evaluator.py`
- `src/ahadiff/eval/gates.py`
- `src/ahadiff/eval/rubric.py`
- `src/ahadiff/eval/rubric.yaml`

哈希输入使用**逻辑标签**而不是磁盘路径：

```python
EVAL_BUNDLE_FILES = (
    ("eval/deterministic.py", "src/ahadiff/eval/deterministic.py"),
    ("eval/evaluator.py", "src/ahadiff/eval/evaluator.py"),
    ("eval/gates.py", "src/ahadiff/eval/gates.py"),
    ("eval/rubric.py", "src/ahadiff/eval/rubric.py"),
    ("eval/rubric.yaml", "src/ahadiff/eval/rubric.yaml"),
)
```

哈希算法冻结如下：

```python
chunks = []
for logical_path, disk_path in sorted(EVAL_BUNDLE_FILES, key=lambda item: item[0]):
    content = read_bytes(repo_root / disk_path)
    chunks.append(logical_path.encode("utf-8") + b"\n" + content)
eval_bundle_version = sha256(b"\n---\n".join(chunks)).hexdigest()[:12]
```

硬性约束：

- 在字节层做哈希，不做编码转换
- 任一文件变更，包括空白，都会产生新的 `eval_bundle_version`
- `rubric.yaml` 与其余 bundle 文件统一放在 `src/ahadiff/eval/` 下，避免 `eval/` 与 `evals/` 双口径漂移
- `rubric_version` 仅是派生显示字段，不再参与真相判定或缓存失效
- `prompts/*.md` 是 improve loop 唯一允许写入的命名空间，但实际可写白名单只包含 `lesson_generate.md`、`lesson_hint.md`、`lesson_compact.md`、`quiz_generate.md`、`claim_extract.md`；`prompts/improve_program.md` 为 human-written immutable state machine，不属于 improve loop 可写面

### 3.3 ResultEvent / result_events

`result_events` 是物理事件表，SQLite 是唯一真相源；`results.tsv` 只是导出视图。

补充冻结：

- `event_type=learn` 是 learn ratchet 的基线 lane；`score` / `verify` 只做临时评估，不参与 learn baseline 选择
- `prompt_version` 记录的是 **AhaDiff 自带 prompt 资源** 的 tree hash：source checkout / improve worktree 读取该 checkout 内的 `src/ahadiff/prompts`，wheel 安装态读取包内 `ahadiff/prompts`；目标仓库顶层自己的 `prompts/` 不参与哈希
- `note_json` 允许记录 ratchet 原因、learnability metadata 和 `degraded_flags`

最小列集：

- `event_id`
- `run_id`
- `event_type`
- `timestamp`
- `source_ref`
- `base_ref`
- `prompt_version`
- `eval_bundle_version`
- `rubric_version`
- `overall`
- `verdict`
- `status`
- `weakest_dim`
- `note_json`

索引冻结为：

```sql
CREATE UNIQUE INDEX ux_result_events_run_type_ts
    ON result_events (run_id, event_type, timestamp);
CREATE INDEX ix_result_events_source_ts
    ON result_events (source_ref, timestamp DESC);
CREATE INDEX ix_result_events_prompt_eval
    ON result_events (prompt_version, eval_bundle_version);
CREATE INDEX ix_result_events_verdict_status
    ON result_events (verdict, status);
CREATE INDEX ix_result_events_weakest_dim_ts
    ON result_events (weakest_dim, timestamp DESC);
```

### 3.4 ReviewCard / ClaimRecord

`ReviewCard` 最小字段：

- `card_id / concept / run_id / source_ref`
- `fsrs_state`
- `scaffolding_level`
- `last_rating`
- `card_state`
- `stale_reason`
- `peeked_this_session`
- `file_id / display_path / hunk_id / hunk_hash / symbol / change_kind`

补充约束：

- `fsrs_state` 存的是 opaque Card JSON，序列化字符串必须是合法 JSON object
- `last_rating` 只允许 `1-4`
- `card_state = stale` 时 `stale_reason` 必填；其他状态不得携带 `stale_reason`
- `peeked_this_session` 允许存在于运行时模型，但序列化持久化时不输出
- `change_kind` 在当前最小合同里只承载 `deleted | renamed | null`
- `hunk_hash` 算法冻结：只从 hunk header 提取 `section_header`，若非空则在规范化 payload 首行加入 `section:<section_header>`；body 中忽略 `[truncated]` 与 `\ No newline at end of file`，其余行仅去掉行尾 `\r\n`，保留原始 `+/-/ ` 前缀与正文；最终用 `\n` 连接规范化结果，做 SHA-256 并取 hex 前 12 位。因此 LF/CRLF 差异与 hunk 数字范围变化不影响 `hunk_hash`

`ClaimRecord` 最小字段：

- `claim_id / run_id / text / status / reason_code / confidence`
- `source_hunks`
- `symbols`
- `negative_evidence`
- `extractor`

`source_hunks[]` 的最小 entry：

- `file`
- `start`
- `end`
- `side`

补充约束：

- `end >= start`
- `side ∈ {old, new, either}`，默认值是 `either`
- 新生成的 claim 应显式写 `old` 或 `new`；`old` 用于删除行或 rename-from 侧，`new` 用于新增/修改后的行或 rename-to 侧
- 当 `side=either` 且同一数字行号同时能命中 hunk 的 old/new 两侧时，verifier 必须按歧义处理并返回 `reason_code=evidence_missing`

### 3.5 ProviderConfig / ProviderCapabilities

`ProviderConfig` 冻结字段：

- `provider_class = openai | openai_responses | gemini | anthropic | azure | newapi | cherryin | ollama`
- `model_name`
- `base_url`
- `api_key_env`
- `probed_max_context`
- `probed_tpm`
- `probed_rpm`
- `supports_temperature`
- `probe_timestamp`

`ProviderCapabilities` 冻结字段：

- `supports_stream`
- `supports_json_mode`
- `supports_tool_use`
- `supports_temperature`
- `supports_rate_limit_headers`
- `supports_context_probe`
- `tokenizer_estimation = tiktoken | char_div_4 | probe_cached`
- `api_family`
- `api_family_version`
- `provider_kind`

开发测试阶段默认模型：

- `generate_model = gpt-5.4-mini`
- `judge_model = gpt-5.4-mini`

### 3.6 UsageEvent（预留）

`UsageEvent` 在 Stage 0 只冻结 schema，不实现写入：

- `event_id`
- `run_id`
- `repo_id`
- `provider_class`
- `model_id`
- `input_tokens`
- `output_tokens`
- `cost_usd`
- `pricing_version`
- `cost_confidence`
- `billing_mode`
- `execution_origin`
- `api_principal_hash`
- `timestamp`

### 3.7 LearnabilityGate

默认值冻结：

- `weights.complexity = 0.4`
- `weights.novelty = 0.3`
- `weights.pattern = 0.3`
- `threshold = 0.3`
- `calibration_status = heuristic_default`

说明：

- 这是 heuristic defaults，不宣称来自外部科学定标
- 后续允许通过配置覆盖阈值，但 Stage 0 不引入新权重口径

---

## 4. Orchestrator 与 Serve 合同

### 4.1 Orchestrator

冻结对象：

- `OrchestratorCommand.kind = learn | improve | verify | serve`
- `RunConfig`：
  - `source`
  - `lang = auto | en | zh-CN`
  - `privacy_mode`
  - `force_learn`
  - `use_graphify`
  - `dry_run`
- `ServeConfig`：
  - `port`
  - `no_browser`
  - `bind_host = 127.0.0.1`
- `OrchestratorResult`：
  - `run_id`
  - `status`
  - `overall`
  - `verdict`
  - `weakest_dim`
  - `artifacts_path`
  - `note_json`
  - `degraded_flags`

边界：

- `run_serve()` 启动长驻 ASGI 进程，不返回 `OrchestratorResult`
- `src/ahadiff/contracts/orchestrator.py` 只冻结编排接口；运行时实现可以落在其他模块里

### 4.2 Serve 安全边界

冻结规则：

- 只绑定回环地址：`127.0.0.1`
- 写请求必须带 `X-AhaDiff-Token`
- 读请求默认只读，无 token
- 中间件必须做 `Host + Origin/Referer` 双校验
- 非法 loopback preflight 必须直接拒绝，不能透传到写路由
- 带 body 的写请求必须是 `application/json`，并在 JSON 解析前受 1 MiB 上限保护
- 所有响应（包含中间件直接生成的错误响应）都必须带 anti-frame / `nosniff` / `same-origin` 类安全头

冻结端点清单：

- `GET /api/auth/token`
- `GET /api/locale`
- `PUT /api/locale`
- `GET /api/runs`
- `GET /api/run/:id`
- `GET /api/run/:id/lesson`
- `GET /api/run/:id/claims`
- `GET /api/run/:id/quiz`
- `GET /api/run/:id/diff`
- `GET /api/run/:id/concepts`
- `GET /api/concepts`
- `GET /api/ratchet/history`
- `GET /api/review/queue`
- `POST /api/review/rate`
- `GET /api/config`
- `GET /api/doctor`
- `GET /api/install/targets`
- `POST /api/signals/mark-wrong`
- `POST /api/signals/quiz-answer`
- `POST /api/signals/srs-review`
- `POST /api/signals/helpfulness`

补充冻结：

- `GET /api/runs` 的最小摘要字段必须包含 `source_kind`、`capability_level`、`degraded_flags`、`status`
- `GET /api/runs` 支持可选 `?source_kind=` 过滤；前端 ratchet/trend 视图默认排除 `status=non_ratcheted` 或非 `git_ref` runs
- `/healthz` 是 utility route，不参与上述 `/api/*` endpoint 编号

发布可见性冻结：

- run-scoped 读接口只暴露已完成二阶段发布的 finalized runs
- 未写出 `finalized.json` 的临时 run 不得对前端可见
- `result_events` 仍是评分与 ratchet 的唯一真相源
- 若 `score.json` / `finalized.json` 发布失败，必须回滚刚写入的 `result_events`，避免 SQLite 中残留未发布 run

### 4.3 Serve DTO

至少冻结以下响应 DTO：

- `AuthTokenResponse`
- `LocaleResponse`
- `RunSummary`
- `RunDetail`
- `RunArtifactEnvelope`：`run_id`、`artifact_type`、`content`、`content_lang: Literal["en","zh-CN"] | None`
- `RatchetHistoryEntry`

Stage 0 同时冻结最小写请求 DTO：

- `SetLocaleRequest`
- `LearningSignalRequest`
- `MarkWrongRequest`
- `ReviewSignalRequest`
- `HelpfulnessRequest`

说明：

- Request DTO 只冻结最小标识字段；后续 payload 扩展不能破坏现有字段语义
- `src/ahadiff/contracts/serve_app.py` 是**契约文件**，不是后续真正的 `src/ahadiff/serve/app.py` 实现文件

### 4.4 Locale 解析顺序

serve/request 链路的 locale 冻结为：

`cookie(ahadiff_lang) -> Accept-Language -> AHADIFF_LANG env -> CLI session -> per-repo config -> global config -> system LANG -> default(en)`

---

## 5. 存储、锁与安全

### 5.1 Config precedence

统一优先级：

`ENV(AHADIFF_*) -> CLI flag -> per-repo .ahadiff/config.toml -> global_config_dir()/config.toml -> defaults`

说明：

- 上述 5 层链适用于除 locale 以外的常规配置键
- locale 是唯一例外，必须走 4.4 的 6 层 request/session 链，因此它额外包含 `cookie / Accept-Language / system LANG`

凭证类优先级：

`env secret -> per-repo env_var_name -> global env_var_name -> none`

### 5.2 Data scope

真相源永远是 per-repo：

- `.ahadiff/review.sqlite`
- `.ahadiff/audit.jsonl`
- `.ahadiff/audit.private.jsonl`
- `.ahadiff/concepts.jsonl`
- `.ahadiff/runs/`
- `.ahadiff/graphify/`
- `prompts/`
- VCR cassettes

global 只做派生层：

- `config.toml`
- `registry.json`
- `usage.sqlite`
- `security/allowlist.yaml`

global 数据不得参与 ratchet 判定。

### 5.3 锁矩阵

冻结三层写锁：

- `repo_write_lock`
- `db_write_lock`
- `serve_write_lock`

获取顺序永远是：

`repo_write -> db_write -> serve_write`

文件锁约束：

- 真相源使用 `portalocker`
- lockfile 路径：`.ahadiff/ahadiff.lock`
- lockfile 内容 `{pid}\n{start_time_iso}\n{command}` 仅作诊断，不做活性真相源
- 手动清理命令：`ahadiff unlock --force`

### 5.4 SQLite gate

最低门禁：

- `sqlite3.sqlite_version_info >= (3, 51, 3)`
- 允许 backport 白名单：`(3, 50, 7)`、`(3, 44, 6)`

不满足时抛出：

```python
StorageError(f"SQLite {actual} < 3.51.3, WAL mode unsafe")
```

统一连接初始化：

- `journal_mode=WAL`
- `busy_timeout=5000`
- `trusted_schema=OFF`
- `SQLITE_DBCONFIG_DEFENSIVE=ON`（实现支持时启用）
- 启动时 `quick_check`
- 深检查留给 `doctor --deep` 或 migration 前的 `integrity_check + foreign_key_check`
- 当前冻结的 `doctor` surface 仅包含 runtime/path/config/SQLite diagnostics；GC/cleanup 类维护动作不默认绑定到 `doctor`

### 5.5 Crash recovery

- stale lock：依赖 `portalocker` 随进程退出自动释放
- orphaned worktree / `.tmp` run 目录 / audit rotation 临时文件：当前不并入 `doctor`。单独维护命令 `ahadiff maint clean-orphans` 负责清理 `.ahadiff/runs/*.tmp` 与 `audit*.jsonl.gz.tmp`；不承诺处理 VCR、Graphify 或其他任意临时文件
- migration 部分失败：每个 migration 在 `BEGIN EXCLUSIVE ... COMMIT` 中执行

### 5.6 Allowlist / untrusted boundary

Allowlist policy 只冻结以下能力：

- builtin `hard_block` 不可禁用
- `soft_detect` 可被 allowlist suppress
- v0.1 仅支持 `exact | hash | path_scope`
- v0.1 不支持 regex
- 每个 run 落 `allowlist_digest`

安全顺序冻结：

`raw input -> secret scan -> redact -> log/cache/model/render`

UNTRUSTED 边界至少包含：

- diff 正文
- 文件名
- commit message
- branch / tag 名称
- Graphify label
- 模型输出
- VCR cassette 内容

额外冻结：

- 进入 model / artifact / DB 的 JSON 解析必须拒绝 `NaN`、`Infinity`、`-Infinity` 和非有限浮点溢出

---

## 6. Graphify v0.1 合同

Graphify 在 v0.1 中是**可选增强**，不是主链前置。

冻结行为：

- `ahadiff learn` 自动检测 `graphify-out/graph.json`
- 产物存在则导入 repo-level context
- 产物不存在则静默降级
- `graph.json` 与 Graphify label 同样视为 untrusted，必须先经过 sanitization
- 保留“内部 7 态 freshness -> 对外 4 值投影”的设计，但 Stage 0 不冻结这 4 个投影标签的具体字面值

冻结 CLI surface：

- `--use-graphify`
- `--no-graphify`
- `ahadiff graph status`
- `ahadiff graph refresh`
- `ahadiff graph import`

冻结前端展示边界：

- full
- learning_only
- empty

---

## 7. Stage 0 验收

Stage 0 通过标准：

- `doc/contract-freeze.md` 与权威源无冲突
- `from ahadiff.contracts import *` 可用
- `tests/unit/test_contracts.py` 通过
- 不因为赶验收而提前补 Stage 1 的 `pyproject.toml`

最小验证命令：

```bash
uv run pytest tests/unit/test_contracts.py -q
uv run python - <<'PY'
from ahadiff.contracts import *
print("contracts import ok")
PY
```

---

## 8. 变更规则

后续如要修改本文任何已冻结条款，必须同时满足：

1. 先有 RFC 或明确裁决记录
2. 重新跑 Codex + Claude 交叉审查
3. 若影响前端契约，再加 Gemini gate
4. 若影响 evaluation bundle 语义，必须连带 bump `eval_bundle_version`
