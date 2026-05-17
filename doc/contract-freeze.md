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
- Phase 2.5 只在同一 improve session 内连续两次 `discard` 后触发一次，且每个 session 最多一次
- 当前运行时不单独写 `status=phase25_rewrite` 事件；Phase 2.5 的最终结果仍回到 improve 链路，通过写 `targeted_verify`，不通过写 `discard`，并在最终事件的 `note_json` 中记录 `phase25=true`、`phase25_note`、`stash_ref` 与 `trigger_reason`
- `phase25_rewrite` 仍保留为 contract status 值，用于兼容旧数据或后续显式事件语义；当前代码和测试不把它作为 Phase 2.5 的实际落库事件

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
- `ReviewAnswer = easy | good | hard | wrong`
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
- `prompts/*.md` 是 improve loop 唯一允许写入的命名空间，但实际可写白名单只包含 `lesson_generate.md`、`lesson_hint.md`、`lesson_compact.md`、`quiz_generate.md`、`claim_extract.md`；`eval_judge.md` 是 packaged prompt resource，用于可选 LLM judge，不属于 improve loop 可写面；`prompts/improve_program.md` 为 human-written immutable state machine，不属于 improve loop 可写面

### 3.3 ResultEvent / result_events

`result_events` 是物理事件表，SQLite 是唯一真相源；`results.tsv` 只是导出视图。

补充冻结：

- `event_type=learn` 是 learn ratchet 的基线 lane；`score` / `verify` 只做临时评估，不参与 learn baseline 选择
- `prompt_version` 记录的是 **AhaDiff 自带 prompt 资源** 的 tree hash：source checkout / improve worktree 读取该 checkout 内的 `src/ahadiff/prompts`，wheel 安装态读取包内 `ahadiff/prompts`；目标仓库顶层自己的 `prompts/` 不参与哈希
- `note_json` 允许记录 ratchet 原因、learnability metadata 和 `degraded_flags`

### 3.3.1 `judge.json`（可选 LLM judge artifact）

`score.json` 仍是 deterministic evaluator 的发布评分，`judge.json` 只在配置了 `judge_provider` 的 learn run 中额外生成。它不替代 `result_events`，用于保存一次 LLM-as-judge 的旁路评分证据。

冻结字段：

- `artifact = "llm_judge"`
- `schema_version`
- `run_id`
- `source_ref`
- `source_kind`
- `model_id`
- `provider_class`
- `prompt_fingerprint`
- `eval_bundle_version`
- `overall`
- `dimensions`（8 维，字段与 rubric 维度一致）
- `usage.input_tokens`
- `usage.output_tokens`
- `finish_reason`
- `request_id`
- `notes`

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
- serve 的 review rate 和 signals SRS 路径在 active card 缺失时，可以在同一个 repo 写锁内从 `.ahadiff/runs/*/quiz/cards.jsonl` lazy import 后重试一次；坏 artifact 通过 `on_error` 跳过，不把导入失败暴露成用户评分失败
- run cards 导入会校验 state path 不穿 symlink/reparse；空 `cards.jsonl` 会把同 run 中不再出现的 active cards 标为 `stale/staleness_unknown`

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

- `provider_class = openai | openai_responses | gemini | anthropic | azure | newapi | lmstudio | ollama`
- `model_name`
- `base_url`
- `api_key_env`
- `max_output_tokens`
- `thinking_level = none | low | medium | high`
- `probed_max_context`
- `probed_tpm`
- `probed_rpm`
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

角色模型解析：

- `generate_provider` / `judge_provider` 分别选择生成与评判 provider。
- `generate_model` / `judge_model` 的非默认配置会覆盖 provider alias 中的 `model_name`。
- 未配置 `judge_provider` 时，learn pipeline 不运行 LLM judge，也不写 `judge.json`。

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
- `GET /api/ratchet/transparency`
- `GET /api/review/queue`
- `POST /api/review/rate`
- `GET /api/config`
- `GET /api/doctor`
- `GET /api/install/targets`
- `POST /api/install/:target/preview`
- `POST /api/install/:target`
- `POST /api/install/:target/uninstall`
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
- `LearnabilityInfo`：`score: float(0..1)`、`threshold: float(0..1)`、`skip_lesson_quiz: bool`、`reasons: list[str]`
- `QuizConfig`：`quiz_question_count: int(1..10)`，默认 `3`
- `ConfigResponse`：除 provider / privacy / capture / learn / llm 外，必须包含 `quiz: QuizConfig`
- `RunArtifactEnvelope`：`run_id`、`artifact_type`、`content`、`content_lang: Literal["en","zh-CN"] | None`
- `RatchetHistoryEntry`
- `RatchetTransparencyResponse`：从 `review.sqlite/result_events` 投影最近结果行，并从 `benchmarks/manifest.json` 与 `.ahadiff/benchmarks/local-report.json` 投影 benchmark 摘要；结果行的 `note_json` 只暴露 allowlist 字段
- `InstallManifestActionSummary`：`action`、`file_strategy: Literal["generated","user-managed"]`、`path`
- `InstallManifestSummary`：`preview`、`write`、`uninstall`
- `InstallTargetSummary`：`name`、`display_name`、`detected`、`platform_supported`、`status`、`description`、`install_command`、`uninstall_command`、`manifest`、`manifest_hash`、`manifest_error`、`error_message`
- `InstallTargetPreviewResponse`：`target`、`manifest_hash`
- `InstallTargetMutationResponse`：`target`、`operation`、`updated`、`updated_paths`、`manifest_hash`

