# 知返 AhaDiff — Claude + Codex 交叉 Code Review 报告（v2 含 Codex 交叉比对）

**日期**: 2026-04-23
**审查模型**: Claude Opus 4.6（主审 + 4 并行代理）+ Codex CLI（对抗审查 + 6 攻击面分析）
**审查范围**: Stage 0 / Task 0 ~ Stage 2 / Task 6 全部已落地代码 + 文档
**Codex 状态**: ✅ 第二轮对抗审查已完成并交叉验证

---

## A. Findings

### HIGH 级

#### H-1: macOS symlink 路径拒绝导致 `--patch`/`--compare` 对 `/tmp` `/var` 路径不可用

- **严重级别**: HIGH
- **文件**: `src/ahadiff/safety/ignore.py:136-141` + `src/ahadiff/git/capture.py:731`
- **问题**: `_reject_symlink_or_special_path()` 遍历候选路径所有父目录，检测到 symlink 即拒绝。macOS 上 `/var` → `/private/var`、`/tmp` → `/private/tmp` 是系统级 symlink，`mktemp -d` 创建的所有临时目录路径包含 `/var/folders/...`，会被误拒。
- **根因**: `resolve_safe_path_from_root()` 先 resolve 了 `root` 但未 resolve `candidate`。当 `candidate` 是绝对路径时（如 `--patch /var/folders/.../test.patch`），symlink 检查在未 resolve 的路径上执行，遇到系统 symlink `/var` 即触发 `SafetyError`。
- **触发条件**: macOS 上使用任何 `/tmp` 或 `mktemp` 路径作为 `--patch` / `--compare` 参数。已实际复现。
- **影响**: 所有 macOS 用户在非 git 工作区使用临时路径时无法运行 `learn --patch` 或 `learn --compare`。
- **确认方**: Claude 独立发现 + 实际 CLI smoke 复现

#### H-2: `staged=True, unstaged=True` 组合的 `source_kind` 误标为 `"git_unstaged"`

- **严重级别**: HIGH
- **文件**: `src/ahadiff/git/capture.py:660`
- **问题**: 当同时传入 `--staged --unstaged` 时，实际执行 `git diff HEAD`（覆盖 index + worktree 全部修改），但 `source_kind` 被设为 `"git_unstaged"`，对下游（metadata、audit、评估链路）造成语义误导。
- **触发条件**: `ahadiff learn --staged --unstaged`
- **影响**: 审计日志和元数据中记录的 source_kind 与实际 diff 范围不匹配。可能影响未来 ratchet 判定和 VCR cassette key 匹配。
- **确认方**: Claude 源码审查代理发现

#### H-3: 跨行 secret 分割完全绕过 redaction（regex 仅逐行匹配）

- **严重级别**: HIGH
- **文件**: `src/ahadiff/safety/redact.py`（全部 secret 检测规则）
- **问题**: 所有 secret detection regex 均在单行上匹配。若 secret 被分割成两行（如 `AKIAIOSAFO\nDNN7EXAMPLE`），regex 不会匹配，secret 将以明文通过 `redacted_remote` 模式发送。
- **触发条件**: diff 中存在跨行分割的 API key/token/password。虽然自然产生概率低（git diff 不会拆分常量），但 `--patch` 接受用户提供的 patch 文件。
- **影响**: `redacted_remote` 模式下可能泄漏跨行 secret 到远端 LLM
- **确认方**: **Codex 对抗审查发现** → Claude 代码审查验证确认

#### H-4: `.ahadiffignore` 是死代码——已实现但从未被 capture/redaction 管道调用

