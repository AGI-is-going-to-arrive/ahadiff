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

`ClaimExtractor = python_ast | tree_sitter | regex | section_header`

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
- `/api/auth/token` 是启动令牌获取口，不是普通匿名读接口；它必须带同源浏览器信号（`Sec-Fetch-Site: same-origin` 或当前端口的 loopback `Origin` / `Referer`）
- 中间件必须做 `Host + Origin/Referer` 双校验
- 中间件默认拒绝 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 这类代理痕迹头
- 非法 loopback preflight 必须直接拒绝，不能透传到写路由
- 带 body 的写请求必须是 `application/json`，并在 JSON 解析前受 1 MiB 上限保护
- 所有响应（包含中间件直接生成的错误响应）都必须带 anti-frame / `nosniff` / `same-origin` 类安全头

冻结端点清单：

- `GET /api/auth/token`
- `POST /api/auth/token`
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
- `run_id` / `task_id` / `event_id` / `claim_id` / `card_id` 这类公开标识字段必须拒绝空字符串；`source_ref` 这类历史引用字段不在本轮一刀切收紧范围内
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
- capture 当前补充冻结：
  - `capture.symbol_extractor = auto | builtin | tree_sitter`
  - 默认值是 `auto`
  - 当前 symbol extraction 顺序记为 `python_ast -> tree_sitter -> regex -> section_header`
  - Python 仍优先走 AST；只有支持的非 Python 路径才会尝试 tree-sitter

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

---

## 9. v1.0 Contract Extension — 0G 合同边界收口（2026-04-29）

以下扩展基于 Phase 0G 合同边界收口裁决，适用于 v1.0 后续开发。所有决策经代码验证 + 测试确认。

### 9.1 HelpfulnessRequest `section_id` 约束

**裁决**：不引入独立 `section_id` 字段。`target_id` 双用：

- `target_kind="file"` 时：文件路径（如 `src/main.py`），无格式约束
- `target_kind="section"` 时：格式 `{run_id}:{section_name}`，**必须包含 ASCII `:`，且冒号两侧 strip 后均非空**
- 服务端会在校验通过后把该字段规范化为 canonical 形式 `{run_id}:{section_name}`（去掉分隔符两侧 padding）

**实现**：`contracts/serve_app.py` 的 `HelpfulnessRequest` 已添加 `model_validator(mode="after")`，在 `target_kind="section"` 时校验 `target_id` 含 `:`。

**理由**：`target_id` 已在生产代码和测试中以 `run_id:section_name` 格式使用（如 `test_helpfulness.py` 中 `"run1:intro"`）。添加独立字段会创建冗余且破坏现有接口。

### 9.2 MisconceptionCard 继续 artifact-only

**裁决**：`MisconceptionCard` 保持 `quiz/misconception.py` 中的 frozen dataclass，不升级到 `contracts/` Pydantic DTO、不引入 SQLite 表、不新增跨 run 聚合。

**冻结 artifact schema**：

```
card_id: str
concept: str
misconception: str
correction: str
evidence_ref: str
severity: "low" | "medium" | "high"
safety_tags: tuple[str, ...]
run_id: str
```

**存储**：`misconception_cards.jsonl`（per-run artifact，位于 `.ahadiff/runs/<run_id>/quiz/`）

**Serve 路由**：`GET /api/run/{run_id}/misconceptions` → 通过 `RunArtifactEnvelope` 返回原始 JSONL 文本（pass-through，schema 仅在写入端由 `parse_misconception_cards()` 校验；读接口不重复校验，避免拒绝旧版本产物）

**理由**：misconception cards 是生成时写入、运行时只读的 per-run 产物。当前不需要 SRS 调度或跨 run 聚合。若未来需要跨 run misconception 趋势分析，再升级为 SQLite + contract DTO。

### 9.3 Graphify runtime-only 边界确认

**裁决**：Graphify 保持 runtime-only 检测。