Stage 0 同时冻结最小写请求 DTO：

- `SetLocaleRequest`
- `InstallPreviewRequest`：`force`、`layer2`
- `InstallMutationRequest`：`force`、`layer2`、`confirmed_manifest_hash`
- `LearningSignalRequest`
- `MarkWrongRequest`
- `ReviewSignalRequest`
- `HelpfulnessRequest`

说明：

- Request DTO 只冻结最小标识字段；后续 payload 扩展不能破坏现有字段语义
- `run_id` / `task_id` / `event_id` / `claim_id` / `card_id` 这类公开标识字段必须拒绝空字符串；`source_ref` 这类历史引用字段不在本轮一刀切收紧范围内
- `GET /api/install/targets` 仍是只读展示 contract；浏览器真实写入只能走 `POST /api/install/:target` 和 `POST /api/install/:target/uninstall`
- install 写操作只允许当前 `ahadiff serve` repo，不接受浏览器传入任意 `repo_root` / path；写入必须带 `X-AhaDiff-Token`，继续走 Origin / Referer 写保护、localhost-only 边界和 repo 写锁
- manifest preview 是确认门：前端先拿 `manifest_hash`，install / uninstall 时必须回传 `confirmed_manifest_hash`；hash 不匹配时拒绝写入
- `GET /api/ratchet/transparency` 当前也要求 `X-AhaDiff-Token`，因为它会投影 benchmark report 摘要；manifest/report 读取必须经过 no-follow、regular-file、reparse、hardlink、大小和 JSON object guard，缺失或损坏时返回 warning 而不是 mock 数据
- `RunDetail.learnability` 是可选字段，用于把 run metadata 中的 learnability gate 结果投影给 viewer；旧 run 没有该 metadata 时必须保持 `null` / omitted 兼容
- `lesson` / `claims` / `quiz` artifact 缺失时返回 404 `artifact_not_found`，不再用 400 表示“artifact 不存在”；这不改变 run 本身不存在时的 404 语义
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

