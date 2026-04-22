# AhaDiff 数据范围架构设计（最终版）

> 评估方法：Codex 深度分析 + Claude 独立评估，双方交叉验证
> 日期：2026-04-21
> 状态：**待用户确认后冻结**

---

## 核心原则

> **AhaDiff 应该是 per-repo truth + global derived governance，而不是 global mutable brain。**

1. 真相源永远留在 per-repo：`review.sqlite`、`audit.jsonl`、`concepts.jsonl`、`prompts/`、VCR cassettes
2. Global 只做用户本地的**派生索引、预算账本、查询层、偏好层**
3. 任何 global 数据都不参与 ratchet 真值判定，不反向覆盖 repo 内状态
4. CLI 全局安装（pip install ahadiff），per-repo 运用（每个 repo 独立 `.ahadiff/`）

---

## 目录结构总览

```
global_config_dir()                   ← Global（派生/索引/偏好，非真相源）
  Linux:   ~/.config/ahadiff/
  macOS:   ~/Library/Application Support/ahadiff/
  Windows: %APPDATA%/ahadiff/
├── config.toml                       — 全局偏好/provider env alias
├── registry.json                     — repo 发现索引 (v0.2, opt-in)
├── usage.sqlite                      — LLM 花费汇总账本 (v0.2)
└── security/
    └── allowlist.yaml                — 全局 secret scan 自定义规则 (v0.2)

<repo>/.ahadiff/                      ← Layer 1: Per-repo（唯一真相源）
├── config.toml                       — repo 级配置覆盖
├── review.sqlite                     — SRS/results/signals 唯一真相源
├── concepts.jsonl                    — branch-aware 概念累积
├── runs/<run_id>/                    — lesson/quiz/claims/score/patch
├── graphify/                         — repo-level code map cache
├── audit.jsonl                       — 本 repo LLM 调用审计
├── audit.private.jsonl               — strict_local 本机专用隐私审计（gitignored）
├── ahadiff.lock                      — portalocker 文件锁
└── .ahadiffignore                    — 路径过滤规则
```

---

## 全功能评估矩阵（Codex + Claude 共识）

| # | 功能 | 需要调整 | 范围 | v0.1 动作 | v0.2 动作 |
|---|------|---------|------|----------|----------|
| A | Provider cost/token | **Yes** | 混合 | 补 UsageEvent schema 到 Task 7 | usage.sqlite + 月度预算 |
| B | Secret allowlist | **Yes** | 混合 | exact/hash/path allowlist (Task 2) | 全局 allowlist + 受限 regex |
| C | Audit log | No | per-repo | version + rotation (Task 7) | 可选 global query |
| D | Install targets | No | per-repo | conflict advisory (Task 19) | 不变 |
| E | 用户学习画像 | No | — | 不做 | 仅轻量 UX prefs |
| F | Improve loop | No | per-repo | 不变 | 手动 prompt-pack 导入 |
| G | Benchmark results | **Yes** | 混合 | 冻结 manifest + suite_id (Task 18) | global compare index |
| H | VCR cassettes | No | per-repo | 不变 + GC | 不变 |
| I | Config 优先级链 | **Yes** | 混合 | 冻结 precedence + doctor (Task 0/1) | UI provenance |

---

## 逐功能详细设计

### A. Provider Cost/Token 追踪

**范围**：per-run audit（真相） + global usage.sqlite（派生账本）

**Config schema**：
```toml
[budget]
monthly_limit_usd = 50.0       # 0 = unlimited
budget_scope = "user"           # "user" | "principal" | "ci"
track_free_local = true         # Ollama 等免费模型也记 token 数
```

**UsageEvent schema**（v0.1 预留，v0.2 实现写入）：
```python
class UsageEvent(BaseModel):
    event_id: str               # UUID v7
    run_id: str
    repo_id: str                # repo fingerprint
    provider_class: str         # "openai" | "openai_responses" | "gemini" | "anthropic" | "azure" | "newapi" | "cherryin" | "ollama"
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float             # estimated
    pricing_version: str        # "2026-04-01"
    cost_confidence: Literal["high", "medium", "low"]
    billing_mode: Literal["billable", "free_local"]
    execution_origin: Literal["user", "ci", "improve"]
    api_principal_hash: str     # SHA-256(api_key)[:12]，不存原始 key
    timestamp: str
```

**Corner cases 处理**：

