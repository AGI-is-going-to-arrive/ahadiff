# AhaDiff 第九轮终极审查报告（v0.1→v1.0 全路径）

> **审查模型**：Claude Opus 4.6（主审 + 3 并行代理） + 浏览器实测（Playwright）
> **审查日期**：2026-04-21
> **审查范围**：9 份 P0/P1 文档 + 3 份 HTML 浏览器验证，10 维度
> **方法**：全文档精读 + 代码库交叉搜索 + 浏览器移动端实测 + 代理并行审计

---

## 一、10 维度综合评分

| # | 维度 | 评分 | 等级 | 关键依据 |
|---|------|------|------|---------|
| D1 | v0.1 开工就绪度 | **8.5/10** | A- | Task DAG 正确，29 项 checklist 实际仅 3 项真正未下沉 |
| D2 | 架构一致性 | **9.0/10** | A | 八层架构 vs Task 全覆盖，仅 Graphify enrichment 无独立 Task（设计内延迟） |
| D3 | FSRS-6 方案完整性 | **9.0/10** | A | 全链路 9/9 项定义完备，schema→SQL→UI→optimizer→scaffolding 一致 |
| D4 | 安全模型 | **8.5/10** | A- | 7 类 UNTRUSTED 边界完整，capture pipeline 5 步精确定义 |
| D5 | 跨平台 | **8.0/10** | A- | 10 项闭合，Windows cancel token 设计仍需细化 |
| D6 | 测试策略 | **7.5/10** | B+ | VCR 双层版本完善，benchmark fixture 偏少（7+3） |
| D7 | v0.2 演进可行性 | **8.0/10** | A- | UsageEvent/SourceDetail/InstallTarget 已预留 |
| D8 | v0.3→v1.0 远景 | **7.0/10** | B | .ipynb parser registry 设计完整，PR 安全边界需独立 RFC |
| D9 | 技术栈验证 | **8.5/10** | A- | Python 3.11+/React 19/SQLite WAL/8 Provider 全部验证 |
| D10 | 学习科学 | **8.0/10** | A- | FSRS+Quiz+三段式撤架有 2024-2025 文献支撑 |
| | **总均分** | **8.2/10** | **A-** | |

---

## 二、各维度详细分析

### D1: v0.1 开工就绪度 — 8.5/10

**Task DAG 验证结果**：

- **关键路径**：Task 0→1→5→6→8→9→10→15→16→17 = 10 步串行 ✅
- **并行分组正确**：Layer 1-8 全部无循环依赖 ✅
- **Task 14.5→Task 15 依赖**：DAG 中正确声明（包含 Task 0+13+15） ✅

**发现的问题**：

| ID | 问题 | 严重度 | 状态 |
|----|------|--------|------|
| R9-1 | Task 14.5 定义中缺 Task 13 显式依赖（DAG 正确但定义行遗漏） | Low | 需补 |
| R9-2 | Task 2 有两行"依赖"（一行"无"，一行"Task 0"），格式混乱 | Low | 需清理 |
| R9-3 | closure-checklist-29.md **部分过时**：FIX-14/16/17/18 标记 ⚠️ 但实际已下沉到 Task 文档 | Medium | 需更新 checklist |

**Checklist 真实状态**（代理交叉验证）：

| 状态 | 原标注 | 实际验证 |
|------|--------|---------|
| ✅ 已下沉 | 22 项 | **26 项**（+4 项实际已补入） |
| ⚠️ 真正未下沉 | 7 项 | **仅 3 项**（FIX-13 大 diff ranking / FIX-15 VCR api_family / FIX-29 macOS case-insensitive） |

### D2: 架构一致性 — 9.0/10

**八层架构 vs Task 映射**：