- 不引入 `[graph]` pip extras 或编译时依赖
- 所有 Graphify 相关 import 必须是运行时 lazy import，不得出现在模块顶层
- `detect_graphify_status()` 的 `"source_present"` 硬编码已在 §9.6（Phase 3E）中修复，现在通过 `compute_freshness()` 计算真实 4 值投影
- contract-freeze §6 已有的 CLI surface（`--use-graphify` / `--no-graphify` / `ahadiff graph *`）和前端三态（`full` / `learning_only` / `empty`）继续有效

### 9.4 v0.2→v1.0 Serve 端点扩展冻结

以下端点是 v0.2 及当前分支已实现的新增端点，补入冻结清单（§4.2 原有端点不变）：

- `GET /api/run/{run_id}/misconceptions` — misconception cards artifact
- `GET /api/search` — FTS5 全文搜索
- `GET /api/usage` — LLM 用量汇总
- `GET /api/audit` — 审计日志查询
- `GET /api/review/mastery` — SRS 掌握度
- `GET /api/concepts/weak` — 薄弱概念
- `GET /api/spec/alignment` — spec 对齐度
- `GET /api/stats/learning` — 学习效能（helpfulness + transfer）
- `GET /api/stats` — 总览统计
- `GET /api/review/heatmap` — 复习热力图
- `GET /api/providers` — provider 状态
- `GET /api/serve/status` — serve 运行状态（无 auth）
- `GET /api/graph/status` — Graphify 当前状态；当前 payload 是 `enabled` / `source_exists` / `has_graph` / `freshness` / `node_count` / `edge_count` / `source_path`，不是完整 provenance API
- `GET /api/graph/concepts` — ConceptGraph 前端 DTO；返回 sanitized `nodes` / `edges` + `status`，不是完整 Graphify provenance API
- `PUT /api/config` — 配置更新
- `POST /api/learn` — 提交后台 learn 任务；当前返回 `202 {"task_id": ...}`，进度/取消走 `/api/tasks*`
- `GET /api/tasks` — **unstable**，参见 §9.10
- `GET /api/tasks/{task_id}` — **unstable**，参见 §9.10
- `POST /api/tasks/{task_id}/cancel` — **unstable**，参见 §9.10
- `GET /api/tasks/{task_id}/progress` — SSE 事件流，**unstable**，参见 §9.10

### 9.5 Concepts 真相源主从关系（1A）

**裁决**：`concepts.jsonl` 是 append-only 真相源，SQLite `concepts` 表是派生查询缓存。

**写入顺序**（`wiki/concepts.py:append_concepts()`）：
1. JSONL 先写（`_write_jsonl_snapshot()`，原子替换）
2. SQLite 后同步（`upsert_concepts_batch()`）

**同步方向**：单向 JSONL → SQLite，无反向路径。

**读取路径**：
- `load_concepts_page_from_storage()`：优先 SQLite（先同步 JSONL → SQLite），DB 不存在时回退 JSONL
- `/api/concepts`：在 git repo 中使用 `load_visible_concepts()` 从 JSONL 读（需 ancestry 过滤），非 git 场景使用 `load_concepts_page()` 从 JSONL 直读
- `/api/concepts/weak`：从 SQLite `cards` 表读（非 `concepts` 表），按 stability 排序

**恢复保证**：SQLite `concepts` 表可从 `concepts.jsonl` 完全重建（通过 `_sync_jsonl_concepts_to_db()`）。

**兼容 helper**：当前也已有 `export_concepts_from_db()`，用于把 SQLite `concepts` 表重新导出为 JSONL 快照；它是兼容/维护 helper，不改变 `concepts.jsonl` 的真相源地位。

**与 contract-freeze §5.2 一致**：`concepts.jsonl` 已列入 per-repo 真相源清单。

### 9.6 Graphify Freshness 接线（3E）

**裁决**：`detect_graphify_status()` 接入真实 freshness 计算，替换 `"source_present"` 硬编码。