- **严重级别**: HIGH
- **文件**: `src/ahadiff/safety/ignore.py:39-59`（`load_ignore_matcher` / `is_ignored_path`）
- **问题**: `load_ignore_matcher()` 和 `is_ignored_path()` 已完整实现并有单元测试（`test_path_safety.py`），但在 `src/ahadiff/` 的任何其他模块中 **从未被调用**。用户创建的 `.ahadiffignore` 文件完全不生效。
- **触发条件**: 用户在 repo 根创建 `.ahadiffignore` 并期望 capture 阶段排除指定文件。
- **影响**: `.ahadiffignore` 功能完全无效；文档和代码均引用此功能但实际未接线。
- **验证**: `grep -rn "load_ignore_matcher\|is_ignored_path" src/ahadiff/` 在 `ignore.py` 外无结果。
- **确认方**: **Codex 对抗审查发现** → Claude 主审 grep 验证确认

---

### MEDIUM 级

#### M-1: 审计日志 `append_audit_record` 无文件锁，多进程并发时存在 rotation 竞态

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/safety/audit.py:96-107`
- **问题**: `append_audit_record` 执行 `_rotate_if_needed` + `open("a")` 两步非原子操作，无锁保护。两个进程同时触发 rotation 可能导致审计记录丢失。
- **触发条件**: 多进程同时运行 `ahadiff learn` 对同一仓库（如 CI 并行）
- **影响**: 审计数据丢失（非核心功能但影响合规审计）
- **确认方**: Claude 独立 + Claude 源码代理共同确认

#### M-2: `transport_target_for_base_url` 中 `hostname in local_hosts` 重复检查

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/llm/provider.py:493,500`
- **问题**: 第 493 行 `hostname in {"localhost", *local_hosts}` 已涵盖 `local_hosts` 检查，第 500 行的 `hostname in local_hosts` 是死代码。
- **影响**: 不影响正确性但表明逻辑可能未覆盖所有意图（如用户在 `local_hosts` 配置中填入 IP 地址字符串，第 496 行的 `ip_address()` 只处理标准格式）。
- **确认方**: Claude 独立发现 + Claude 源码代理共同确认

#### M-3: `_infer_prefix` 在 `delta_old > 0 and delta_new > 0` 时默认返回 `" "`（context）

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/git/parser.py:290-315`
- **问题**: 当 malformed diff 中一行前缀缺失且未来的 old/new 都需要行时，函数默认推断为 context 行，同时消耗 old_cursor 和 new_cursor 各一行。这可能导致对 malformed diff 的误分类。
- **触发条件**: 极端 malformed diff 输入（前缀字符缺失且 old/new 计数均有余量）
- **影响**: hunk body 中个别行的 kind 被错误标记为 context 而非 add/delete
- **确认方**: Claude 独立发现

#### M-4: OpenAI Responses adapter `parse_response` 变量遮蔽

- **严重级别**: MEDIUM（代码质量）
- **文件**: `src/ahadiff/llm/adapters/openai_responses.py:57-63`
- **问题**: 嵌套推导式 `for item in [content]` 遮蔽外层 `for item in payload.get("output", [])` 的循环变量。Python 推导式语义下不影响正确性（外层迭代器独立推进），但严重损害可读性，且未来修改极易引入 bug。
- **触发条件**: 代码维护/修改时
- **影响**: 可维护性风险
- **确认方**: Claude 源码代理发现，Claude 主审验证为非 bug 但存在维护风险

#### M-5: `_semaphore_state` 替换竞态

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/llm/provider.py:456-462`
- **问题**: 当 `limit` 变化时创建新的 `BoundedSemaphore` 替换旧的。已持有旧信号量的线程仍在运行，新线程获取新信号量，实际并发数可能短暂超过 `limit`。
- **触发条件**: 运行时动态更改 `max_concurrent`
- **影响**: 短暂超过并发限制
- **确认方**: Claude 源码代理发现