| Layer | 覆盖 Task | 状态 |
|-------|----------|------|
| 0. Schema & Contract | Task 0（21 步） | ✅ 完整 |
| 1. Diff Capture | Task 5（6 种模式 + stdin + compare） | ✅ 完整 |
| 2a. Context Assembly | Task 6（symbol extraction） | ⚠️ Graphify enrichment 无独立 Task |
| 2b. Safety Gate | Task 2（10 步） | ✅ 完整 |
| 2c. Budget & Degrade | Task 5 step 5 + Task 7 step 15 | ✅ 跨 Task 覆盖 |
| 3. Lesson Generation | Task 8 + Task 9 | ✅ 完整 |
| 4. Verification | Task 8 + Task 11 | ✅ 完整 |
| 5. Ratchet | Task 11 + Task 12 | ✅ 完整 |
| 6. Learning | Task 10 + Task 15 | ✅ 完整 |
| 7. Wiki + UI | Task 13 + 14 + 14.5 | ✅ 完整 |

**术语漂移检查**：

| 检查项 | 结果 |
|--------|------|
| head_sha 残留 | 仅在历史/归档文档中，活跃设计文档已统一为 source_ref ✅ |
| SM-2 残留 | 仅用于对比/fallback 说明（"删除 SM-2 字段"、"--scheduler sm2"），无误用 ✅ |
| Jinja2 前端残留 | 活跃文档仅"jinja2 用于 install 模板生成"（正确），但 result.json 有一处 stale 引用 ⚠️ |
| commits/ 路径 | v6.html 已清理 ✅，v2-v5 旧原型和设计手册仍有残留（非权威） ⚠️ |
| contract-freeze.md | 正确不存在（Task 0 产出物） ✅ |

### D3: FSRS-6 方案完整性 — 9.0/10

**全链路 9 项验证**：

| # | 验证项 | 状态 | 定义位置 |
|---|--------|------|---------|
| 1 | ReviewCard FSRS 字段 | ✅ | fsrs-decision.md §4.2 + stages Task 10 step 1 |
| 2 | cards 表 SQL schema | ✅ | fsrs-decision.md §4.3 + stages Task 15 step 1 |
| 3 | scheduler_presets 表 | ✅ | fsrs-decision.md lines 212-220 |
| 4 | review_logs 表 | ✅ | fsrs-decision.md lines 222-231 |
| 5 | 三按钮映射 Good/Hard/Wrong | ✅ | fsrs-decision.md §3.3 |
| 6 | Scaffolding 由 stability 驱动 | ✅ | fsrs-decision.md §3.2.1 (full<3d/hint 3-14d/compact≥14d) |
| 7 | Optimizer 双门槛触发 | ✅ | fsrs-decision.md §3.4 (≥30天 OR ≥max(512,50%)) |
| 8 | Misconception 卡生成 | ✅ | fsrs-decision.md lines 118,124-128 |
| 9 | SM-2 fallback flag | ✅ | fsrs-decision.md line 254, stages Task 15 step 2 |

**发现**：
| ID | 问题 | 严重度 |
|----|------|--------|
| R9-4 | Pydantic 用 `fsrs_card_json` vs SQL 用 `fsrs_state`，字段名不一致 | Low |
| R9-5 | CLAUDE.md 关键设计决策 11 条中无 FSRS-6 独立条目 | Low |

### D4: 安全模型 — 8.5/10

**UNTRUSTED_DIFF 7 类边界**（CLAUDE.md 决策 #9）：

1. ✅ diff 正文
2. ✅ 文件名
3. ✅ commit message
4. ✅ branch/tag 名称
5. ✅ Graphify label
6. ✅ 模型输出
7. ✅ VCR cassette 内容

**Capture Pipeline 5 步顺序**（diff-input-expansion.md）：
```
capture_raw(内存) → secret_scan → parse_patch(在 raw 上) → apply_redaction → persist(仅 redacted)
```
- raw_patch 永不落盘 ✅
- parse 在 raw 上执行保证 AST 准确 ✅
- redaction_pipeline() 作为统一入口 ✅

**隐私三档**：strict_local(默认) / redacted_remote / explicit_remote ✅
**strict_local 检查 transport boundary**（非 provider class）：仅允许 loopback/socket/allowlist ✅
**Allowlist**: hard_block(不可禁) + soft_detect(可 suppress)，v0.1 不支持 regex(防 ReDoS) ✅

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-6 | explicit_remote 降级语义未冻结（用户从 explicit→strict_local 后已发送数据的处理） | Medium |