**接线方式**：
- `detect_graphify_status()` 新增可选参数 `repo: GitRepo | None`
- 有 git 上下文时：通过 `git log -1 --format=%H -- graphify-out/graph.json` 获取 graph commit，`git rev-list --count --max-count=51` 获取有界距离，调用 `compute_freshness()` → `project_freshness()` 得到 4 值投影
- 无 git 上下文时：降级为 `"stale"`（`FreshnessState.UNKNOWN` 投影）
- `GraphifyStatus.freshness` 存储 4 值投影字符串：`"fresh" | "stale" | "unavailable" | "disabled"`
- git probe timeout / parse 失败时同样降级为 `"stale"`，不打断主链路

**metadata.json 字段名修复**：
- 写入使用键名 `freshness`（capture.py:277）
- 读取 `_project_graphify()` 修复为读 `freshness` 键（之前错误读 `status` 键）
- `_SUPPORTED_GRAPHIFY_STATUSES` 接受 canonical 四值以及 legacy 输入 `{"source_present", "missing_partial", "missing"}`
- `_project_graphify()` 会把 legacy 输入规范映射到 canonical 四值输出（`source_present/missing_partial -> stale`，`missing -> unavailable`）

### 9.7 /api/usage repo-scoped 过滤（1D）

**裁决**：`usage.sqlite` 保持全局位置不变（`global_config_dir()/usage.sqlite`），`/api/usage` 端点按 workspace identity 过滤，只返回当前 serve repo 的用量。

**实现**：`routes_stats.py:_build_usage()` 接受 `ServeState` 参数，使用 `workspace_identity_key(state.state_dir.parent)` 作为新的写入/查询键；为兼容历史 `usage.sqlite` 数据，读路径会同时兼容旧的 `path_identity_key(...)` legacy 键。

### 9.8 生产接线收口状态（3D）

| 组件 | 状态 | 说明 |
|------|------|------|
| **registry.py** | ✅ 已接线 | `cli.py` learn 成功后自动调用 `register_repo()`，失败仅 warn 不阻塞 |
| **hooks.py** | ⏸ install-only | 当前仅安装 git hook 脚本，不执行用户自定义 hook 命令。hook 执行入口属于后续 Phase |
| **PUT /api/config** | ✅ session-only | 仅支持 `lang` 键，修改内存中 locale，不持久化到磁盘。这是有意的 serve session 行为 |
| **GET /api/graph/status** | ✅ 已接线 | 以 workspace root 为基准探测 raw `graphify-out/graph.json` 是否存在；当前 node/edge 统计和 `source_path` 读取的是 imported `.ahadiff/graphify/graph.json`，返回 `enabled/source_exists/has_graph/freshness/node_count/edge_count/source_path(relative)` |
| **GET /api/graph/concepts** | ✅ 已接线 | 从 imported `.ahadiff/graphify/graph.json` 投影前端 ConceptGraph 所需的 sanitized nodes/edges/status；5D core d3-force/detail/fallback 已落地，Graphify import provenance 与 per-run `graphify_context.json` artifact 已有后端接线，5E 跨页 freshness/provenance polish 仍属后续 UI 工作 |
| **POST /api/learn** | ✅ 已接线 | `core/orchestrator.py` 从 `cli.py` 抽出 learn 主链；route 只接受安全 capture / learn 选项，返回 `202 {"task_id": ...}`，provider override 不从 HTTP 暴露 |
| **medium APIs** | ✅ 全部真实接线 | search/audit/mastery/weak/alignment/learning stats 均查 SQLite/JSONL，无 mock |
| **/api/tasks*** | ⏸ internal/unstable | 现在已有真实 submitter（`POST /api/learn`），但 task payload / queue policy / progress surface 仍按低层内部接口处理 |

### 9.9 Serve 异步 IO 策略（1B）

**裁决**：维持 `anyio.to_thread.run_sync` + 同步 `sqlite3` 的 threadpool 模式，不引入 `aiosqlite`。

**依据**：
- 28 处 `to_thread.run_sync` 调用已正确隔离所有阻塞 IO
- 读远多于写（21 读 / 5 写），WAL 模式下本地 SQLite 亚毫秒级响应
- 写路径受 `portalocker` 文件锁序列化，是同步阻塞调用 — aiosqlite 无法绕过
- 改写量：`database.py` 1700+ 行 + 6 个 route 文件，收益极低
- `benchmarks/scripts/bench_sqlite_queries.py` 已验证核心查询 p50/p95 性能基线