#### M-6: Git 模式 diff 输出无大小限制——`max_patch_bytes` 仅保护 stdin/patch 模式

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/git/capture.py:527,621,672,1089-1093` + `src/ahadiff/git/repo.py:50-56`
- **问题**: `run_git()` 使用 `capture_output=True` 将整个 git 输出捕获到内存。`max_patch_bytes` 仅在 `_capture_patch_input`（stdin/文件）和 `_read_stdin_bytes` 中检查。所有 git-sourced 模式（`--last`、`--since`、revision range、`--staged`、`--unstaged`）的 `git diff` 输出无大小限制。
- **触发条件**: 在含大型二进制文件变更的 repo 上运行 `ahadiff learn --last`
- **影响**: 潜在 OOM（内存耗尽）
- **确认方**: **Codex 对抗审查发现** → Claude 代码审查验证确认

#### M-7: 跨行 prompt injection 绕过逐行检测

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/safety/injection.py`
- **问题**: 与 H-3 同理，injection 检测也是逐行匹配。将 injection payload 分割到多行可绕过检测。
- **触发条件**: `--patch` 文件中刻意构造的跨行 injection
- **影响**: 未检测到的 injection 进入 LLM prompt
- **确认方**: **Codex 对抗审查发现**

#### M-8: Double base64 编码仅触发 soft_detect，不触发 hard_block

- **严重级别**: MEDIUM
- **文件**: `src/ahadiff/safety/redact.py`
- **问题**: base64 解码仅做一层。双重 base64 编码的 secret（如 `base64(base64("AKIAIOSFODNN7EXAMPLE"))`）解码第一层后得到 base64 字符串而非原始 secret 模式，仅触发高熵 `soft_detect`，在 `redacted_remote` 模式下可通过。
- **触发条件**: 刻意双重 base64 编码的 secret
- **影响**: `redacted_remote` 模式下可能泄漏
- **确认方**: **Codex 对抗审查发现** → Claude 验证为 MEDIUM（实际风险较 H-3 低）

---

### LOW 级

#### L-1: `escape_terminal_text` 未转义 BiDi Unicode 控制字符

- **文件**: `src/ahadiff/safety/ignore.py:163-177`
- **问题**: 通过 Unicode 0x80+ 范围字符不做转义，其中 U+202A-U+202E 等 BiDi 控制字符可在终端伪造显示。
- **确认方**: Claude 独立发现

#### L-2: `_sanitize_js_like_structure_line` 仅处理单行块注释

- **文件**: `src/ahadiff/git/symbols.py:1079-1082`
- **问题**: `re.sub(r"/\*.*?\*/", "", line)` 无法匹配跨行块注释的中间部分。如果 `{ }` 出现在块注释中间行，brace counting 会出错。
- **确认方**: Claude 独立发现

#### L-3: `[truncated]` 标记仅精确匹配

- **文件**: `src/ahadiff/git/parser.py:236,242`
- **问题**: 只匹配 `"[truncated]"` 精确字符串。`[Truncated]`、`... [truncated]` 或其他变体不会被识别。
- **确认方**: Claude 独立发现

#### L-4: `probed_max_context=0` 会返回 0 作为上下文窗口

- **文件**: `src/ahadiff/llm/cost.py:134-137`
- **问题**: `resolve_context_window` 检查 `probed_max_context is not None` 但不检查 `> 0`。probe 返回 0 时下游 `max_context * 0.9 = 0`，触发永远无法满足的 context check。
- **确认方**: Claude 源码代理发现

#### L-5: 文档 changelog 中旧测试计数 (18 vs 19)

- **文件**: `CLAUDE.md`、`doc/CLAUDE.md` 的 2026-04-22 changelog 条目
- **问题**: 历史 changelog 记录 `test_contracts.py = 18 passed`，但当前实际为 19。主文本中的计数已更新为正确值。
- **确认方**: 文档审查代理发现

#### L-6: data-scope-architecture.md 目录树中 `.ahadiffignore` 位置歧义

- **文件**: `.claude/team-plan/ahadiff-data-scope-architecture.md`
- **问题**: 目录树显示 `.ahadiffignore` 在 `.ahadiff/` 内部，但代码和 README 均将其放在 repo 根目录。
- **确认方**: 文档审查代理发现