### D5: 跨平台 — 8.0/10

**10 项闭合验证**：

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | portalocker 文件锁 | ✅ 16+ 引用，Task 0/1/5/12/16 全覆盖 |
| 2 | pathlib 强制 | ✅ 字符串拼接禁止 |
| 3 | locale.getlocale() | ✅ 替代已弃用 getdefaultlocale + Windows ctypes fallback |
| 4 | webbrowser.open() | ✅ 跨平台 |
| 5 | os.replace() 原子重命名 | ✅ |
| 6 | 短路径策略 | ✅ 260 字符预检（实现细节未冻结，Low） |
| 7 | WAL 网络盘 fail-fast | ✅ Task 1 step 7 |
| 8 | Rich auto-detect | ✅ PowerShell 一等 + cmd.exe fallback |
| 9 | CI 三平台矩阵 | ✅ ubuntu+macos+windows |
| 10 | SQLite ≥3.51.3 | ✅ Task 0 step 19 写死版本号 |

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-7 | Windows cancel token 设计未完整下沉到 Task 步骤（FIX-18 closure-checklist 标 ⚠️） | High |

### D6: 测试策略 — 7.5/10

**测试金字塔**：
- Unit Tests: pytest + VCR.py, PR CI ✅
- Integration: 10 pinned diffs ✅
- Eval Tests: 20 benchmark diffs, nightly CI ✅
- 覆盖率: ≥85% 核心路径 ✅

**VCR 双层版本**：
- Run 级：prompts/ tree hash ✅
- Cassette 级：prompt_fingerprint + model_id + rubric_version + output_lang 四元组 ✅

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-8 | Benchmark fixture 仅 7(Python)+3(Non-Python)=10 份，略少 | Medium |
| R9-9 | 覆盖率 85% 目标无 CI gate 强制执行定义 | Low |
| R9-10 | VCR cassette 无自动过期清理（积累可能很大） | Low |

### D7: v0.2 演进可行性 — 8.0/10

**已预留的 Schema**：
- ✅ UsageEvent（14 字段，Task 0 冻结，v0.2 实现 global ledger）
- ✅ SourceDetail（transport/content_format/compare_scope/origin_url/platform）
- ✅ InstallTarget protocol（detect/preview/write/uninstall）
- ✅ degraded_flags 可扩展（v0.2 新增 5 种 key）

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-11 | Global derived governance 多 repo 竞态未定义锁策略 | High（v0.2 前必须冻结） |
| R9-12 | --compare-dir 需新增目录 diff 基础设施 | Medium |
| R9-13 | section-level helpfulness 推迟影响 SRS 有效性反馈 | Medium |

### D8: v0.3→v1.0 远景 — 7.0/10

**已设计**：
- .ipynb: parser registry + EvidenceAnchor 扩展 anchor_kind ✅
- PR 元数据: 只读集成，不写平台 ✅
- 公共 benchmark: manifest.json visibility 字段 ✅

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-14 | .ipynb cell_index 引用需 EvidenceAnchor 预留 Optional[cell_ref] | Medium |
| R9-15 | PR 元数据安全边界需独立 RFC | Medium |
| R9-16 | 公共 benchmark fixture 可能含敏感代码 | Medium |

### D9: 技术栈验证 — 8.5/10

| 技术 | 验证状态 | 备注 |
|------|---------|------|
| Python 3.11+ | ✅ 确认 | locale.getlocale 兼容、tomllib 内置 |
| React 19 + Vite | ✅ 三模型共识 (7-9/10) | Zustand + @tanstack/react-virtual |
| SQLite WAL | ✅ 版本门禁冻结 | ≥3.51.3 + backport 白名单 |
| 8 种 LLM Provider | ✅ adapter 全定义 | ProviderCapabilities 契约已补入 Task 7 |
| Starlette + Uvicorn | ✅ serve 契约冻结 | bind=127.0.0.1 + write token |
| py-fsrs v6.3.1 | ✅ 依赖确认 | desired_retention=0.9 |
| portalocker | ✅ 跨平台锁 | 替代 flock |