- `ahadiff learn` 自动检测外部 `graphify` CLI；存在时先执行 `graphify update <repo>`，成功后 `force=True` 导入新的 `graphify-out/graph.json`
- 外部 `graphify` CLI 不存在时，仍会检测既有 `graphify-out/graph.json`，产物存在则导入 repo-level context
- 外部 `graphify` CLI 存在但 update 失败时，只按可选增强降级，不把旧图当作本轮已刷新图导入
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
- `GET /api/graph/status` — Graphify 当前状态；payload 包含 `enabled` / `source_exists` / `has_graph` / `freshness` / `node_count` / `edge_count` / `source_path` / `provenance`（`GraphProvenance | null`，含 `graph_sha256`/`import_time`/`parser_version`；`graph_sha256` 必须是 64 位小写 hex，`import_time` 必须是 ISO 8601 datetime）
- `GET /api/graph/concepts` — ConceptGraph 前端 DTO；返回 sanitized `nodes` / `edges` + `status`，edge 可带 allowlist 内的 `confidence`，node `metadata` 继续透传；它不是完整 Graphify provenance API
- `POST /api/graph/refresh` — 受写 token 保护；在 repo 写锁内重新导入 Graphify artifact，校验 `.ahadiff/graphify/graph.json` 的 symlink/reparse 边界，返回 `status` / `nodes` / `edges`
- `POST /api/db/check` — 受写 token 保护；在 repo 写锁内调用 read-only `check_review_db(..., ensure_schema=False)`，不初始化空库，返回 `healthy` / `schema_version` / `quick_check` / `event_count` / `card_count`
- `PUT /api/config` — 配置更新
- `POST /api/learn` — 提交后台 learn 任务；当前返回 `202 {"task_id": ...}`，进度/取消走 `/api/tasks*`；写请求有 in-memory 10 req/min 滑动窗口限流，429 返回 `{"error":"rate_limited","retry_after":...}` 并带 `Retry-After`；submit 会预检 repo 写锁；submit/estimate 都会校验 workspace-only `against_spec` 和 `since` / `author` git option 注入边界
- `GET /api/tasks` — **stable**，参见 §9.10
- `GET /api/tasks/{task_id}` — **stable**，参见 §9.10
- `POST /api/tasks/{task_id}/cancel` — **stable**，参见 §9.10
- `GET /api/tasks/{task_id}/progress` — SSE 事件流（`TaskProgressEvent` JSON data payload 稳定；SSE framing text 为实现细节），**stable**，参见 §9.10

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
| **PUT /api/config** | ✅ persistent | 支持 `lang`/`privacy_mode`/`generate_provider`/`generate_model`/`judge_provider`/`judge_model`/`serve_port`/`capture`/`llm`/`learn`/`quiz` 字段，`lang` 同时更新 session locale，其余字段持久化到 per-repo `.ahadiff/config.toml`。`capture` 含 `max_files`/`hard_limit`/`max_patch_bytes`/`file_ranking`；`llm` 含 `input_token_budget`/`output_token_budget`/`request_timeout_seconds`/`max_concurrent`/`retry_attempts`；`learn` 含 `learnability_threshold`/`desired_retention`；`quiz` 只接受 `quiz_question_count`，范围 1-10。所有字段带范围校验 |
| **GET /api/graph/status** | ✅ 已接线 | 以 workspace root 为基准探测 raw `graphify-out/graph.json` 是否存在；当前 node/edge 统计和 `source_path` 读取的是 imported `.ahadiff/graphify/graph.json`，返回 `enabled/source_exists/has_graph/freshness/node_count/edge_count/source_path(relative)` |
| **GET /api/graph/concepts** | ✅ 已接线 | 从 imported `.ahadiff/graphify/graph.json` 投影前端 ConceptGraph 所需的 sanitized nodes/edges/status；node `metadata` 继续透传，edge `confidence` 只接受 `EXTRACTED` / `INFERRED` / `AMBIGUOUS`，非法值不出现在响应里；前端已从 SVG + d3-force 迁到 `react-force-graph-2d` Canvas renderer，并保留 Graph/List、大图默认 List、Full graph、节点详情和可访问列表 fallback；Graphify import provenance 与 per-run `graphify_context.json` artifact 已有后端接线；完整 source/provenance UI 和真实大仓 signoff 仍属后续工作 |
| **POST /api/graph/refresh** | ✅ 已接线 | 写 token + Origin/Referer 写保护 + repo 写锁；调用 `import_graphify_artifact(root, force=True)` 重新导入 raw Graphify artifact，并在导入前后用 no-symlink state-path guard 校验 `.ahadiff/graphify/graph.json`；request timeout 对精确路径 `/api/graph/refresh` 放宽到 600s |
| **POST /api/db/check** | ✅ 已接线 | 写 token + Origin/Referer 写保护 + repo 写锁；使用 `check_review_db(state.review_db_path, ensure_schema=False)` 走 read-only SQLite 检查，不调用 `_ensure_schema()`，缺表时计数为 0，不顺手创建或迁移空库 |
| **POST /api/learn** | ✅ 已接线 | `core/orchestrator.py` 从 `cli.py` 抽出 learn 主链；route 只接受安全 capture / learn 选项，返回 `202 {"task_id": ...}`，provider override 不从 HTTP 暴露；当前有 10 req/min 写限流，401/403/404 不消耗额度；提交前预检 repo 写锁、workspace-only `against_spec` 和 `since` / `author` leading dash / 控制字符 |
| **GET /api/export/apkg** | ✅ 已接线 | 写 token + Origin/Referer 写保护；读取 review.sqlite active cards 并生成 `ahadiff_review.apkg`；依赖可选 `genanki`，缺依赖返回 `501 FEATURE_UNAVAILABLE`；空卡组允许导出，上限 10,000 张 active cards |
| **medium APIs** | ✅ 全部真实接线 | search/audit/mastery/weak/alignment/learning stats 均查 SQLite/JSONL，无 mock |
| **/api/tasks*** | ✅ stable product API | 2026-05-02 R0 决策提升为稳定 API（§9.10）；`TaskInfoResponse` 全部字段、`TaskErrorCode`、`RecoveryHint`、`TaskProgressEvent` JSON payload 均为稳定合约；SSE framing text 为实现细节 |

### 9.9 Serve 异步 IO 策略（1B）

**裁决**：维持 `anyio.to_thread.run_sync` + 同步 `sqlite3` 的 threadpool 模式，不引入 `aiosqlite`。

**依据**：
- 28 处 `to_thread.run_sync` 调用已正确隔离所有阻塞 IO
- 读远多于写（21 读 / 5 写），WAL 模式下本地 SQLite 亚毫秒级响应
- 写路径受 `portalocker` 文件锁序列化，是同步阻塞调用 — aiosqlite 无法绕过
- 改写量：`database.py` 1700+ 行 + 6 个 route 文件，收益极低
- `benchmarks/scripts/bench_sqlite_queries.py` 已验证核心查询 p50/p95 性能基线

### 9.10 /api/tasks* 合约提升（3C → 稳定产品 API）

**裁决**（2026-05-02 R0 决策）：`/api/tasks*` 路由提升为 **stable product API**。

**当前状态**：`POST /api/learn` 已经接到真实 learn 主链，会返回 `202 {"task_id": ...}`；进度查看和取消分别走 `GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/progress` 和 `POST /api/tasks/{task_id}/cancel`。

**提升依据**：
- `TaskInfoResponse` 已在 docstring 中声明 stable fields（task_id/task_type/status/progress/error/error_code/recovery_hint/created_at/started_at/completed_at/elapsed_seconds/result_summary）
- 前端 Zod strict schema 严格消费全部字段，破坏性变更即刻打破产品
- 59 后端测试 + 42 前端 unit 测试覆盖 tasks 契约
- SSE progress 端点已被前端以 EventSource 优先消费，并保留 polling fallback；JSON data payload 由 `TaskProgressEvent` 表达，SSE framing text 仍不作为产品文案承诺
- Rate limiting (10 req/min) + admission control (max 1 pending) 已就位

**稳定边界**：
- **稳定**：5 个 REST 端点（POST /api/learn + 4 个 /api/tasks*）的路径、HTTP method、请求/响应 schema
- **稳定**：TaskInfoResponse 全部字段、TaskErrorCode 枚举、RecoveryHint 枚举、TaskSubmitResponse、TaskCancelResponse、TaskProgressEvent JSON payload
- **实现细节（可变）**：SSE framing text 的具体拼接、队列容量数值、polling 间隔建议、429 retry_after 秒数