#### L-7: `@@ -0,0 +1,N @@` 解析产生 `old_end = -1`

- **文件**: `src/ahadiff/git/parser.py:43-44`
- **问题**: `old_end` 属性在 `old_count == 0` 时返回 `old_start - 1`。当 `old_start=0`（新文件）时返回 `-1`，下游若对 `old_end` 做范围计算可能出错。
- **确认方**: **Codex 发现** → Claude 实际运行验证 `old_end=-1`

#### L-8: Diff header 中路径穿越（如 `a/../../etc/passwd`）被接受

- **文件**: `src/ahadiff/git/parser.py:162-164`（`_normalize_diff_path`）
- **问题**: diff header 中的路径穿越不被过滤，`../` 序列保留在 `display_path` 中。
- **影响**: 仅影响显示路径，不触发文件操作。LOW。
- **确认方**: **Codex 发现**

#### L-9: Provider adapter 返回负 token 计数不被拦截

- **文件**: `src/ahadiff/llm/provider.py:296-302`
- **问题**: `response.input_tokens` / `output_tokens` 无非负校验。负值进入 `estimate_cost_usd` 会产生负成本。
- **确认方**: **Codex 发现**

---

## B. Cross Review Matrix

### 双方共同确认（Claude 发现 + Codex 独立确认，或 Codex 发现 + Claude 验证）

| # | Finding | Claude | Codex | 验证方式 |
|---|---------|--------|-------|---------|
| H-3 | 跨行 secret 分割绕过 | Claude 代理确认 | ✅ 首先发现 | 代码审查 regex 为逐行 |
| H-4 | `.ahadiffignore` 死代码 | Claude `grep` 验证 | ✅ 首先发现 | `grep -rn` 确认无调用 |
| M-6 | Git diff 无大小限制 | Claude 代码审查 | ✅ 首先发现 | `run_git` 无 size guard |
| M-8 | Double base64 绕过 | Claude 降级验证 | ✅ 首先发现 | 单层 decode 确认 |

### 仅 Claude 发现

| # | Finding | 备注 |
|---|---------|------|
| H-1 | macOS symlink 拒绝 | CLI smoke 实际复现 |
| H-2 | staged+unstaged source_kind 误标 | Claude 代理发现 |
| M-1 | 审计日志无锁竞态 | Claude 独立+代理 |
| M-2 | hostname 重复检查 | Claude 独立+代理 |
| M-3 | _infer_prefix 歧义 fallback | Claude 独立 |
| M-4 | OpenAI Responses 变量遮蔽 | Claude 代理→主审降级 |
| M-5 | semaphore 替换竞态 | Claude 代理 |
| L-1~L-6 | BiDi/注释/truncated/context/changelog/doc | Claude 独立+代理 |

### 仅 Codex 发现

| # | Finding | Claude 验证结果 |
|---|---------|----------------|
| M-7 | 跨行 injection 绕过 | ✅ 确认（与 H-3 同理） |
| L-7 | `old_end = -1` 负值 | ✅ 实际运行验证 |
| L-8 | diff header 路径穿越 | ✅ 确认但仅影响 display |
| L-9 | 负 token 计数 | ✅ 确认 |

### 已复核排除的误报