| Corner Case | 策略 |
|---|---|
| 多用户共机 | 按 `api_principal_hash` 分桶 |
| 月度预算耗尽 | provider preflight 检查；只阻断 billable，不阻断 free_local |
| strict_local Ollama | 记 token 数，cost=0.0，billing_mode="free_local" |
| 网络断开价格不准 | 内置价格表 + cost_confidence 标记 |
| CI 环境 | execution_origin="ci"，默认不计入个人配额 |
| 并发写 usage.sqlite | WAL + busy_timeout + idempotency_key |
| provider 改价 | 存 pricing_version，历史不回写 |
| retry 重复计费 | 粒度为 provider call，含 retry_chain_id |

**Task 影响**：改 Task 7（补 schema）、改 Task 1（config budget 字段）、新增 Task 7a（v0.2 global ledger）

---

### B. Secret Scan 自定义 Allowlist

**范围**：builtin（不可禁用）→ global allowlist → per-repo allowlist

**设计原则**：
- builtin = hard_block 规则，用户不可禁用（安全底线）
- 自定义规则 = soft_detect，可被 allowlist suppress
- v0.1 不开放任意 regex（防 ReDoS），只支持 exact/hash/glob/path-scope

**Allowlist 格式**（per-repo `.ahadiff/config.toml`）：
```toml
[security]
# 精确值排除（如测试用 dummy token）
allow_exact = ["sk-test-1234567890"]

# 路径范围排除（如 fixture 目录）
allow_paths = ["tests/fixtures/**", "docs/examples/**"]

# 按 rule_id 压制全局规则（不可压制 builtin hard_block）
suppress_rules = ["CORP-INTERNAL-TOKEN-FORMAT"]
```

**全局 allowlist**（`global_config_dir()/security/allowlist.yaml`，v0.2）：
```yaml
rules:
  - id: "CORP-INTERNAL-TOKEN-FORMAT"
    type: "glob"
    pattern: "corp_*_token"
    scope: "all_repos"
    risk_note: "公司内部 token 格式，非真实密钥"
```

**Corner cases 处理**：

| Corner Case | 策略 |
|---|---|
| 全局引入不安全模式 | `ahadiff doctor` 扫描宽泛规则并警告 |
| per-repo 禁用全局规则 | 支持 suppress_rules（by ID），不可禁用 builtin |
| ReDoS | v0.1 不支持 regex；v0.2 加 100ms 编译超时 |
| 团队共享 vs 个人 | `.ahadiff/config.toml` 进 git = 团队；全局 = 个人 |
| 旧 run 不一致 | 每 run 存 `allowlist_digest`，不追溯 |
| monorepo 子目录 | 不支持子目录级（per git root only） |
| allowlist 被 improve loop 改 | 禁止——安全配置不在 prompts/ 可写面内 |

**Task 影响**：改 Task 2（allowlist policy + digest）、改 Task 1（config 加载）

---

### C. Audit Log

**范围**：per-repo 存储，不改。补 retention + schema version。

**设计**：
```python
# audit.jsonl 每行格式
{
    "schema_version": 1,
    "event_id": "...",
    "event_type": "llm_call",
    "provider_class": "anthropic",
    "model_id": "claude-sonnet-4-6",
    "prompt_name": "lesson_generate",
    "prompt_fingerprint": "a1b2c3d",
    "request_hash": "...",
    "input_tokens": 15000,
    "output_tokens": 3000,
    "cost_usd": 0.12,
    "execution_origin": "user",
    "timestamp": "2026-04-21T10:30:00Z"
}
```

**Retention**：audit.jsonl > 10MB → rotate 为 `audit.1.jsonl.gz`，保留最近 3 份。`audit.private.jsonl` 复用同一 rotation 策略，但仅在 `strict_local` 下生成。当前 `.tmp` 残留清理由 `ahadiff maint clean-orphans` 单独承担，不并入 `doctor`。

**隐私**：不存 prompt 原文、不存 response 内容、不存 API key。只存结构化元数据。若确需记录绝对路径/本机诊断信息，只能写入 `audit.private.jsonl`；该文件必须保持 repo-local、gitignored，不参与远端同步。

**Task 影响**：改 Task 7（补 schema_version + rotation）

---

### D. Install Targets — 不调整

保持 per-repo。补 conflict advisory 到 Task 19。

---

### E. 用户学习画像 — 不做

v0.1/v0.2 均不实现。`config.toml [general] lang` 已覆盖最核心偏好。

---

### F. Improve Loop — 不调整

保持 per-repo。v0.2 可选 `ahadiff prompt export/import`（手动，不自动共享）。

---

### G. Benchmark Results

**范围**：per-repo 执行 + manifest 冻结 + v0.2 global compare