**当前 runtime 事实**：
- `GET /api/tasks` / `GET /api/tasks/{task_id}` 的 payload 已经带 `error_code`，类型收紧为 `TaskErrorCode | None`
- `TaskInfoResponse` 的稳定字段包含 `task_id`、`task_type`、`status`、`progress`、`error`、`error_code`、`recovery_hint`、`created_at`、`started_at`、`completed_at`、`elapsed_seconds`、`result_summary`
- `RecoveryHint` 取值为 `"retry" | "check_config" | "check_permissions" | "dismiss" | "none"`；它只在失败任务有可判定恢复动作时填充，其他状态可为 `None`
- raw task `result` 不对前端暴露；完成态使用 `result_summary`
- 当任务进入运行态后，route 侧会额外投影 `elapsed_seconds`
- `TaskRunner` 默认 scheduler timeout 是 600 秒，可由 `AHADIFF_DEFAULT_TASK_TIMEOUT_SECONDS` 覆盖
- `TaskRunner` 支持 per-task `task_timeout_seconds` override
- `POST /api/learn` 当前不再关闭 timeout；它走 `TaskRunner` 的默认 timeout 语义
- `POST /api/learn` 的 429 `rate_limited` 是 submit-layer HTTP 状态，不进入 `TaskErrorCode`；前端按 `retry_after` / `Retry-After` 展示等待文案
- thread-backed learn task 被取消时，取消信号会传进 `run_learn_pipeline()` 的 `is_cancelled` 回调；超时进入 draining 的 worker 不会被 `shutdown()` 提前 untrack
- 前端 EventSource client 对瞬断做最多 5 次后台重连，按 1s/2s/4s/8s/16s 退避；这只是 client 恢复策略，不改变 SSE payload 合约

**实现文件**：
- `core/task_runner.py`：TaskRunner 类完整保留，Phase 6B 直接使用
- `serve/routes_tasks.py`：路由实现完整保留，Phase 6B 启用
- `serve/app.py`：路由注册；REST 端点路径/method/schema 属稳定合约，内部调度逻辑可变
- `serve/routes_learn.py`：write-token 保护 + JSON body 校验 + learn submitter 已落地

**当前请求面说明**：
- 允许的请求字段是现有 learn capture / 选项字段：`revision`、`last`、`since`、`author`、`staged`、`unstaged`、`include_untracked`、`patch`、`compare`、`compare_dir`、`patch_url`、`changed_paths`、`against_spec`、`spec_semantic_review`、`dry_run`、`force_learn`、`use_graphify`、`lang`、`privacy_mode`
- `compare` / `compare_dir` 需要 2 项 path array
- `changed_paths` 只用于工作区类输入的路径范围，不表示前端可以传任意 repo 外路径；serve 层只接受 repo-relative path scope，拒绝空值、绝对路径、Windows drive / UNC、`.` / `..`、`.git` / `.ahadiff` 和控制字符
- `against_spec` 只接受当前 workspace 内本地文件路径；URL、控制字符、repo 外路径和 symlink / special-file 路径都拒绝，并统一走 `INPUT_VALIDATION`
- `since` / `author` 不能以 `-` 开头，不能包含 `\x00-\x1f` / `\x7f` 控制字符；capture 层也有同一层防护，避免绕过 serve route
- `patch="-"` 在 serve 层明确拒绝，避免后台任务读取进程 stdin

§9.4 中 `/api/tasks*` 四个端点已于 2026-05-02 R0 决策提升为 **stable product API**。

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

### 9.12 Phase 6B rate limit / recovery hardening（2026-05-02）

本轮只记录已经由代码和测试验证的收口项：

- `WriteRateLimitMiddleware` 注册在 serve 中间件栈，当前只限制 `POST /api/learn`；key 使用 token 前缀或 client host，窗口为 60 秒内最多 10 次。
- 认证/授权/路径类失败（401/403/404）不会消耗 `/api/learn` 写额度；真正进入提交面的请求才保留在窗口里。
- 429 response body 为 `{"error":"rate_limited","status":429,"retry_after":N}`，并同步写 `Retry-After: N`。
- `TaskErrorCode` 冻结为 `network_error` / `timeout` / `config_error` / `permission_error` / `claim_error` / `lesson_error` / `quiz_error` / `learnability_error` / `cancelled` / `internal_error`。
- 未知 task error code 会在后端序列化时收敛为 `internal_error`，避免把任意内部字符串变成前端契约。
- 前端 `taskInfoResponseSchema` 与 `TaskInfoResponse` 对齐，`recovery_hint` 作为稳定可选字段；LearnTaskBanner 用 `recovery_hint` 控制 Retry，并用 `Learn.rate_limited` 渲染 429。

本轮实测：targeted parser / judge / orchestrator / lesson 回归 `230 passed in 11.67s`；后端全量 `pytest --tb=short` = `1993 passed, 1 skipped in 178.87s`；`ruff check` / `ruff format --check` / `pyright` / `git diff --check` 通过。真实 WebUI learn run 使用 `gpt-5.5` 生成和 judge，`score.json=94.96/PASS`，`judge.json model_id=gpt-5.5`，浏览器 console 无 error/warn；live judge smoke `1 passed in 4.30s`。coverage、前端 build 和全量 Playwright 未在本轮后重跑。