| # | 原始来源 | 原始结论 | 排除理由 |
|---|---------|---------|---------|
| ~~`_resolve_policy` 逻辑反转~~ | Claude 代理 | HIGH bug | two-layer 设计：git repo 由 `redact.py._resolve_policy` 加载 allowlist |
| ~~OpenAI Responses shadow 致数据丢失~~ | Claude 代理 | HIGH bug | Python 推导式外层迭代器独立推进，降为 M-4 可维护性 |
| ~~repo_write_lock 未清理内容~~ | Claude 代理 | HIGH bug | `read_lock_metadata` 仅 contention 时调用，新持有者 truncate+overwrite |
| ~~`diff --git` 在 hunk body 中致静默分割~~ | Codex | MEDIUM bug | 实测 parser 抛 InputError（count mismatch），**不是静默错误** |
| ~~ENV privacy_mode 覆盖致降级~~ | Codex | MEDIUM 安全 | **设计文档明确** ENV > CLI > repo > global > default 优先级链 |
| ~~`find_workspace_root` 越界~~ | Codex | MEDIUM 安全 | 设计行为：向上查找 `.ahadiff/` 是 workspace discovery 机制 |
| ~~`\ ` 前缀行被丢弃~~ | Codex | LOW bug | 正确行为：unified diff `\ No newline at end of file` 标记 |

---

## C. Test Evidence

### 实际执行

| 命令 | 结果 |
|------|------|
| `uv run ruff check src tests` | ✅ 0 errors (exit 0) |
| `uv run pyright` | ✅ 0 errors (exit 0) |
| `uv run pytest tests/unit -q` | ✅ **181 passed** in 3.19s |
| `uv run pytest tests/unit/test_contracts.py -q` | ✅ 19 passed |
| `uv run pytest tests/unit/test_stage1_task1.py -q` | ✅ 23 passed |
| `uv run pytest tests/unit/test_redact.py test_injection.py test_path_safety.py test_allowlist.py -q` | ✅ 29 passed |
| `uv run pytest tests/unit/test_probe.py tests/unit/test_provider.py -q` | ✅ 40 passed |
| `uv run pytest tests/unit/test_git_capture.py -q` | ✅ 34 passed |
| `uv run pytest tests/unit/test_hunk_hash.py test_diff_parser.py test_line_map.py test_symbol_extract.py test_git_capture.py -q` | ✅ 70 passed |
| `uv run python -m ahadiff --version` | ✅ `ahadiff 0.1.0a0` |
| `uv run ahadiff doctor` | ✅ 正常输出 repo/config/SQLite 信息 |
| `uv run ahadiff config show --resolved` | ✅ 26 配置项正确显示 source |
| `uv run ahadiff maint clean-orphans --dry-run` | ✅ `Clean: no orphaned state artifacts found` |
| `uv run ahadiff provider test`（无参数） | ✅ 正确报错 `Missing option '--name'` |
| `learn --patch /var/.../sample.patch --repo-root /var/...` | ❌ `Error: symlink paths are not allowed: /var` (H-1) |
| `learn --compare old.py new.py --repo-root /var/...` | ❌ 同上 (H-1) |
| `learn --patch .../sample.patch --repo-root ~/Desktop/...`（非 symlink） | ✅ 正确 capture |
| `learn --compare old.py new.py --repo-root ~/Desktop/...`（非 symlink） | ✅ 正确 capture |
| `unlock --force --repo-root <tmp>` | ✅ `No repo write lock was present` |

### 未执行

| 项目 | 原因 |
|------|------|
| Provider live smoke（真实 LLM 调用） | 无安全可用的 loopback endpoint；不伪造 |
| Windows / Linux 实机测试 | 当前环境为 macOS；仅做静态兼容性审查 |
| `ahadiff learn --staged/--unstaged` 真实 git 操作 | 避免污染仓库 |

---

## D. Platform Matrix

### macOS (当前平台)

- **已执行验证**: 全量测试 + CLI smoke + symlink 复现
- **确认问题**: H-1 symlink 路径拒绝

### Windows

- **仅静态审查**，未实机验证
- `portalocker` 使用正确（`LOCK_EX | LOCK_NB`），Windows 兼容
- `global_config_dir()` 使用 `APPDATA` 环境变量，正确
- `os.replace()` 用于原子重命名，Windows 支持
- **剩余风险**:
  - `os.fsync(handle.fileno())` 在 Windows 上可能对某些文件系统无效
  - 长路径支持（>260 字符）取决于 Windows 版本和 manifest
  - `subprocess.run(["git", ...])` 需要 git 在 PATH 中
  - `sys.stdin.buffer` 在 Windows cmd.exe 中的行为可能与 Unix 不同

