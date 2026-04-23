# Stage 2 / Task 7 Cross-Review Revalidation

**日期**: 2026-04-23  
**HEAD**: `29e1eb74` on `main`  
**范围**: 当前 session 全部未提交修改  
**结论口径**: 先按代码真值逐条复核原 findings，再直接修复属实问题，最后重跑真实验证

---

## 1. Findings Revalidation

### 已确认属实且已在当前工作树修复

#### C-1: `strict_local` 可被环境代理绕过
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 默认 provider client 改为 `httpx.Client(..., trust_env=False)`
  - `strict_local + local transport` 下，若外部注入 client 仍 `trust_env=True`，现在会直接抛 `SafetyError`
- **验证**:
  - 新增测试覆盖默认 client 禁用环境代理
  - 新增测试覆盖注入 `trust_env=True` client 时拒绝发送

#### H-1: provider audit 缺少 `event_id`
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 新增 `make_event_id()`
  - `build_provider_audit_record()` 与 `build_redaction_audit_record()` 现在都会生成 `event_id`
- **验证**:
  - provider audit 测试现在显式断言 `event_id` 写入

#### H-2: provider 全局状态跨工作区/跨测试泄漏
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - provider runtime key 现在包含 `workspace_root` identity，避免跨工作区共享
  - 新增 `reset_provider_runtime_state()` 清理 API
  - provider/probe 测试增加 `autouse` fixture，在每个测试前后清理全局状态

#### H-3: 畸形 200 响应不会进入重试分支
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `KeyError / IndexError / TypeError / ValueError` 现在按 malformed payload 进入重试
- **验证**:
  - 新增 `choices=[]` 的 200 响应回归测试，确认会重试再恢复

#### H-4: probe 持久化非原子、无锁
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `write_config_data()` 改为临时文件 + `replace()` 原子写
  - `persist_probe_result()` 改为在 `.ahadiff/ahadiff.lock` 下做 read-modify-write
  - provider alias 含 `.` 现在会被明确拒绝，避免 TOML 路径歧义

#### H-5: provider/probe 测试隔离不足
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `tests/unit/test_provider.py`
  - `tests/unit/test_probe.py`
  - 两边都加了 `autouse` fixture，强制清理 provider runtime 全局状态

#### M-1: `config show --resolved` 遗漏 `[providers.*]`
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - config flatten/resolve 现在会纳入动态 `providers.<name>.*` 键
  - `ConfigSnapshot.values` 和 `iter_resolved_settings()` 现在都能看见 probe 持久化条目
- **验证**:
  - CLI 测试已断言 `providers.demo.base_url` 会出现在 `config show --resolved`

#### M-2: Anthropic adapter 隐式硬编码 `max_tokens=512`
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 默认上限不再固定死为 `512`
  - 现在改成优先用 `request.max_output_tokens`，否则按 `probed_max_context` 动态推导保守默认值

#### M-6: `test_retry_after_header` 受共享 rate limiter 干扰
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 测试已经通过 `autouse` fixture 清理共享状态
  - rate limiter 本身也补了时钟回退自恢复逻辑

#### M-7: Windows 本地传输判定缺失
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `transport_target_for_base_url()` 现在支持 `npipe` / `http+npipe`
  - 回环地址判定改成 `ip_address(...).is_loopback`
- **验证**:
  - 新增 loopback IP 和 named pipe 单测

#### M-4: `estimate_cost_usd()` 曾经对当前默认模型永远 low confidence
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 引入内置官方来源 pricing book
  - 当前默认 OpenAI 模型 `gpt-5.4 / gpt-5.4-mini / gpt-5.4-nano` 现在可直接给出高置信成本估算
  - 未命中官方价表的模型仍保持保守降级
- **验证**:
  - 新增成本估算测试，默认模型现在返回 `cost_confidence=high`

#### M-5: strict_local 审计里的 `request_hash` 可跨运行关联
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `request_hash` 现在按 `event_id + payload` 生成
  - 保留审计字段，但移除跨运行稳定指纹
- **验证**:
  - 新增回归测试，连续两次相同请求现在得到不同 `request_hash`

#### L-1: cache key 在大 diff 上会完整序列化正文
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - cache key 改为使用 `diff_content_sha256`
  - 不再把原始大 diff 文本直接塞进 JSON payload 后再 hash

#### L-2: Azure `api-version` 硬编码
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 保留默认版本
  - 同时支持从 `base_url` query 中覆写 `api-version`
- **验证**:
  - 新增 adapter 测试，确认 query 覆写生效