### 9.13 APKG export 与 FEATURE_UNAVAILABLE（2026-05-12）

本轮只记录已经由代码和测试验证的收口项：

- `GET /api/export/apkg` 是 WebUI/serve 下载能力，不新增 CLI `export-apkg` 命令，也不是 AnkiConnect 自动写入。
- APKG export 只读取 `cards` 表中 `card_state='active'` 的 review cards；空卡组会生成可下载的空 deck；超过 10,000 张 active cards 会拒绝导出，避免本地请求一次性生成过大的包。
- `genanki` 是 optional extra：用户需要安装 `ahadiff[anki]`。缺依赖时 route 返回统一错误 payload，`status=501` 且 `error_code=FEATURE_UNAVAILABLE`。
- `FEATURE_UNAVAILABLE` 是稳定 `ErrorCode`，用于“服务可用，但本地缺可选依赖或能力未安装”的情况；它不表示鉴权失败，也不表示用户输入错误。
- APKG note front/back 会做 HTML escape；front 为空时拒绝导出，避免把不可复习的卡片塞进 deck。

本轮实测：`tests/unit/test_apkg_export.py` 覆盖 active-card export、空 deck、empty front、10,000+ 上限、缺 `genanki` 的 501、旧 schema storage error 和 route 下载；后续 v1.1 security / cross-platform follow-up 后完整 unit suite 为 `2188 passed`，`ruff check`、`ruff format --check` 和 `pyright` 通过。

### 9.14 v1.1 security / cross-platform contract 收口（2026-05-12）

本轮只记录已经由代码和测试验证的收口项：

- git revision / pathspec 调用补 `--end-of-options`，并拒绝 leading dash 输入；git subprocess env 清洗按大小写不敏感方式移除 `GIT_*`，再设置 `GIT_TERMINAL_PROMPT=0`。
- `--patch-url` 拒绝 URL userinfo；这是下载入口的边界，不等同于 provider URL helper 的全部 SSRF 边界。
- `safe_json_loads()` 默认拒绝超过 50 MiB 的输入；调用方仍可传更小上限。
- MCP stats 动态表名走 allowlist；这一轮 read-only stdio MCP server 仍是 6 个工具，后续 9.15 已升到 7 个工具。
- prompt injection 检测补 soft hyphen、variation selectors 和 TAG chars；claim artifact 读取补 no-follow、Windows reparse、hardlink、大小和 TOCTOU guard。
- `/api/improve/preflight` 改用共享 git wrapper，避免污染环境隐藏 dirty prompt 状态。
- 项目根新增 `.gitattributes`：文本 LF，常见图片、字体、视频和 PDF 标记 binary。
- viewer 已配置 browserslist 和 Vite `build.target`；前端复制逻辑收敛到共享 `copyToClipboard()`，支持 Clipboard API、textarea fallback、SSR/sandbox guard 和焦点恢复。

本轮实测：后端 unit `2188 passed`；`ruff check`、`ruff format --check`、`pyright` 通过；viewer typecheck、Vitest `318 passed`、build 通过；`git diff --check HEAD` 通过。integration、eval、live judge、wheel、完整 Playwright 和远端 GitHub Actions 未在本轮重跑。

### 9.15 Phase 2 本地学习面收口（2026-05-12）

本轮只记录已经由代码和测试验证的收口项：

- `review.sqlite` schema 升到 v10，新增 `concept_status` 和 `concept_lint_runs`。`ahadiff concepts lint` 当前只实现 deterministic 模式，会标记 orphan、deleted-file stale、line drift 和 contradicted claim；LLM-assisted maintenance loop 仍未落地。
- `ahadiff export preview` 和 `POST /api/export/preview` 生成本地 static preview：`README.txt`、`index.html`、`data/run.json`、`data/concepts.json`、`manifest.json`，并按 manifest allowlist / size / hash 写 deterministic zip。API 固定 strict-local，CLI 可传 privacy mode。
- Challenge loop 默认 disabled。CLI 只有 `build` / `status`；serve 提供 build/get/advance/abort/review/feedback 六个 routes，禁用时返回 `FEATURE_UNAVAILABLE`。review 是 deterministic learner diff 与 canonical diff gap 对比，不执行 shell、测试或用户代码。
- MCP read-only server 现在是 7 个工具，新增 `ask_lesson`。它只读取 finalized run 的 lesson 文件和 claims，用本地 token overlap 返回片段，不调用 LLM。
- APKG export 已改用 packaged CSS 资源；GUID 当前仍是 `genanki.guid_for(card_id)`，stable namespace GUID 未落地，不能写成已完成。
- 本轮 adversarial review 又补上 Challenge rebuild/review 原子性、manifest 有限数校验、export preview noindex / 注入重扫 / stale cleanup TOCTOU、MCP `ask_lesson` 输出契约和只读路径 guard、concept lint JSONL 读取与路径归一化、review 评分非有限数拒绝。
- serve 当前为 69 个 concrete `/api/*` routes + 1 个 catchall；前端为 16 页面、62 个生产 TSX、46 个 CSS，i18n scalar keys `1262/1262`。