| ID | 问题 | 严重度 |
|----|------|--------|
| R9-17 | 8 adapter 维护成本线性增长，v1.0 应抽象 OpenAICompatibleBase | Medium |
| R9-18 | token 估算 Gemini len÷4 + Anthropic ×1.1 系数来源不明 | Low |

### D10: 学习科学 — 8.0/10

| 机制 | 科学支撑 | 证据强度 |
|------|---------|---------|
| SRS 间隔重复 | SM-2 → FSRS-6 (DSR 三分量模型) | **高** (Ye et al. 2024 KDD) |
| 编程学习 SRS | 2024 IEEE 验证 HTML/CSS/JS 有效 | **中高** (Jacinto et al.) |
| FSRS vs SM-2 | 减少 20-30% 复习量 | **中** (RemNote 经验值) |
| 三段式撤架 | Vygotsky ZPD + 认知负荷理论 | **高** |
| Quiz 检索练习 | Testing effect 反复验证 | **高** (Roediger & Karpicke 2006) |
| Claim-Evidence | Self-explanation effect | **中** (Chi et al. 1989) |

**FSRS stability 驱动撤架**是 Codex 改进的创新点，比 SM-2 的固定 interval 映射更科学。

---

## 三、HTML 浏览器验证结果

### 内容一致性 ✅ 全部通过

| 文件 | FSRS 引用 | runs/ 路径 | 无旧技术残留 | Provider 标签 |
|------|----------|-----------|------------|-------------|
| Blueprint.html | ✅ FSRS-6 全文更新 | ✅ 统一 runs/ | ✅ Next.js/LiteLLM 仅"不使用"说明 | ✅ React 19 |
| Competitors.html | ✅ FSRS 对比 section | ✅ 无 commits/ | ✅ 无旧引用 | ✅ |
| v6.html | ✅ | ✅ 4处 runs/ | ✅ 无 Jinja2/LiteLLM | ✅ GPT-5.4-mini/Ollama |

### 移动端布局 ⚠️ 已知问题（Task 4/13 修复范围）

| 文件 | 375px scrollWidth | 溢出 | 根因 |
|------|------------------|------|------|
| v6.html | 651px | **是** | sidebar 固定 280px 不折叠 |
| Competitors.html | 700px | **是** | 竞品矩阵表 1020px 无响应式 |
| Blueprint.html | — | 未测 | 预计类似（固定侧栏布局） |

> **注**：HTML 原型是设计参考，非生产代码。移动端问题已在 Task 4 (UI 响应式修复) + Task 13/14 (React 实现) 中计划修复。

---

## 四、问题汇总清单

### Critical (0)

**无 Critical 问题。**

### High (2)

| ID | 问题 | 修复方案 | 修复时机 |
|----|------|---------|---------|
| R9-7 | Windows cancel token 设计未完整下沉 | Task 7 step 10 补充结构化 cancel token 模式 | Task 7 启动前 |
| R9-11 | v0.2 Global 多 repo 竞态锁策略未定义 | v0.2 前冻结 global file locking protocol | v0.2 前 |

### Medium (7)

| ID | 问题 | 修复时机 |
|----|------|---------|
| R9-3 | closure-checklist 部分过时（4 项误标 ⚠️） | Task 0 期间更新 |
| R9-6 | explicit_remote 降级语义未冻结 | Task 2 启动前 |
| R9-8 | Benchmark fixture 仅 10 份 | Task 18 实施时扩充 |
| R9-12 | --compare-dir 基础设施需新增 | v0.2 |
| R9-13 | section-level helpfulness 推迟 | v0.2 |
| R9-14 | .ipynb EvidenceAnchor 预留 | v0.3 前 |
| R9-17 | 8 adapter 维护成本 → OpenAICompatibleBase | v1.0 |

### Low (5)

| ID | 问题 |
|----|------|
| R9-1 | Task 14.5 定义缺 Task 13 显式依赖 |
| R9-4 | fsrs_card_json vs fsrs_state 字段名不一致 |
| R9-5 | CLAUDE.md 缺 FSRS-6 独立设计决策条目 |
| R9-9 | 覆盖率 85% 无 CI gate |
| R9-18 | token 估算系数来源不明 |