### Linux

- **仅静态审查**，未实机验证
- `global_config_dir()` 使用 `XDG_CONFIG_HOME` 或 `~/.config`，正确
- `portalocker` 在 Linux 使用 `fcntl.flock`，兼容
- **剩余风险**:
  - NFS/CIFS 上 `flock` 可能不生效
  - SQLite WAL 模式在网络文件系统上不安全（已有 fail-fast 代码但未实测）

---

## E. Task Truth Summary

### 已落地任务（代码+测试验证）

| Task | 状态 | 测试数 |
|------|------|--------|
| Stage 0 / Task 0 (Contracts) | ✅ 完整落地 | 19 |
| Stage 1 / Task 1 (CLI scaffold) | ✅ 完整落地 | 23 |
| Stage 1 / Task 2 (Safety layer) | ✅ 完整落地 | 29 |
| Layer 1.5 / Task 7 (Provider runtime) | ✅ 完整落地 | 40 |
| Stage 2 / Task 5 (Diff capture) | ✅ 完整落地 | 34 |
| Stage 2 / Task 6 (Parser/structuring) | ✅ 完整落地 | 70（含 capture 重复计入） |

### 尚未落地任务

- Evaluator runtime（`src/ahadiff/eval/` 不存在）
- Viewer runtime（`viewer/` 不存在）
- `ahadiff serve`
- Orchestrator（仅 contract stub，`raise NotImplementedError`）
- FSRS SRS 系统
- i18n
- 所有 Stage 3-7 任务

---

## F. Residual Risks / Test Gaps

### 高优先级测试缺口

1. **LLM 适配器 `build_request`/`parse_response` 无独立单测** — 8 个 adapter 仅有 conformance 测试和 Azure URL 测试，无请求构造/响应解析的专项测试
2. **特定 secret 规则无独立测试** — AWS_ACCESS_KEY, PEM_PRIVATE_KEY, SLACK_WEBHOOK, COOKIE_SESSION_TOKEN, DATABASE_URL 等规则无专项测试
3. **`enforce_token_budget()` 失败路径未测试** — input/output 超预算的 raise 路径无覆盖
4. **Provider 401/403 认证失败未测试** — `_send_once` 的 `SafetyError` 路径
5. **Binary patch 输入拒绝未直接测试** — `b"\x00" in data` 检查
6. **Config + privacy + provider 端到端集成未测试**
7. **跨行 secret/injection 检测未测试** — 与 H-3/M-7 对应，无测试验证跨行分割场景
8. **`.ahadiffignore` 集成测试缺失** — 有单元测试但无集成测试验证 capture 阶段实际使用
9. **Git diff 大输出压力测试缺失** — 与 M-6 对应，无测试验证大型 diff 的内存行为

### 跨平台未验证项

- Windows: 长路径、stdin pipe、信号处理、文件锁
- Linux: NFS flock、XDG 路径、locale 处理
- 上述均为静态审查判断，非实机验证

---

## G. 交叉审查统计

| 维度 | 数量 |
|------|------|
| 总发现数 | **4 HIGH + 8 MEDIUM + 9 LOW = 21** |
| Claude 独立发现 | 14（含代理） |
| Codex 独立发现 | 11（含 4 被排除） |
| 双方交叉确认 | 4（H-3, H-4, M-6, M-8） |
| Claude 排除的 Codex 误报 | 4（`diff --git` hunk、ENV override、workspace walk、`\ ` 前缀） |
| Codex 排除的 Claude 误报 | 0（Codex 未审查 Claude 发现） |
| Claude 代理被主审排除的误报 | 3（`_resolve_policy`、shadow 变量、lock 残留）|