### 9.10 /api/tasks* 合约收缩（3C）

**裁决**：`/api/tasks*` 路由继续保持 **internal/unstable**，不纳入稳定公开 API 合约。

**当前状态**：`POST /api/learn` 已经接到真实 learn 主链，会返回 `202 {"task_id": ...}`；进度查看和取消分别走 `GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/progress` 和 `POST /api/tasks/{task_id}/cancel`。

**为什么仍不冻结**：task queue 的状态 payload、队列容量策略、进度文案和 SSE 细节都还是低层运行时 surface，后续仍可能继续收口；因此它们继续保留为 internal/unstable。

**当前 runtime 事实**：
- `GET /api/tasks` / `GET /api/tasks/{task_id}` 的 payload 已经带 `error_code`
- 当任务进入运行态后，route 侧会额外投影 `elapsed_seconds`
- `TaskRunner` 默认 scheduler timeout 是 600 秒，可由 `AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS` 覆盖
- `TaskRunner` 支持 per-task `task_timeout_seconds` override
- `POST /api/learn` 当前不再关闭 timeout；它走 `TaskRunner` 的默认 timeout 语义
- thread-backed learn task 被取消时，取消信号会传进 `run_learn_pipeline()` 的 `is_cancelled` 回调；超时进入 draining 的 worker 不会被 `shutdown()` 提前 untrack

**保留状态**：
- `core/task_runner.py`：TaskRunner 类完整保留，Phase 6B 直接使用
- `serve/routes_tasks.py`：路由实现完整保留，Phase 6B 启用
- `serve/app.py`：路由注册保留（内部使用），但不纳入稳定合约
- `serve/routes_learn.py`：write-token 保护 + JSON body 校验 + learn submitter 已落地

**当前请求面说明**：
- 允许的请求字段是现有 learn capture / 选项字段：`revision`、`last`、`since`、`author`、`staged`、`unstaged`、`include_untracked`、`patch`、`compare`、`compare_dir`、`patch_url`、`dry_run`、`force_learn`、`use_graphify`、`lang`、`privacy_mode`
- `compare` / `compare_dir` 需要 2 项 path array
- `patch="-"` 在 serve 层明确拒绝，避免后台任务读取进程 stdin

§9.4 中 `/api/tasks*` 四个端点标注为 **unstable，不纳入稳定合约**。

### 9.11 Backend review hardening（2026-04-30）

本轮只记录已经由代码和测试验证的收口项：

- `/api/auth/token` 保持 GET 兼容，并新增 POST；两者都需要同源浏览器信号。它仍不是 one-time nonce / 登录态设计，前端后续应迁到 POST bootstrap。
- 默认拒绝 `Forwarded` / `X-Forwarded-*` / `X-Real-IP` 代理痕迹头，避免在 localhost-only 模型里误信任代理来源。
- learn 主链的取消清理继续在 `repo_write_lock` 内执行；Step 10 `append_concepts()` 之后视为发布边界，late cancel 不再回滚已发布 run。
- `TaskRunner.shutdown()` 不再取消已经进入 draining 的 thread-backed worker；`POST /api/tasks/{task_id}/cancel` 已覆盖真实 thread-backed `/api/learn`。
- watcher stop timeout 会暴露 `restartable` / `stop_timed_out`，供前端或调试界面展示真实状态。
- FSRS 的 `stability` / `difficulty` 继续允许 `None -> 0.0` 作为新卡快照语义，但拒绝 `NaN` / `Inf`。
- contracts DTO 中的 `run_id` / `task_id` / `event_id` / `claim_id` / `card_id` 拒绝空字符串；`source_ref` 等历史引用字段保持兼容。

本轮后端回归基线：`pytest tests -q -p no:cacheprovider` = `1501 passed, 1 skipped`，`ruff check src tests` 通过，`pyright` = `0 errors`。只对本轮 touched files 跑了 `ruff format --check`；全仓 format 仍有既有 `src/ahadiff/graphify/parser.py` 重排遗留，不属于本轮改动。