---

## 五、与 Round 8 对比

| 指标 | Round 8 | Round 9（本轮） | 变化 |
|------|---------|----------------|------|
| 审查维度 | 17 维 | 10 维（聚焦 v0.1） | 聚焦 |
| Critical | 0 | 0 | = |
| High | 12 (含 Codex 6 项) | **2**（8 项已修复/确认下沉） | ↓10 |
| Medium | 12 | 7 | ↓5 |
| Low | 8 | 5 | ↓3 |
| Checklist 未下沉项 | 7 | **实际仅 3**（交叉验证发现 4 项已补入） | ↓4 |
| HTML 内容一致性 | PASS | PASS | = |
| 总均分 | ~7.6 (17维) | **8.2** (10维) | ↑0.6 |

**改善归因**：Round 8 的 8 项前置条件已大部分落实到 Task 文档（DBCONFIG_DEFENSIVE、run finalize、transport boundary、Learnability Gate、虚拟列表 dynamic measuring、ProviderCapabilities 等均已写入对应 Task 步骤）。

---

## 六、最终判定

### 评分汇总

| 视角 | 均分 | 判定 | 关键条件 |
|------|------|------|---------|
| 架构完整性 | 9.0 | GO | 八层全覆盖 |
| 工程就绪度 | 8.5 | GO | DAG 正确，仅 3 项真正未下沉 |
| FSRS 方案 | 9.0 | GO | 全链路 9/9 定义完备 |
| 安全模型 | 8.5 | GO | 7 类边界完整 |
| 跨平台 | 8.0 | CONDITIONAL | Windows cancel token 需补 |
| 技术栈 | 8.5 | GO | 全部验证通过 |
| **总体** | **8.2** | **GO** | |

### 最终判定：**GO** ✅

> **与 Round 8 "CONDITIONAL GO" 的区别**：Round 8 提出的 8 项前置条件中，经本轮交叉验证，6 项已确认落地到 Task 文档。剩余 2 项 High 问题（R9-7 Windows cancel token、R9-11 v0.2 global locking）不阻塞 v0.1 开工——R9-7 可在 Task 7 启动前 0.5h 内补入，R9-11 是 v0.2 前置条件。

### GO 条件

1. **Task 0 启动时**（~2h）：
   - 更新 closure-checklist-29.md（4 项误标 ⚠️ 改为 ✅）
   - 补入 FIX-13（大 diff ranking → Task 5）、FIX-15（VCR api_family → Task 18）、FIX-29（macOS case-insensitive → Task 6）
   - CLAUDE.md 补 FSRS-6 为第 12 条设计决策
   - 统一 fsrs_card_json → fsrs_state 字段名

2. **Task 7 启动前**（~0.5h）：
   - Windows cancel token 结构化设计补入 step 10

3. **v0.2 前**：
   - 冻结 global file locking protocol
   - 冻结 explicit_remote 降级语义

### 信心水平

| 阶段 | 信心 | 依据 |
|------|------|------|
| v0.1 可开工 | **高** | 0 Critical, 2 High 均可快速修复，架构完整 |
| v0.2 路径可行 | **中高** | Schema 预留充分，需冻结 global locking |
| v0.3→v1.0 | **中** | parser registry 和 PR 安全需独立 RFC |
| 学习科学假设 | **中高** | 2024-2025 文献支撑 FSRS+scaffolding |

### NO-GO 触发条件（监控项）

- v0.1 beta 用户调研 <30% 开发者有"学回"需求 → 重新评估产品方向
- FSRS py-fsrs 库出现 breaking change 或停止维护 → 评估替代方案

---

## 七、下一步路径

```
本审查 GO ✅
  └─> /ccg:team-plan ahadiff-v01
        └─> 生成可执行计划（含文件分配、依赖顺序、验收标准）
              └─> 按 Stage Gate 分阶段开工
                    Stage 0: Task 0 (Schema Freeze) + 上述 GO 条件
                    Stage 1: Task 1-4 (并行)
                    Stage 2: Task 5-8 (串行+并行)
                    ...
```
