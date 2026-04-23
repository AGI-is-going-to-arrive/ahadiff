# Learnability Gate + Claims Extract Runtime — 双轮对抗性交叉审查报告

> 日期: 2026-04-23
> 审查模型: Claude Opus 4.6 + Codex CLI (codex-plugin-cc) + Explorer Agent
> 审查轮次: 2 轮（R1 三代理并行 + R2 双路独立对抗 + 手工 PoC 验证）
> Verdict: **CONDITIONAL GO** — 2 High 必须先修

---

## 一、审查范围

### 已修改文件（git diff HEAD）

```
 M prompts/claim_extract.md         (+1 line)
 M src/ahadiff/claims/__init__.py   (+8 lines)
 M src/ahadiff/cli.py               (+174 lines)
 M tests/unit/test_claim_extract.py (+237 lines)
 M tests/unit/test_git_capture.py   (+47 lines)
```

### 新增文件（untracked）

```
?? src/ahadiff/claims/runtime.py
?? src/ahadiff/lesson/__init__.py
?? src/ahadiff/lesson/learnability.py
?? tests/unit/test_learnability.py
```

### 依赖检查范围

- `src/ahadiff/claims/{extract,verify,negative_scan,classify,schema}.py`
- `src/ahadiff/llm/{provider,schemas}.py` + `adapters/{openai,openai_responses}.py`
- `src/ahadiff/core/{config,paths}.py`
- `src/ahadiff/contracts/{claim_status,orchestrator}.py`
- `src/ahadiff/git/{capture,parser}.py`
- `src/ahadiff/safety/gates.py`

---

## 二、审查方法

### 第一轮 (R1) — 三代理并行 + 手工验证

| 代理 | 类型 | 职责 | 耗时 |
|------|------|------|------|
| Codex CLI | codex-plugin-cc | Adversarial review（首次卡死，kill 后重试成功） | ~20min |
| Explorer Agent | Claude subagent | 全文件结构化分析 + 接口验证 | ~3min |
| Test Runner | Claude subagent | 250 tests + ruff + pyright + wheel + CLI smoke | ~1min |
| Claude 主线 | 手工 | 独立代码审查 + PoC 验证 + 真实 provider smoke | ~15min |

### 第二轮 (R2) — 双路独立对抗

| 代理 | 类型 | 职责 | 耗时 |
|------|------|------|------|
| Codex CLI R2 | codex-plugin-cc | 验证 R1 findings + 深入新攻击面 | ~16min |
| Claude Deep Explorer R2 | Claude subagent | LLM 输出注入 / 边界条件 / 合约一致性 | ~2min |
| Claude 主线 R2 | 手工 | PoC 验证 Codex R2 FALSE_POSITIVE 判定 | ~5min |

---

## 三、Findings（严重级别排序）

### HIGH

#### H-1. Non-git workspace `run_id` 路径穿越（可利用）

- **文件**: `src/ahadiff/cli.py:682`
- **描述**: `has_git_repo=False` 时，`run_id` 直接拼接到 `state_dir / "runs" / run_id`，绕过 `_RUN_ID_RE` 正则校验。
- **可利用性**: 当目标目录存在且 claims 文件中 run_id 匹配时，CLI 可读取外部目录的 artifact 并将 `claims.jsonl` 写入 workspace 外部。
- **PoC**:
  ```
  # 创建 workspace/.ahadiff/runs 和 tmpdir/evil_run（含匹配 run_id 的 claims.raw.jsonl）
  ahadiff claims "../../../evil_run" --force --repo-root <non-git-workspace>
  # → exit_code=0, claims.jsonl 成功写入 evil_run/
  ```
- **发现者**: Claude R1 独立发现，Codex R1 确认，Codex R2 误判为 FALSE_POSITIVE（Claude PoC 推翻）
- **修复**: non-git 分支统一走 `_RUN_ID_RE` 校验

#### H-2. `claims --extract` 远程 provider 被 `strict_local` 隐私门拦截

- **文件**: `src/ahadiff/claims/runtime.py:90` + `src/ahadiff/llm/provider.py:198`
- **描述**: `runtime.py` 从 `metadata.json` 读取 `privacy_mode`（默认 `strict_local`），传入 `ProviderRequest`。`ManagedProvider.generate()` 调用 `enforce_privacy_mode(request.privacy_mode, target=transport_target)`，当 target="remote" 时抛出 `SafetyError("strict_local mode forbids remote transport")`。
- **影响**: `claims --extract --base-url https://api.openai.com` 直接被拦截。本地 loopback 不受影响。
- **对比**: `provider test` 命令（`cli.py:968-971`）有显式 `explicit_remote` 提升，但 `claims --extract` 缺少此逻辑。
- **发现者**: Codex R1 独立发现（Claude R1 遗漏），Claude R1 复核采纳，Codex R2 误判为 FALSE_POSITIVE（Claude 代码追踪推翻）
- **修复**: `claims --extract` 对远程 provider 补入隐私模式提升逻辑