本轮实测：后端 unit `2409 passed`；integration `11 passed`；eval `9 passed`；`ruff check`、`ruff format --check`、`pyright` 通过；viewer typecheck、Vitest `326 passed`、build 通过；i18n `1262/1262`；`git diff --check HEAD` 通过。live judge、wheel、完整 Playwright 和远端 GitHub Actions 未在本轮重跑。

### 9.16 Run Detail learnability 与学习 artifact 404（2026-05-13）

本轮只记录已经由代码和目标测试验证的契约收口项：

- `RunDetail` 新增可选 `learnability` 字段，类型为 `LearnabilityInfo | None`。旧 run 没有 metadata 时继续返回 `None`，不破坏旧数据。
- `LearnabilityInfo` 只包含 `score`、`threshold`、`skip_lesson_quiz` 和 `reasons`。投影逻辑只接受有限数值、真实 boolean 和 `list[str]` reasons；metadata 类型不匹配时不投影。
- `GET /api/run/{run_id}/lesson`、`/claims`、`/quiz` 在 artifact 缺失时返回 404 `artifact_not_found`。这三个 artifact 是 run 下的可选学习产物，缺失不等同于请求参数错误。
- 前端 search schema 保留后端 `primary_key` 作为稳定 result id，graph node 的 Concepts Ledger 聚焦文本走单独 `focusText`，避免把 HTML 片段或 unsafe hash 当作概念名。
- ConceptGraph 与 ConceptLedger 的聚焦契约按 id、name 或 normalized ledger key 匹配；同一 hash 跳转时前端会手动派发一次 `hashchange`，让 `#/concepts?tab=ledger&focus=...` 能重复聚焦同一概念。

本轮实测：后端目标 pytest `199 passed`；目标 pyright `0 errors`；目标 ruff check / format check 通过；viewer typecheck 通过；前端 Vitest `336 passed`；SearchOverlay Playwright `60 passed`；i18n `1271/1271`；`git diff --check HEAD` 通过。integration、eval、live judge、wheel、viewer build、完整 Playwright 和远端 GitHub Actions 未在本轮重跑。

### 9.17 Warm v6 / Blueprint current-truth 收口（2026-05-14）

本轮只记录已经由代码和本轮验证支撑的收口项：

- Diff Viewer 新增 Unified / Split 两种视图。Split 视图按 old/new 两侧展示删除线和新增线，claim 证据点、ClaimInspector 引用和跳转都会保留 side 信息；同一文件同一行的 old / new 引用不会互相覆盖。
- Dashboard 的 spec alignment KPI 不再用所有 result_events 的历史均值冒充当前状态；它读取 finalized run 的 `score.json`，遇到缺库、坏 JSON、symlink/reparse/hardlink 或超限文件时降级为空值。
- `GET /api/graph/concepts?focus=` 会在正常 `limit` 之外补回聚焦节点，Concepts Ledger 的 graph link 只使用真实 `graphify_node_id`；找不到可用 graph node 的旧概念不会显示假链接。
- Quiz 生成契约把 `quiz_kind` 收窄为 `guided` / `recall` / `transfer`；learn 主链在生成 cards 后会导入 `review.sqlite`，失败只记 warning，不阻断 lesson/quiz artifact。
- 当前 serve 面是 70 个 concrete `/api/*` routes + 1 个 catchall，另有 `/healthz`。
- 本轮复核 `AhaDiff-Blueprint.html` 后，只把当前代码支持的八层架构、diff capture、8 维评估、Guide/Onboarding、导出、MCP 和 opt-in Challenge 写成已实现；`learn --open`、Amp/Jules/Junie install target、CherryIN provider、DOMPurify 依赖和固定 29 步流程没有代码支撑，不能写成已完成。

本轮实测：后端 unit `2434 passed`；integration `11 passed`；eval `9 passed`；`ruff check`、`ruff format --check`、`pyright`、wheel build 通过；viewer typecheck、Vitest `344 passed`、build 通过；完整 Playwright `2735 passed, 10 skipped`；i18n `1392/1392`；`git diff --check HEAD` 通过。live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.18 Learnability skip 持久化、quiz 数量和 Diff/Review/Lesson 收口（2026-05-15）

本轮只记录已经由代码和本轮验证支撑的收口项：

- learnability gate 判断 `skip_lesson_quiz=True` 且非 dry-run 时，learn 主链仍会发布一个最小 finalized run：写入 result event、`score.json` 和 `finalized.json`。这个 run 不伪造 lesson/quiz artifact；对应 artifact 缺失仍按 §9.16 返回 404 `artifact_not_found`。
- 最小 run 发布失败时必须回滚刚写入的 result event，避免 SQLite 中出现没有 `score.json` / `finalized.json` 的可见 run。CLI 直跑 `ahadiff learn` 和 serve/orchestrator 路径走同一套发布语义。
- `quiz.quiz_question_count` 成为稳定配置项，默认 `3`，范围 `1..10`。配置值会进入 quiz prompt、quiz prompt fingerprint、CLI learn 主链、`GET/PUT /api/config` 和 Settings Preferences。
- Review open-answer 卡片的普通 reveal 不再记为 quiz peek；这只影响当前 session 内的前端状态，不改变 review.sqlite 的 FSRS 评分语义。
- Diff Viewer 在 Unified / Split 基础上补文件摘要 Prev/Next、`+` / `-` 行标记、claim 选中后的自动滚动和窄屏 / forced-colors 样式。Split 下行标记仍保留左右分侧语义。
- Lesson 页继续把 run detail 404 视为 `fetch_failed`；只有 lesson artifact 缺失才展示 skipped empty state。这与 skipped-run 最小发布配套，避免把 run 不存在误报成“跳过课程”。
- 当前 serve 面仍是 72 个 concrete `/api/*` routes + 1 个 catchall，另有 `/healthz`。