#### L-3: NewAPI / CherryIN 代码重复
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 抽出 `OpenAICompatAdapter`
  - `NewAPIAdapter` 与 `CherryINAdapter` 现在共用同一实现基座

#### L-4: `ManagedProvider` 缺少 context manager 协议
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - 新增 `__enter__` / `__exit__`
  - 可在 `with make_provider(...) as provider:` 下安全使用
- **验证**:
  - 新增 context manager 回归测试

#### L-5: `--api-key` CLI 明文可见
- **结论**: 原 finding **属实**
- **当前状态**: **已修复**
- **修复**:
  - `provider test` 不再接受明文 `--api-key` 作为正常路径
  - 优先从 `--api-key-env` 指向的环境变量读取
  - 交互式场景改走隐藏输入
- **验证**:
  - 新增 CLI 测试，env fallback 可用，明文 `--api-key` 会被拒绝

---

### 已确认是误报，或在当前真值下不成立

#### M-3: Gemini `candidatesTokenCount` 字段名错误
- **结论**: **误报**
- **依据**:
  - 当前实现使用 `usageMetadata.candidatesTokenCount`
  - 复核官方 Gemini `generateContent` 文档后，该字段名与当前实现一致
- **处理**: 不改代码

---

## 2. Code Changes Applied

- `src/ahadiff/core/ids.py`
  - 新增 `make_event_id()`

- `src/ahadiff/safety/audit.py`
  - redaction/provider audit 统一补 `event_id`

- `src/ahadiff/core/config.py`
  - `write_config_data()` 改为原子写
  - 动态 `providers.<name>.*` 键进入 resolved/config show 链路

- `src/ahadiff/llm/provider.py`
  - 默认 client `trust_env=False`
  - `strict_local` 下拒绝 `trust_env=True` 的注入 client
  - malformed payload 重试
  - provider runtime key 加入 workspace scope
  - 新增 `reset_provider_runtime_state()`
  - `request_hash` 改成事件级加盐
  - Windows loopback/named-pipe 本地传输判定增强
  - 新增 context manager 协议

- `src/ahadiff/llm/probe.py`
  - probe 持久化加锁
  - provider alias 含 `.` 直接拒绝

- `src/ahadiff/llm/cache.py`
  - cache key 改为使用 `diff_content_sha256`

- `src/ahadiff/llm/cost.py`
  - 引入官方来源 pricing book
  - 当前默认 OpenAI 模型支持高置信成本估算

- `src/ahadiff/llm/adapters/anthropic.py`
  - 移除固定 `512` 的默认输出上限

- `src/ahadiff/llm/adapters/azure.py`
  - 支持从 `base_url` query 覆写 `api-version`

- `src/ahadiff/llm/adapters/openai_compat.py`
  - 提取 OpenAI-compatible 共用实现

- `src/ahadiff/cli.py`
  - `provider test` 支持从 `--api-key-env` 环境变量读 key
  - 明文 `--api-key` 直接拒绝
  - alias 含 `.` 直接报错

- 测试
  - `tests/unit/test_provider.py`
  - `tests/unit/test_probe.py`
  - 新增 proxy trust、audit event_id、malformed payload retry、dynamic provider resolved、env key fallback、loopback/npipe、fixture 清理等回归测试

---

## 3. Real Validation

### 定向验证

| 命令 | 结果 |
|------|------|
| `uv run pytest tests/unit/test_provider.py tests/unit/test_probe.py -q` | `32 passed in 0.22s` |
| `uv run pytest tests/unit/test_stage1_task1.py tests/unit/test_allowlist.py tests/unit/test_provider.py tests/unit/test_probe.py -q` | `53 passed in 0.32s` |

### 全量后端基线

| 命令 | 结果 |
|------|------|
| `uv run pytest tests/unit -q` | `161 passed in 2.97s` |
| `uv run ruff check src tests` | `All checks passed` |
| `uv run ruff format --check src tests` | `62 files already formatted` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |

---

## 4. Final Gate

### 当前工作树结论

- **Critical**: 0
- **High**: 0
- **Blocking Medium**: 0

### Gate 判定

**GO**

理由：
- 原交叉审查里真正 blocking 的问题已在当前工作树修复
- 全量 `tests/unit` 与静态检查全部通过
- 仍有若干低优先级改进项与非阻塞残余风险，但不再构成 `NO GO`

---

## 5. Residual Follow-up

后续可继续跟进，但不阻塞当前 Stage 2 / Task 7：

1. 如需覆盖 Anthropic / Gemini / Azure / reseller 的精确 token 计费，可继续扩官方来源 price book
2. 若未来要把审计聚合到更高层级，可重新设计 `request_hash` 的去重与隐私平衡策略