### MEDIUM

#### M-1. Fallback prompt 与文件 prompt 内容漂移

- **文件**: `src/ahadiff/claims/runtime.py:23-58` vs `prompts/claim_extract.md`
- **描述**: `_FALLBACK_CLAIM_EXTRACT_PROMPT` 缺少：(1) `"either"` 使用条件的 verifier 推断描述；(2) `rename-to` 明确用 `"new"` 的规则；(3) deletion/rename 显式说明规则。
- **影响**: Wheel install（无 `prompts/` 目录）时 LLM 提取质量降低。
- **发现者**: Claude R1 + Explorer 一致，Codex R2 CONFIRMED

#### M-2. `provider test` 与 `claims --extract` base_url normalization 不一致

- **文件**: `src/ahadiff/cli.py:998` vs `cli.py:170`
- **描述**: `claims --extract` 调用 `_normalize_provider_base_url` 剥离 `/v1/chat/completions`；`provider test` 不做 normalization。adapter 内部再次拼接导致双重路径。
- **影响**: `provider test --base-url http://host/v1/chat/completions` → 404。**预存问题**，非本次引入。
- **发现者**: Claude R1 独立发现，Codex R2 CONFIRMED

#### M-3. `ClaimCandidate.source_hunks` 类型标注为 `list[Any]`

- **文件**: `src/ahadiff/claims/schema.py:14`
- **描述**: 运行时通过 `field_validator` 正确 coerce 为 `SourceHunk`，但 `list[Any]` 标注使 mypy/pyright 无法检测类型错误。`ClaimRecord`（`claim_status.py:82`）正确使用 `list[SourceHunk]`。
- **发现者**: Claude R2 Explorer

#### M-5. Extract 成功 + Verify 失败阻塞重试

- **文件**: `src/ahadiff/cli.py:709-763`
- **描述**: `--extract` 写入 `claims.raw.jsonl` 后，若 verify 阶段失败（如 run_id 不匹配），raw 文件残留。不带 `--force` 重试被 `_write_jsonl` 拒绝（"refusing to overwrite existing file"）。
- **PoC**: 首次 extract 成功 → verify 异常 → 重试不带 `--force` → `InputError`。
- **发现者**: Claude R2 Explorer，PoC 确认

#### M-7. Monkeypatch 遮蔽完整 runtime 管线（测试覆盖缺口）

- **文件**: `tests/unit/test_claim_extract.py:608-628`
- **描述**: CLI extract 测试将 `extract_claim_candidates_from_run` 完全 monkeypatch，未经过 `runtime.py → make_provider → generate → parse` 的真实路径。仅 `test_extract_claim_candidates_from_run_writes_claims_raw_jsonl`（line 425）用 MockTransport 走了完整路径。
- **发现者**: Codex R2 + Claude R2 一致

### LOW

#### L-1. `SourceHunk` 接受负数 `start`/`end`

- **文件**: `src/ahadiff/contracts/claim_status.py:29-30`
- **描述**: 仅校验 `end >= start`，`start=-5, end=-1` 可通过。verifier 因正行号不匹配而安全拒绝，但浪费验证计算。
- **发现者**: Claude R2 + Codex R2 一致

#### L-2. `_file_signal` 双重计算

- **文件**: `src/ahadiff/lesson/learnability.py:164, 224`
- **描述**: `_compute_factors` 和 `_build_reasons` 各自独立计算 `signals`。大 diff 时双倍计算量。
- **发现者**: Claude R2 Explorer

#### L-3. Prompt 文件发现依赖 package 相对路径

- **文件**: `src/ahadiff/claims/runtime.py:155`
- **描述**: `Path(__file__).resolve().parents[3] / "prompts"` 在 pip install 的 wheel 中指向不存在的路径，fallback 到弱版本。
- **发现者**: Claude R1

#### L-4. Learnability 测试覆盖不足

- **文件**: `tests/unit/test_learnability.py`
- **描述**: 仅 4 个测试，未覆盖空 diff、binary diff、all-context hunks、大文件数场景。
- **发现者**: Claude R2 Explorer

#### L-5. metadata.json 缺失字段静默为 null

- **文件**: `src/ahadiff/claims/runtime.py:135-140`
- **描述**: `build_claim_extract_payload` 中 `metadata.get("run_id")` 等字段缺失时返回 None → 序列化为 JSON null → LLM 收到语义不完整的 metadata。
- **发现者**: Claude R2 Explorer

---

## 四、交叉验证 / 分歧裁决

### R1 Claude 与 Codex 一致

| Finding | 一致性 |
|---------|--------|
| H-1 路径穿越 | 两方都发现（Codex 标 Medium/High，Claude 标 High） |
| JSONL 原子写入安全 | 两方确认 |
| API key 无泄露 | 两方确认 |
| 跨平台安全 | 两方确认 |