本轮实测：后端 unit `2502 passed`；integration `11 passed`；eval `9 passed`；`ruff check`、`ruff format --check`、`pyright`、wheel build 通过；viewer typecheck、Vitest `350 passed`、build 通过；完整 Playwright `2855 passed, 10 skipped`；i18n `1447/1447`；`git diff --check HEAD` 通过。live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.19 Diff claim 选中视觉和 Welcome lesson 折叠收口（2026-05-15）

本轮只记录已经由代码和本轮验证支撑的 `viewer/` 收口项：

- Diff Viewer 的 claim 选中态不再用 accent ring，改为柔和的蓝灰行级色带；Unified / Split 的新增/删除选中底色都保留 add/del 语义。
- claim dot 的 hover / focus-visible 样式在 Unified 和 Split 下保持一致；header 增加圆点说明，选中 claim 时会显示“高亮行是代码证据”的提示。
- Welcome 的 hero lesson demo 按 H2 分组为 `<details>/<summary>` 折叠面板；H2 前的 preamble 会保留；没有 H2 时回到普通 prose；H3 仍留在当前 H2 section 里。
- Welcome demo 面板有高度上限；当页面拿到最新 finalized run 时，会在 lesson demo 下方链接到对应 Lesson。
- `renderMarkdownProse` 的签名未变；新增的 `renderMarkdownCollapsible` 是单独 helper，现有 Lesson 调用不受影响。

本轮实测：后端 unit `2502 passed`；viewer typecheck 通过；Vitest `35 files, 353 tests passed`；viewer build 通过；i18n `1449/1449`；`git diff --check HEAD` 通过。integration、eval、ruff/format/pyright、wheel、完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.20 Learn Mode 输入校验与 Diff claim 聚合收口（2026-05-15）

本轮只记录已经由代码和本轮验证支撑的安全 / a11y / UI 收口项：

- `src/ahadiff/git/capture.py` 和 `src/ahadiff/serve/routes_learn.py` 对 `since` / `author` 使用同一类 git option guard：拒绝 leading dash，拒绝 `\x00-\x1f` / `\x7f` 控制字符。serve submit 与 estimate 都会在 route 层返回 `INPUT_VALIDATION`。
- `against_spec` 仍是 workspace-local 文件路径参数，不接受 URL、控制字符、repo 外路径、symlink 或 special-file 路径；合法值会在 route 层解析成 safe path 后交给 orchestrator。
- `/api/learn` 进入 `TaskRunner` 前会做 repo write lock 预检；已有 learn / graph / install 等写操作持锁时，submit 返回 `LOCK_CONFLICT`，不排队制造后续失败。
- Learn Mode Dialog 的 path scope 只用于 working / unstaged / staged，前端拒绝 `..`、绝对路径、Windows drive path、UNC path、控制字符和超过 500 条路径。它不改变 capture 层的 literal pathspec 边界。
- Learn Mode Dialog 的 `patch_url` 只允许无 username/password 的 `http:` / `https:`；`data:`、`blob:`、`file:`、`javascript:` 等协议都在前端拒绝。`revision` 最长 255，拒绝 leading dash、控制字符和非预期字符。
- Learn Mode Dialog 关闭时会 abort estimate 和 pending learn request；`learn-store` 的 `pendingPayload` 会去掉 inline `patch` 和 `patch_url`，避免 UI 状态里保留 patch 内容或远端 URL。
- Dialog 暴露 `aria-busy` 和 polite live region；overlay 不再使用 `role="presentation"`；print CSS 会隐藏 Learn dialog；forced-colors 下 tile focus 仍可见。
- Diff Viewer 不再为同一行渲染多个水平堆叠 claim dot。现在按 verdict severity 聚合为单个 indicator；多 claim 时显示 count badge；未选中 claim 时点击默认打开最高严重度 claim，和圆点颜色一致。
- `VERDICT_SEVERITY` 当前顺序是 `verified < weak < not_proven < contradicted < rejected`，用于聚合优先级和默认选择，不改变 claim artifact 原始状态。

本轮实测：`UV_CACHE_DIR=/tmp/ahadiff-uv-cache uv run pytest tests/unit/test_routes_learn.py tests/unit/test_git_capture.py -q` = `199 passed`；后端 unit `2513 passed`；integration+eval `20 passed`；`ruff check`、`ruff format --check`、`pyright`、wheel build 通过；viewer typecheck、Vitest `35 files, 360 tests passed`、viewer build 通过；i18n `1454/1454`；`git diff --check HEAD` 通过。完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.21 Diff claim navigation sticky 收口（2026-05-16）

本轮只记录已经由代码和本轮验证支撑的 `viewer/` 收口项：