**v0.1 必须冻结**：
```json
// benchmarks/manifest.json
{
    "suite_id": "ahadiff-local-v1",
    "suite_digest": "sha256:...",
    "visibility": "private",
    "entries": [
        {"id": "python-retry", "lang": "python", "difficulty": "medium"},
        {"id": "ts-component", "lang": "typescript", "difficulty": "medium", "degraded": true}
    ]
}
```

**Corner cases**：

| Corner Case | 策略 |
|---|---|
| 跨 repo 比较 | 只有 `suite_digest + eval_bundle_version + model_id` 全匹配才可比 |
| degraded run 混入 | 禁止；benchmark 不接受 degraded input |
| 不同语言 repo | 按 suite 分组，不做混合 leaderboard |

**Task 影响**：改 Task 18（manifest + suite_id + visibility）

---

### H. VCR Cassettes — 不调整

保持 per-repo。当前已有 `ahadiff maint clean-orphans` 负责 `.tmp` orphan cleanup；VCR cassette GC 若后续要做，继续单独提供 maintenance CLI，不纳入当前 `doctor` 合同。

---

### I. Config 优先级链

**冻结优先级（高到低）**：

```
┌─────────────────────────────────────────────┐
│ 1. ENV var (AHADIFF_*)                      │ ← 最高，CI 可覆盖一切
│ 2. CLI flag (--lang, --provider, --budget)   │
│ 3. per-repo .ahadiff/config.toml            │
│ 4. global_config_dir()/config.toml           │
│ 5. builtin defaults                         │
└─────────────────────────────────────────────┘

特殊域：
- 凭证：env secret > per-repo env_var_name > global env_var_name > none
- Serve/request：cookie > Accept-Language > CLI session > per-repo > global > system
```

**诊断命令**：
```bash
$ ahadiff config show --resolved
[general]
  lang = "zh-CN"     # source: per-repo .ahadiff/config.toml
[provider]
  api_key = "***"    # source: env ANTHROPIC_API_KEY
[budget]
  monthly_limit = 50 # source: global_config_dir()/config.toml
```

**Corner cases**：

| Corner Case | 策略 |
|---|---|
| 全局 key + per-repo 不同 key | per-repo 配 `api_key_env = "WORK_KEY"` 指向不同 env var |
| config 拼写错误 | 加载时 warn unknown keys，不 fail |
| repo 误存 raw key | `ahadiff doctor` 检测 config 中的 secret pattern 并警告 |

**Task 影响**：改 Task 0（冻结 precedence 规范）、改 Task 1（unified config resolver + doctor）

---

## 对 v0.1 Task DAG 的总影响

| Task | 改动 | 内容 |
|------|------|------|
| **Task 0** | 补充 | config precedence 规范 + UsageEvent schema 预留 + allowlist policy contract |
| **Task 1** | 补充 | 统一 config resolver（5 层 precedence）+ `ahadiff config show --resolved` + `ahadiff doctor` config 诊断 |
| **Task 2** | 补充 | allowlist exact/hash/path + allowlist_digest + suppress_rules（不禁 builtin） |
| **Task 7** | 补充 | audit.jsonl schema_version + rotation + UsageEvent 字段（预留） |
| **Task 18** | 补充 | benchmarks/manifest.json + suite_id + suite_digest + visibility |

**不改的 Task**：Task 3/4/5/6/8/9/10/11/12/13/14/14.5/15/16/17/19/20/i18n-0~6

**新增 Task（v0.2）**：
- Task 7a: Global usage ledger + 月度预算
- Task 15b: `review --all` 全局聚合
- Task 18a: Global benchmark compare index

---

## 分期交付路线

```
v0.1 (当前)
├── 纯 per-repo 真相源
├── config precedence 5 层冻结
├── allowlist exact/hash/path（per-repo only）
├── audit schema_version + rotation
├── benchmark manifest 冻结
└── UsageEvent schema 预留（不实现 global ledger）

v0.2
├── registry.json (opt-in) + review --all
├── usage.sqlite + 月度预算
├── 全局 allowlist.yaml
├── global benchmark compare
└── prompt-pack export/import (手动)

v1.0+
├── 轻量用户偏好 (explanation_density)
├── global audit query catalog
└── public benchmark suite
```

---

## Codex + Claude 共识声明

两方在以下关键判断上**完全一致**：
1. per-repo 真相源不可动摇
2. concepts.jsonl 保持 per-repo（不迁移、不全局去重）
3. Graphify 纯 per-repo
4. 用户画像 v0.1/v0.2 不做
5. VCR 不跨 repo 去重
6. improve loop 不自动共享
7. global 只做派生/索引/账本，不做真相源
8. v0.1 改动控制在 Task 0/1/2/7/18 五处，不扩散到主 DAG