### R1 分歧

| Finding | Claude R1 | Codex R1 |
|---------|-----------|---------|
| H-2 远程 provider 隐私门 | 未发现 | **独立发现 (High)** |

### R2 Codex 误判（Claude PoC 推翻）

| Finding | Codex R2 判定 | Claude R2 验证 | 裁决 |
|---------|-------------|--------------|------|
| H-1 路径穿越 | FALSE_POSITIVE（"existence check 足够"） | **PoC 证明可利用** | **真阳性** |
| H-2 隐私门 | FALSE_POSITIVE（"informational metadata"） | **`enforce_privacy_mode` 是实际门禁** | **真阳性** |

### R2 新发现

| Finding | 来源 | 交叉验证 |
|---------|------|---------|
| M-3 source_hunks list[Any] | Claude R2 | Codex R2 同意(标为 Info) |
| M-5 extract+verify 非原子 | Claude R2 | PoC 确认 |
| M-7 monkeypatch 遮蔽 | Codex R2 + Claude R2 | 一致 |
| L-1 负数 start/end | Claude R2 + Codex R2 | 一致 |
| L-2 双重 _file_signal | Claude R2 | 确认 |

---

## 五、测试执行记录

| # | 命令 | 结果 | 执行方 |
|---|------|------|--------|
| 1 | `pytest tests/unit/ -q` (6 target files) | **89 passed** | Test Agent |
| 2 | `pytest tests/unit -q` (full) | **250 passed** | Test Agent |
| 3 | `ruff check src tests` | **All passed** | Test Agent |
| 4 | `ruff format --check src tests` | **76 files formatted** | Test Agent |
| 5 | `pyright` | **0 errors, 0 warnings** | Test Agent |
| 6 | `uv build --wheel` | **ahadiff-0.1.0a0** | Test Agent |
| 7 | `ahadiff --version` | **0.1.0a0** | Test Agent |
| 8 | `ahadiff claims --help` | 完整输出 | Test Agent |
| 9 | `ahadiff learn --help` | 含 --force-learn | Test Agent |
| 10 | `learn --compare --dry-run` (non-git) | 成功, score=0.574 | Claude 手工 |
| 11 | `claims --extract` port 8318 | verified/high | Claude 手工 |
| 12 | H-1 路径穿越 PoC | **漏洞确认** | Claude 手工 |
| 13 | H-2 enforce_privacy_mode 追踪 | **阻塞确认** | Claude 手工 |
| 14 | M-5 retry 阻塞 PoC | **确认** | Claude 手工 |
| 15 | 负数 SourceHunk 测试 | start=-1 被接受 | Claude 手工 |
| 16 | 空 diff / binary diff learnability | 安全降级 | Claude 手工 |
| 17 | LLM 输出 file 路径注入 | verifier 正确拒绝 | Claude 手工 |
| 18 | base_url normalization 边缘 | 行为确认 | Claude 手工 |
| — | Codex R2 测试 (3 test files) | **61 passed** | Codex |

---

## 六、跨平台评估

| 平台 | 方式 | 信心 | 说明 |
|------|------|------|------|
| **macOS** | 实机运行 | **High** | 全部测试 + smoke 在 Darwin 25.4.0 上执行 |
| **Linux** | 代码级推断 | **High** | 新文件仅用 pathlib/json/hashlib，无平台特定 API |
| **Windows** | 代码级推断 | **Medium** | NamedTemporaryFile delete=False 已使用；Path.replace() NTFS 原子；进程崩溃后 .tmp 残留需 maint clean-orphans |

---

## 七、Final Verdict

### **CONDITIONAL GO**

#### 阻塞项（必须先修）

1. **H-1**: `claims_cmd` non-git 分支补入 `_RUN_ID_RE` 校验
2. **H-2**: `claims --extract` 对远程 provider 补入 `explicit_remote` 隐私模式提升逻辑（参考 `provider test` cli.py:968-971）

#### 建议修复（不阻塞但应在下一 commit 处理）

3. **M-1**: 同步 fallback prompt 与文件 prompt
4. **M-2**: `provider test` 也调用 `_normalize_provider_base_url`
5. **M-5**: extract + verify 失败后自动清理 raw 文件，或在 extract 前检查是否需要 --force
6. **M-7**: 补充一个不 monkeypatch 的 MockTransport 集成测试

---

## 八、Codex 运行日志

| 次序 | 状态 | 耗时 | 结果 |
|------|------|------|------|
| R1 首次 | 卡死（API hang 15min+） | ~15min | 仅返回"task started"占位 |
| R1 重试 | 成功 | ~20min | 1 High + 1 Medium |
| R2 | 成功 | ~16min | 4 findings + 2 FALSE_POSITIVE（被 Claude PoC 推翻） |