- `.diff-page` 不再用 `overflow: hidden` 截断 sticky 右侧栏；长 diff 跳转时 ClaimInspector 仍停在视口内。
- ClaimInspector 选中卡片的自动滚动只作用于右侧栏自身，不再调用会影响整页的 `scrollIntoView()`。
- 选中详情和证据 / 跳转按钮仍使用原有视觉结构，但渲染在对应 claim 卡片下方，用户不用回到列表顶部查看详情。
- 选中 claim 的源码块预览现在也渲染在对应 ClaimInspector 卡片里，使用 `.claim-inspector__source-preview-code` 展示片段和跳转按钮；旧的底部 `.diff-page__selected-hunk` 面板已移除。
- 旧浏览器会话可能仍被 Workbox service worker / cache 托管旧 bundle；验证当前 build 时需要清理缓存或硬刷新。

本轮实测：目标 Vitest `2 files, 29 tests passed`；viewer typecheck；完整 Vitest `35 files, 362 tests passed`；viewer build；`git diff --check HEAD`；serve/browser cache-bust smoke 确认 `DiffViewerPage-CTH1QPRr.css` 已加载，`.diff-page` `overflowY=visible`，claim 021 跳到 `viewer/src/i18n/messages/en.json:565`，右侧 ClaimInspector 仍可见。后端、integration、eval、ruff/format、pyright、wheel、完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.22 Diff inline source preview / Welcome real-run preview（2026-05-17）

本轮只记录当前 `viewer/` 改动已经支撑的契约：

- Diff claim 的“看证据”路径以右侧 ClaimInspector 卡片为入口。用户点击任意 claim 后，状态、证据、相关概念、源码块预览和跳转按钮都在同一卡片附近展示；页面底部不再保留单独的 selected hunk 展示区。
- 源码块预览仍来自当前 diff 的 `sourceSnippets`，每条 preview 使用原始 line number 和 marker 格式化，不把 claim 文案当源码。
- Welcome/Landing 的学习入口会先显示当前 learn task 反馈；有刚完成 task 的 `run_id` 时优先读取该 run，其次才读取 latest finalized run。
- Landing 的 hero preview 使用真实 run 的 diff artifact 和第一个可用 lesson artifact（full → hint → compact）。当真实 run 缺 lesson 时，页面显示空状态并跳到 Run Detail，不回退到样例 lesson，避免把样例和真实 run 混在一起。

本轮实测：viewer typecheck 通过；前端 Vitest `35 files, 362 tests passed`；viewer build 通过；Diff Chromium E2E `1 passed`；Welcome Chromium E2E `4 passed`；i18n scalar keys `1490/1490`。一次并行 Playwright 启动因为两个 webServer 同抢 `5173` 失败，随后用 `AHADIFF_VIEWER_E2E_PORT=5174` 重跑 Welcome 通过。后端、integration、eval、ruff/format、pyright、wheel、完整 Playwright、live judge 和远端 GitHub Actions 未在本轮重跑。

### 9.23 Completion audit / 输入与本地文件边界收口（2026-05-17）

本轮只记录已经由代码和本轮验证支撑的后端 / 前端 / 文档收口项：

- `safe_sqlite_connect()` 在 Linux 上通过 nofollow fd 绑定打开 SQLite 文件，并校验主库实际路径；打开失败的错误路径也会做路径身份校验，避免 race 后把错误归到旧路径。
- compare input、Graphify source/imported graph 和 JSONL artifact 读取继续走 no-follow / regular-file / reparse / size / TOCTOU guard，本轮又明确拒绝 hardlink 文件，避免同一路径检查后被其它 link 身份混淆。
- provider URL 的私有地址判断收紧为 `not addr.is_global`。这会覆盖 loopback、private、link-local、multicast、reserved、CGNAT 等非公网地址；本地 provider discovery 仍走显式 local provider 入口，不靠公网 URL helper 放行。
- `POST /api/learn` 与 `POST /api/learn/estimate` 对 `changed_paths` 使用同一组 route 校验：拒绝空字符串、控制字符、绝对路径、Windows drive path、UNC path、`.` / `..` path part、`.git` 和 `.ahadiff`。合法路径仍作为 repo-relative path scope 交给 capture 层 literal pathspec 处理。
- 前端 API client 在 bootstrap token 和 raw fetch 中使用同源 absolute URL；token generation 变化会清理 pending bootstrap promise，避免旧请求拿到过期 token。
- provider model discovery 和 learn estimate 的前端响应都走 Zod schema 解析；Guide 页的 GPT-5.5 provider 命令补齐 `--provider-class openai_responses`，并统一使用 `gpt55` 示例名称。
- 新增 `docs/USER_GUIDE.zh.html` 作为自包含中文用户指南；`docs/VALIDATION_AUDIT.zh.md` 记录本轮 completion audit、真实验证、剩余门禁和复跑命令。

本轮实测：后端 unit `2530 passed`；integration+eval `20 passed`；`ruff check`、`ruff format --check`、`pyright`、wheel build 通过；viewer typecheck、lint、Vitest `36 files, 365 tests passed`、build 通过；完整 Playwright `2945 passed, 10 skipped`；real-serve `2 passed`；live judge `2 passed`；临时 repo GPT-5.5 provider test / live learn 通过；Linux SQLite `3.51.3` 目标 gate 通过；`git diff --check HEAD` 通过。推送后远端 Backend CI / Frontend CI / Pages runs 已触发，但 jobs 立即 failure，steps 为空且日志不存在，不计为代码验证通过；Windows 仍缺真实 runner 结果。
