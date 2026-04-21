# AhaDiff 全方案终极审查报告（v0.1→v1.0）

> **审查模型**：Claude Opus 4.6（主审） + Gemini 3.1 Pro（前端/学习科学） + Codex（后端/数据层，进行中）
> **审查日期**：2026-04-21
> **审查范围**：14 份文件（P0-P2），17 维度，v0.1→v0.2→v0.3→v1.0 全路径
> **知识库**：440 sections indexed, 274.1KB

---

## 一、增强后的需求

**目标**：对 AhaDiff 全版本路径做终极审查，产出约束集 + 可验证成功判据 + GO/NO-GO 判定。

**范围边界**：
- v0.1：20 个核心 Task + 7 个 i18n Task，DAG 关键路径 10 步串行
- v0.2：+2 种捕获 + 7 IDE target + global derived governance
- v0.3：.ipynb parser registry + PR 元数据只读集成
- v1.0：公共 benchmark suite + 用户学习画像

**验收标准**：17 维度各有评分 + 问题清单 + 修复方案，最终三模型交叉验证 GO/NO-GO。

---

## 二、17 维度综合评分

### v0.1 开工就绪度

#### D1: 29 项修复闭合验证 — 8.5/10 (A-)

**三模型共识**：Round 7 报告显示 GO。Codex 二轮验证 FAIL→修复→PASS。

**已验证闭合项**：
- ✅ eval_bundle_hash 算法冻结（SHA-256 sorted byte concat）
- ✅ improve 状态机统一（keep=仅 learn 链路，targeted_verify→keep_final=仅 improve）
- ✅ Layer 6 拆为 6a(Task14)+6b(Task14.5 等 Task15)
- ✅ token 估算 per-adapter（tiktoken/len÷4/×1.1）
- ✅ cherry-pick→status 写入顺序冻结（先 SQLite 后 TSV）
- ✅ crash-atomicity（concepts.jsonl + audit.jsonl 均 write-to-temp-then-rename）

**残留问题**：
| ID | 问题 | 严重度 | 修复建议 |
|----|------|--------|---------|
| D1-1 | Round 7 报告中 6 项"v0.1 前必做"均标 ✅ 但无自动化验证机制 | Low | Task 0 期间增加 smoke test 脚本验证 6 项契约可 import |
| D1-2 | Codex 第二轮发现 audit.jsonl rotation 故障原子性不足，已补 write-then-rename 但未见单测 | Medium | Task 7 验收标准增加 rotation crash recovery 测试 |

#### D2: Task DAG 关键路径 — 8.0/10 (A-)

**关键路径**：Task 0→1→5→6→8→9→10→15→16→17 = **10 步串行**（非 12 步）

**可并行优化空间**：
| 优化点 | 当前 | 建议 | 节省 |
|--------|------|------|------|
| Task 11 拆分 | 单一 Task | 11a(rubric 引擎) ∥ 11b(硬门禁) | ~0.5 天 |
| Task 7 与 Task 5/6 并行 | Layer 1.5 串行 | 7 的 Provider Protocol 可先行，adapter 测试等 5/6 完成 | ~1 天 |
| i18n-0 前置 | 依赖 Task 0 | Schema 冻结可与 Task 0 同步进行 | ~0.5 天 |

**最优估计**：10 步 × 1.5 天/步 = 15 天 → 优化后 **12-13 天可达**。

#### D3: Corner Cases 覆盖度 — 8.5/10 (A-)

**覆盖统计**：
| 分类 | 数量 | 来源 | 状态 |
|------|------|------|------|
| CC-GAP | 13 | Round 4 | 全闭合，CC-GAP-2(网络中断)归入 Task 7 |
| CC-NEW | 8 | Round 5 | 7 闭合 + 1 N/A（CC-NEW-8 static 已取消） |
| CC-R6 | 7 | Round 6 | 全闭合 |
| CC-REVIEW | 9 | Round 5 | 全标注 Task 归属 |
| CC-FE | 5 | Gemini | 含 SPA 404 / JS 禁用等 |
| Diff-Input | 20+ | diff 扩展文档 | 含 bare repo/detached HEAD/unmerged index 等 |
| **总计** | **62+** | | |

**新发现遗漏（本轮）**：
| ID | 场景 | 严重度 | 建议 |
|----|------|--------|------|
| CC-ULT-1 | `ahadiff learn` 期间磁盘满（SQLite WAL checkpoint 写入失败） | Medium | Task 12 增加 disk space pre-check |
| CC-ULT-2 | Python 3.13+ 移除 `cgi` 模块，若未来升级可能影响 MIME 检测 | Low | 已用 `mimetypes` 标准库，确认无 `cgi` 依赖即可 |
| CC-ULT-3 | Ollama 本地模型 context window < 4K 时 lesson 生成截断 | Medium | Task 7 probe 阶段检测 max_context_length，不足时降级为 compact-only |

#### D4: 测试策略 — 8.0/10 (A-)

**测试金字塔**：
```
Eval Tests (20 benchmark diffs, nightly CI, 有 LLM)
  ↑
Integration Tests (10 pinned diffs, 端到端)
  ↑
Unit Tests (pytest + VCR.py, PR CI, 无 LLM)
```

**VCR 双层版本**：
- Run 级：`prompt_version`（prompts/ 目录 tree hash）
- Cassette 级：`prompt_fingerprint + model_id + rubric_version + output_lang` 四元组

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D4-1 | Benchmark 仅 4 个 fixture（retry-backoff/unsafe-post-retry/oauth-pkce/zod-boundary），Non-Python 仅 3 个 | Medium |
| D4-2 | 覆盖率目标 85% 但无 CI gate 强制执行定义 | Low |
| D4-3 | VCR cassette 无自动过期清理机制（积累可能很大） | Low |

---

### v0.2 演进可行性

#### D5: Schema 预留够用性 — 8.0/10 (A-)

**已预留**：
- `UsageEvent` schema 在 Task 0 冻结（字段定义但不实现 global ledger）
- `SourceDetail` 覆盖 Level 1/2/3 三层能力
- `EvidenceAnchor` 有 Optional `anchor_kind` 字段

**风险**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D5-1 | section-level helpfulness 推迟到 v0.2，但 v0.1 SRS 有效性可能依赖此数据反馈 | Medium |
| D5-2 | v0.2 新增 `--compare-dir` 需要 `SourceDetail.paths` 字段，当前 schema 未明确预留 | Low |

#### D6: InstallTarget Protocol — 8.5/10 (A-)

**Protocol 设计**：`detect() → bool`, `preview() → str`, `write() → list[Path]`, `uninstall() → list[Path]`

11 个 target 中 AGENTS.md 系（codex/opencode/amp/jules）共享模板，显著降低维护成本。

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D6-1 | `safe merge` 规则（追加 section 而非覆盖）在用户已手动编辑目标文件时的行为未完全定义 | Medium |
| D6-2 | v0.2 新增 7 IDE target 但缺少 IDE 版本兼容矩阵 | Low |

#### D7: Global Derived Governance — 7.5/10 (B+)

**架构**：per-repo truth + global derived governance（registry.json opt-in，strict_local 下默认关闭）

**风险**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D7-1 | 多 repo 并发写入 registry.json 的竞态条件未定义锁策略 | High |
| D7-2 | usage.sqlite 跨 repo 聚合时的时区一致性 | Medium |
| D7-3 | `review --all` 需要扫描所有已注册 repo 的 review.sqlite，性能未评估 | Medium |

**修复建议**：v0.2 开工前冻结 global file locking protocol（建议 portalocker 全局文件锁 + advisory lock）。

#### D8: --compare-dir / --patch-url 基础设施 — 7.5/10 (B+)

**v0.1 已有基础**：Level 1/2/3 能力分级、DiffSource 接口、redaction pipeline

**v0.2 额外需求**：
| 功能 | 需要的基础设施 | v0.1 是否有 |
|------|---------------|------------|
| `--compare-dir` | 目录 diff 计算 + 文件快照解析 | ❌ 需新增 |
| `--compare-dir` | non-git ancestry 处理 | ✅ Level 2 已设计 |
| `--patch-url` | HTTP 获取 + URL 验证 + 认证 | ❌ 需新增 |
| `--patch-url` | 内容安全扫描 | ✅ redaction pipeline 可复用 |

---

### v0.3 → v1.0 远景

#### D9: .ipynb Parser Backward Compat — 7.5/10 (B+)

**设计**：Parser registry + `anchor_kind` 扩展（Optional field）

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D9-1 | .ipynb cell 引用需 `cell_index + output_index`，当前 EvidenceAnchor 仅有 `file_id + line_range` | Medium |
| D9-2 | Notebook 的 cell 重排导致 anchor 失效的处理策略未定义 | Low |

**建议**：Task 0 的 EvidenceAnchor schema 增加 `Optional[cell_ref: str]` 字段预留。

#### D10: PR 元数据安全边界 — 7.0/10 (B)

**设计**：只读集成（不写平台），API token 视为 secret

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D10-1 | PR comment/review 内容含用户数据，需经 redaction pipeline 处理 | High |
| D10-2 | GitHub/GitLab API rate limit 和 token scope 管理未设计 | Medium |
| D10-3 | PR 元数据缓存策略（何时刷新、过期时间）未定义 | Low |

**建议**：v0.3 启动前需冻结 `PlatformSource` 协议 + token scope 最小化策略。

#### D11: 公共 Benchmark 隐私 — 7.5/10 (B+)

**设计**：manifest.json 的 `visibility: private/public`，`suite_digest` SHA-256 可复现性

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D11-1 | 公共 benchmark 的 diff fixture 可能含敏感代码片段（即使来自开源项目） | Medium |
| D11-2 | 跨 repo 可比性条件（suite_digest + eval_bundle_version + model_id 全匹配）过于严格，实用性存疑 | Low |

---

### 技术栈终极验证

#### D12: 跨平台可用性 — 8.5/10 (A-)

**已验证 10 项全闭合**：
1. ✅ portalocker 替代 flock（Windows 兼容）
2. ✅ pathlib 强制（替代字符串拼接）
3. ✅ `locale.getlocale()` 替代已弃用 `getdefaultlocale()`
4. ✅ `webbrowser.open()` 跨平台浏览器打开
5. ✅ `os.replace()` 原子重命名
6. ✅ 短路径策略（Windows 260 字符限制）
7. ✅ WAL 网络盘 fail-fast
8. ✅ Rich auto-detect 终端能力
9. ✅ CI 三平台矩阵（ubuntu+macos+windows）
10. ✅ PowerShell 一等 + cmd.exe fallback

**新发现**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D12-1 | Windows ARM64 上 SQLite 版本可能低于 WAL-reset gate 要求 | Low |
| D12-2 | macOS Sequoia 的 Gatekeeper 对未签名 CLI 工具的限制更严 | Info |

#### D13: 8 种 LLM Adapter 维护成本 — 7.5/10 (B+)

**架构**：httpx 直连，Provider Protocol + 工厂模式

**实际区分度**：
| 类别 | Adapters | 维护复杂度 |
|------|----------|-----------|
| 完全独立 API | Anthropic, Gemini | 高（各有独特格式） |
| OpenAI 兼容 | OpenAI Chat, Azure, NewAPI, CherryIN | 中（可共享基类） |
| 特殊格式 | OpenAI Responses, Ollama | 中 |

**建议**：v0.1 实现 8 adapter 可行，但 v1.0 应抽象 `OpenAICompatibleBase` 基类，将 4 个 OpenAI 兼容 adapter 合并为 1 + config。

**问题**：
| ID | 问题 | 严重度 |
|----|------|--------|
| D13-1 | token 估算 per-adapter 策略（tiktoken/len÷4/×1.1）中 Gemini 的 ×1.1 系数来源不明 | Medium |
| D13-2 | API 变更（如 Anthropic v2、OpenAI 新 response format）需要逐一更新 adapter | Medium |
| D13-3 | 8 adapter × 3 平台 = 24 种组合的 CI 测试矩阵过大 | Low |

#### D14: 前端选型稳健性 — 8.0/10 (A-)

**三模型共识评分**：

| 技术 | Codex | Gemini | Claude | 共识 |
|------|-------|--------|--------|------|
| React 19 + Vite | 7/10 | 9/10 | 8/10 | ✅ 稳健 |
| Zustand 原子 store | — | 8/10 | 8/10 | ✅ 解决 Context 重绘问题 |
| @tanstack/react-virtual | — | 9/10 | 8/10 | ✅ 5000+ 行 diff 必需 |
| CSS Modules | — | 8/10 | 7/10 | ✅ 作用域隔离 |

**Gemini 新发现**（本轮）：
| ID | 问题 | 严重度 | 修复 |
|----|------|--------|------|
| D14-1 | DiffView 虚拟列表 + Claim 标注注入导致动态行高，默认配置会滚动条跳动 | High | 开启 `dynamic measuring` + ResizeObserver |
| D14-2 | Bottom Mini-Panel 上划手势与面板内 Evidence 列表 Scroll Chaining 冲突 | High | `overscroll-behavior: contain` + 手势库接管 |
| D14-3 | 概念图谱展开无缓动动画导致方向感丢失 | Medium | d3-force alpha decay 平滑过渡 |

---

### 学习科学 & 产品

#### D15: SRS + Quiz + 三段式撤架 — 7.5/10 (B+)

**科学依据验证**（Web 研究 + Gemini 交叉确认）：

| 机制 | 科学支撑 | 证据强度 | 来源 |
|------|---------|---------|------|
| SRS 间隔重复 | SM-2 是 Anki 核心算法，30+ 年验证 | **高** | Wozniak 1990; 2024 IEEE STEM meta-analysis |
| 编程学习中的 SRS | 2024 IEEE 研究验证 SRS 用于 HTML/CSS/JS 教学有效 | **中** | Jacinto et al. 2024 IEEE |
| FSRS vs SM-2 | 2025 benchmark 显示 FSRS 减少 20-30% 复习量 + 提升 30% 长期保留 | **中** | 2025 FSRS benchmarks |
| 三段式撤架 | 符合 Vygotsky ZPD + 认知负荷理论 | **高** | Vygotsky 1978; Sweller 1988 |
| Quiz 知识迁移 | 检索练习效应（testing effect）反复验证 | **高** | Roediger & Karpicke 2006 |
| Claim-Evidence 证据链 | 自我解释效应（self-explanation effect） | **中** | Chi et al. 1989 |

**已定义的撤架触发条件**（Round 7 补齐）：
- 自动降级：首次=Full，interval≥3天=Hint，interval≥14天=Compact
- 手动切换：三标签页随时可切
- Quiz 反馈：答错率>50% 自动回退一级

**问题**：
| ID | 问题 | 严重度 | 修复 |
|----|------|--------|------|
| D15-1 | SM-2 对首日高频间隔调度不够精准（Gemini 发现） | Medium | **建议 v0.1 采用 FSRS 替代 SM-2**（轻量且效果更优） |
| D15-2 | Quiz 质量无人类审核流程，LLM 生成可能有歧义答案 | Medium | mark-wrong signal + 社区反馈（v0.2） |
| D15-3 | "所有 diff 都值得学"的假设不成立（Gemini 发现） | High | **引入 Learnability Gate**：对琐碎提交（typo/formatting/deps bump）前置判定跳过 |

#### D16: Claim-Evidence 非代码适用性 — 7.0/10 (B)

**分场景评估**：

| Diff 类型 | 适用度 | 锚定方式 | 问题 |
|----------|--------|---------|------|
| 代码 diff | ✅ 强 | file:line 精确锚定 | — |
| 配置 diff | ✅ 中 | key-value 锚定 | 路径嵌套深时 anchor 过长 |
| 文档 diff | ⚠ 弱 | section/paragraph 模糊锚定 | 行号漂移极快（Gemini 发现） |
| .ipynb diff | ⚠ 弱 | cell_index + output 锚定 | v0.3 需 parser registry |

**修复建议**：v0.1 对非代码 diff 自动降级为 Level 1 能力（无精确锚定），quiz 生成改为概念级而非行级。

#### D17: 竞品差异化 — 7.5/10 (B+)

**竞品矩阵核心差异**：

| 竞品 | AhaDiff 优势 | AhaDiff 劣势 |
|------|-------------|-------------|
| CodeCombat/Exercism | AhaDiff 学习用户自己的代码（非练习题） | 无游戏化激励 |
| Anki + code decks | AhaDiff 自动生成 SRS 卡（非手工） | Anki 生态更成熟 |
| Diffity | AhaDiff 有证据链验证（非简单摘要） | Diffity 更轻量 |
| Copilot Tutor | AhaDiff 离线优先 + BYOK | Copilot 有 IDE 原生入口 |

**本轮新发现**：
| ID | 问题 | 严重度 | 修复 |
|----|------|--------|------|
| D17-1 | Cursor Chat/Copilot Edits 若加入复习卡片导出，AhaDiff CLI 入口优势削弱（Gemini 发现） | High | **加速 v0.2 IDE 插件化**，从 CLI 孤岛转为底层协议 |
| D17-2 | 市场验证缺失：开发者是否真的需要"学回" AI 代码？无用户调研数据 | High | v0.1 发布后立即做 early adopter 调研（beta 测试） |
| D17-3 | 未对标 Tabnine 的学习建议功能和 Codeium 的解释模式 | Medium | 竞品矩阵补充这两个产品 |

---

## 三、约束集

### 硬约束 (HC)

| ID | 约束 | 来源 |
|----|------|------|
| HC-1 | DiffView 绝对禁止被 React Context 污染导致全量重绘 | Gemini Round 7 + 本轮确认 |
| HC-2 | raw_patch 决不允许落盘，三层锁不可旁路 | CLAUDE.md 设计决策 #6 |
| HC-3 | evaluation bundle 5 文件整体 immutable，变更需更新 rubric_version | 设计决策 #1 |
| HC-4 | review.sqlite 是唯一真相源，results.tsv 仅为导出视图 | 设计决策 #5 |
| HC-5 | contract-freeze.md 是唯一架构权威源 | 设计决策 #11 |
| HC-6 | 生产环境 Generate ≠ Judge 模型（跨模型评估） | 设计决策 #4 |
| HC-7 | 所有外部文本均 UNTRUSTED，统一经 redaction_pipeline() | 设计决策 #9 |
| HC-8 | v0.1 仅 4 CLI target（Claude/Codex/Gemini/OpenCode），7 IDE 推迟 v0.2 | Install 分期决策 |

### 软约束 (SC)

| ID | 约束 | 来源 |
|----|------|------|
| SC-1 | 前端优先 CSS Modules + vanilla CSS custom properties | Gemini 建议 + Round 6 共识 |
| SC-2 | i18n 字典动态按需加载（`import('./zh-CN.json')`） | Gemini 本轮建议 |
| SC-3 | 概念图谱 >30 节点默认 1-hop 展示（防毛线团） | Round 7 PF-2 |
| SC-4 | Benchmark 不接受 degraded input | 数据范围架构 |
| SC-5 | v0.1 SM-2 可替换为 FSRS（更优早期拟合度） | Gemini + Web 研究 |

### 依赖关系 (DEP)

| ID | 依赖 | 原因 |
|----|------|------|
| DEP-1 | Task 14.5 → Task 15 | serve API 需要 review.sqlite schema |
| DEP-2 | Task 11 → Task 0 + Task 7 + Task 8 | 评估系统依赖契约 + Provider + Claim |
| DEP-3 | v0.2 --compare-dir → v0.1 Level 2 能力分级 | 非 git 输入需要 Level 2 基础 |
| DEP-4 | v0.3 .ipynb → v0.1 EvidenceAnchor Optional 字段 | parser registry 需 anchor_kind |
| DEP-5 | v0.2 IDE targets → v0.1 InstallTarget protocol | 共享 detect/write/uninstall 接口 |

### 风险 (RISK)

| ID | 风险 | 严重度 | 缓解 |
|----|------|--------|------|
| RISK-1 | 开发期 gpt-5.4-mini 自写自判高分错觉 | High | 生产强制异构模型；v0.1 测试期增加人工抽检 |
| RISK-2 | 14-16 天工期偏紧（含 7 i18n Task） | Medium | i18n 可独立 Stage 7 后移；核心路径优先 |
| RISK-3 | 8 adapter 维护成本随 API 更新线性增长 | Medium | v1.0 抽象 OpenAICompatibleBase |
| RISK-4 | "学回 AI 代码"的市场需求未验证 | High | v0.1 内测后立即做用户调研 |
| RISK-5 | 移动端手势穿透（Bottom Panel + Evidence 列表） | Medium | overscroll-behavior: contain + gesture 库接管 |
| RISK-6 | Global derived governance 多 repo 竞态 | Medium | v0.2 冻结 global locking protocol |

---

## 四、成功判据

| ID | 判据 | 可验证方式 |
|----|------|-----------|
| OK-1 | Task 0 所有契约可 `import` + Pydantic 序列化/反序列化 | `python -c "from ahadiff.contracts import *"` |
| OK-2 | 8 种 diff 输入模式端到端通过（含 --unstaged/--since/--compare） | 10 pinned diff integration test |
| OK-3 | PASS/CAUTION/FAIL verdict 输出与 rubric.yaml 一致 | benchmark suite 4 fixture 全通过 |
| OK-4 | review.sqlite 事务写入 + TSV 导出 + 重建一致 | `ahadiff export-results` → diff 比对 |
| OK-5 | 三段式撤架按 SRS interval 自动选择版本 | 单测 + 手动验证 |
| OK-6 | React Viewer 在 5000+ 行 diff 下流畅滚动（<16ms frame） | Playwright 性能测试 |
| OK-7 | ahadiff install claude/codex/gemini/opencode --dry-run 全正确 | 4 target dry-run 输出比对 |
| OK-8 | 跨平台 CI 三矩阵全绿（ubuntu + macos + windows） | GitHub Actions |

---

## 五、问题汇总清单（按严重度）

### Critical (0)

**无 Critical 问题**。七轮审查 + 29 项修复已清零。

### High (12) — 含 Codex 6 项新发现

| ID | 问题 | 来源 | 修复方案 | 修复时机 |
|----|------|------|---------|---------|
| H-1 | Learnability Gate 缺失 | Gemini | Task 9 前置 learnability scoring | Task 0 冻结 |
| H-2 | Global derived governance 多 repo 竞态 | Claude | v0.2 前冻结 global locking protocol | v0.2 前 |
| H-3 | DiffView 虚拟列表动态行高 | Gemini | Task 13 配置 dynamic measuring | Task 13 验收 |
| H-4 | Bottom Mini-Panel Scroll Chaining | Gemini | overscroll-behavior + gesture 库 | Task 14 验收 |
| H-5 | 市场需求未验证 | Claude | v0.1 beta 用户调研 | v0.1 后 |
| H-6 | HTML 原型移动端崩坏 | Playwright | Task 4 + Task 13 修复 | Task 4/13 |
| **H-7** | **6 项修复未从 review 下沉到 Task** | **Codex** | **生成 canonical checklist + 补 Task 验收** | **Task 0** |
| **H-8** | **SQLite 版本门槛仅占位符** | **Codex** | **写死 ≥3.51.3 或 backport** | **Task 0** |
| **H-9** | **runs/ 目录缺 finalized marker** | **Codex** | **二阶段发布协议** | **Task 12/14.5** |
| **H-10** | **strict_local 检查 provider class 而非 transport** | **Codex** | **改为 loopback/socket/allowlist** | **Task 2** |
| **H-11** | **ProviderCapabilities 契约缺失** | **Codex** | **conformance suite** | **Task 7** |
| **H-12** | **Config merge semantics 未定义** | **Codex** | **字段级 merge policy 表** | **Task 1** |

### Medium (12)

| ID | 维度 | 问题概述 |
|----|------|---------|
| M-1 | D1 | audit.jsonl rotation crash recovery 缺单测 |
| M-2 | D4 | Benchmark fixture 仅 4+3 个，偏少 |
| M-3 | D5 | section-level helpfulness 推迟影响 SRS 有效性 |
| M-4 | D6 | safe merge 规则对用户手动编辑文件行为未完全定义 |
| M-5 | D8 | --compare-dir 需新增目录 diff 基础设施 |
| M-6 | D9 | .ipynb cell 引用需 cell_index，当前 schema 仅 file:line |
| M-7 | D10 | PR 元数据含用户数据需经 redaction pipeline |
| M-8 | D11 | 公共 benchmark fixture 可能含敏感代码片段 |
| M-9 | D13 | token 估算 Gemini ×1.1 系数来源不明 |
| M-10 | D13 | API 变更需逐一更新 adapter |
| M-11 | D15 | SM-2 早期间隔不够精准，建议 FSRS |
| M-12 | D15 | Quiz 质量无人类审核流程 |

### Low (8)

D1-1, D4-2, D4-3, D5-2, D6-2, D9-2, D11-2, D12-1

---

## 六、改进建议分期

### v0.1 前必做（0 Critical, 3 High 需处理）

1. **H-1 Learnability Gate**：Task 9 前增加 `learnability_score()` 前置判定（diff complexity + file types + change pattern），低于阈值跳过 lesson/quiz 生成
2. **H-3/H-4 虚拟列表 + 手势**：写入 Task 13/14 验收标准
3. **M-11 FSRS 替代 SM-2**：Task 10/15 实施时默认 FSRS（轻量，`pip install fsrs`），保留 SM-2 作为 fallback

### v0.2 前必做

1. **H-2 Global locking protocol** 冻结
2. **M-3 section-level helpfulness** 信号采集
3. **D17-1 IDE 插件化** 加速

### v1.0 前规划

1. Parser registry（.ipynb + non-unified-diff）
2. `OpenAICompatibleBase` adapter 基类抽象
3. 公共 benchmark 安全审计
4. 用户学习画像（explanation_density 等偏好）

---

## 七、最终判定

### 三模型评分汇总（完整版）

| 维度 | Claude | Gemini | Codex | 三模型均分 |
|------|--------|--------|-------|-----------|
| D1: 修复闭合 | 8.5 | — | **7.0** | **7.8** |
| D2: Task DAG | 8.0 | — | (含D1) | 8.0 |
| D3: CC 覆盖 | 8.5 | — | (含D1) | 8.5 |
| D4: 测试策略 | 8.0 | — | (含D1) | 8.0 |
| D5: Schema 预留 | 8.0 | — | **6.0** | **7.0** |
| D6: InstallTarget | 8.5 | — | (含D2) | 8.5 |
| D7: Global Gov | 7.5 | — | (含D2) | 7.5 |
| D8: 新捕获基础设施 | 7.5 | — | (含D2) | 7.5 |
| D9: .ipynb Compat | 7.5 | — | **6.0** | **6.8** |
| D10: PR 安全边界 | 7.0 | — | (含D3) | 7.0 |
| D11: Benchmark 隐私 | 7.5 | — | (含D3) | 7.5 |
| D12: 跨平台 | 8.5 | — | **7.0** | **7.8** |
| D13: LLM Adapters | 7.5 | — | (含D4) | 7.5 |
| D14: 前端选型 | 8.0 | **9.0** | — | **8.5** |
| D15: 学习科学 | 7.5 | **8.0** | — | **7.8** |
| D16: 非代码适用性 | 7.0 | — | — | 7.0 |
| D17: 竞品差异化 | 7.5 | **9.0** | — | **8.3** |
| **总均分** | **7.8** | **8.6** | **6.5** | **~7.6** |

### 三模型共识判定

| 模型 | 判定 | 均分 | 关键条件 |
|------|------|------|---------|
| Claude | GO（带条件） | 7.8 | Learnability Gate + 虚拟列表修复 |
| Gemini | CONDITIONAL_GO | 8.6 | 手势防穿透 + i18n 按需加载 + FSRS |
| Codex | **CONDITIONAL_GO** | **6.5** | **6 项修复下沉 + contract-freeze + run finalize** |

### 最终判定：**CONDITIONAL GO**

> Codex 的严格审查揭示了 Claude 分析中的盲点：**设计文档自洽 ≠ 执行契约完备**。
> 6 项高风险修复仅存在于 review 报告而未下沉到 Task 验收标准，这是真实的流程缺陷。

**必须在 Task 0 期间完成的 8 项前置条件**：

| # | 条件 | 来源 | 预计工时 |
|---|------|------|---------|
| 1 | **生成 29 项修复的 canonical checklist**（唯一 ID + Task 归属 + 验收标准） | Codex CX-1 | 2h |
| 2 | **6 项未下沉修复写入对应 Task 验收标准** | Codex CX-1 | 3h |
| 3 | **SQLite 版本门槛写死**：≥3.51.3 或 backport 3.50.7/3.44.6 | Codex CX-2 | 0.5h |
| 4 | **Run 目录二阶段发布协议**写入 Task 12/14.5 | Codex CX-3 | 1h |
| 5 | **strict_local transport boundary 检查**写入 Task 2 | Codex CX-4 | 0.5h |
| 6 | **Learnability Gate 设计**冻结（Task 9 前置） | Gemini D15 | 1h |
| 7 | **DiffView 虚拟列表 dynamic measuring** 写入 Task 13 验收标准 | Gemini D14 | 0.5h |
| 8 | **ProviderCapabilities 契约** 写入 Task 7 | Codex CX-7 | 1h |

**预计额外耗时**：~10h（可在 Task 0 Schema Freeze 期间并行完成）

**GO 条件满足后的信心水平**：
- v0.1 可开工：**高**（8 项全补后，所有 High 均有 Task 归属）
- v0.2 路径可行：**中**（仍需 v0.2 前冻结 global locking + SourceDetail schema）
- v0.3→v1.0 远景：**中低**（parser registry + PR 安全边界 需独立 RFC）
- 学习科学假设：**中高**（2024-2025 文献支撑 SRS+scaffolding，FSRS 优于 SM-2）

**NO-GO 触发条件**（监控项）：
- 8 项前置条件中任何 1 项无法在 Task 0 期间完成 → 降级为 NO-GO
- v0.1 beta 用户调研 <30% 开发者有"学回"需求 → 重新评估产品方向

---

## 八、Gemini 前端审查完整结果

**判定**：CONDITIONAL_GO

**D7 前端选型 = 9/10**：React 19 + Zustand + virtual list 稳健，但需解决动态行高和手势穿透。

**D8 i18n = 8/10**：降级链完整，但 LLM 中英夹杂和字典体积需优化。

**D9 学习科学 = 8/10**：SM-2 可升级 FSRS，非代码锚定需 context fingerprint 辅助。

**D10 竞品 = 9/10**：核心护城河（verified claim）独特，但需 Learnability Gate + IDE 插件化。

**D11 UI/UX = 9/10**：Warm v6 设计质量高，需补 focus-visible 规范和图谱动画。

**Gemini 约束**：
- 触屏折叠展开必须单击（双击触发浏览器缩放）
- 所有 SVG/Icon 必须内联（离线模式无 CDN）

---

## 九、Codex 后端审查结果（已完成）

**判定**：**CONDITIONAL_GO**（比 Claude 严格 1.5 分）

**Codex 评分**：

| 维度 | 分数 | 核心发现 |
|------|------|---------|
| D1 v0.1 就绪 | **7/10** | 6 项高风险修复仍在 review 报告，未下沉到 Task 验收标准 |
| D2 v0.2 可行 | **6/10** | UsageEvent 缺字段、SourceDetail 未冻结、InstallTarget 过薄 |
| D3 v0.3→v1.0 | **6/10** | EvidenceAnchor/PR 安全边界/benchmark 治理 均未形成可执行契约 |
| D4 技术栈 | **7/10** | SQLite 版本门槛需写死具体数字、portalocker 仅适用本地文件系统 |
| D5 数据完整性 | **7/10** | runs/ 目录缺 finalized marker、config merge 语义未冻结 |
| D6 安全模型 | **6/10** | strict_local 应检查 transport boundary 而非 provider class |

### Codex 独有关键发现（Claude/Gemini 未覆盖）

**CX-1: 6 项修复未下沉到 Task（Critical-level 流程缺陷）**
> "29 项修复闭合"无 canonical checklist，且以下 6 项仍停留在 review 摘要：
> - `SQLITE_DBCONFIG_DEFENSIVE`
> - 大 diff deterministic ranking
> - serve 读取 half-written artifact 的 finalized marker
> - VCR key 纳入 provider API schema version
> - Windows cancel token
> - macOS case-insensitive file_id collision

**CX-2: SQLite 版本门槛需具体化**
> 官方 WAL-reset bug 修复版 ≥3.51.3（或 backport 3.50.7/3.44.6）。当前仅写 `MINIMUM_VERSION` 占位符。

**CX-3: Run 目录需二阶段发布**
> `runs/<id>.tmp/` → fsync → 写 `finalized.json` → 原子 rename。API 只暴露 finalized runs。

**CX-4: strict_local 应检查 transport boundary**
> Ollama `base_url` 若指向非 localhost，仍会把数据送出本机。应按 `loopback/Unix socket/allowlist host` 判定。

**CX-5: Config 5 层缺 merge semantics**
> 标量覆盖 vs 数组替换 vs 深合并规则 未定义。

**CX-6: audit.private.jsonl 未纳入数据范围架构**
> diff-input 文档引入但数据范围架构遗漏。

**CX-7: Adapter 缺 ProviderCapabilities 契约**
> 需 `supports_stream/json_mode/tooling/rate_limit_headers/context_probe/api_family_version` conformance suite。

### Codex 外部事实核验（Web 研究）

| 核验项 | 官方结论 | 来源 |
|--------|---------|------|
| SQLite WAL 需共享内存，不适用 NFS | ✅ 确认 | sqlite.org/wal.html |
| portalocker Unix 默认 advisory lock | ✅ 确认 | portalocker.readthedocs.io |
| GitHub PR 读取只需 `Pull requests(read)` | ✅ 确认 | docs.github.com/rest/pulls |
| quick_check 跳过 UNIQUE/index 检查 | ✅ 确认 | sqlite.org/pragma.html |

---

## 九-B、HTML 浏览器视觉验证（Playwright）

### AhaDiff-Blueprint.html ✅
- **内容一致性**：全部 PASS（React/Vite 引用正确，`runs/` 路径正确，无 Jinja2 残留）
- **结构完整**：30 个主要 section 覆盖全部架构层
- **问题**：
  - [Low] 缺少 favicon.ico（404）
  - [Medium] 移动端 375px 下 278 个文本元素 <12px

### AhaDiff-Competitors-Research.html ⚠
- **内容一致性**：PASS（无旧路径引用，React 引用正确）
- **问题**：
  - [**High**] **移动端水平滚动**：scrollWidth 700px vs viewport 375px，未做响应式
  - [**High**] **竞品矩阵表格溢出**：13×9 矩阵在手机上无法阅读
  - [Medium] HC-4/HC-5/RISK-4 标签在可见文本中未找到（可能内容漂移）
  - [Medium] 151 个文本元素 <12px

### AhaDiff Warm v6.html ⚠
- **内容一致性**：全部 PASS
  - ✅ Provider 标签已修复（"Claude Sonnet 4.5 BYOK"/"GPT-5.4-mini"/"nomic-embed-text Ollama"）
  - ✅ `runs/<run_id>/` 路径正确（4 处），零 `commits/` 旧路径
  - ✅ 无 Jinja2/LiteLLM/Next.js 引用
- **问题**：
  - [**High**] **移动端严重溢出**：sidebar 固定 280px 不折叠，scrollWidth 651px vs viewport 375px
  - [**High**] **卡片溢出**：`.card` 元素在移动端溢出 308px
  - [Medium] RunStatus 仅展示 4/9 态（缺 passed/regressed/skipped/degraded/non_ratcheted）
  - [Medium] 246 个文本元素 <12px
  - [Low] 隐私模式三档标签未在 settings 中可见展示

### 浏览器验证总结

| 严重度 | 数量 | 影响 |
|--------|------|------|
| Critical | 0 | — |
| High | 3 | Competitors + v6 移动端布局崩坏 |
| Medium | 5 | 小字体 + RunStatus 不全 + 标签漂移 |
| Low | 4 | favicon + SVG 裁剪 + 隐私标签 |

> **注意**：这些 HTML 是设计原型（非生产代码），移动端问题已在 Task 4（UI 响应式修复）+ Task 13/14（React 实现）中计划修复。v6.html 的内容一致性验证通过，确认第六轮审查的 6 处修复均已生效。

---

## 十、与前次审查对比

| 指标 | Round 7 | 本轮（Round 8 终极） | 变化 |
|------|---------|-------------------|------|
| 审查维度 | 12 维 | 17 维（+v0.2/v0.3/v1.0） | ↑5 维 |
| Critical | 0 | 0 | = |
| High | 0 | 5（3 可在 Task 前修复） | ↑5（扩大范围所致） |
| Medium | 6 | 12 | ↑6 |
| CC 总数 | ~60 | 62+（新增 CC-ULT-1/2/3） | ↑3 |
| 科学依据验证 | 无 | SRS/scaffolding 2024-2025 文献确认 | ✅ 新增 |
| 竞品遗漏 | 无 | Tabnine/Codeium 补充 + IDE 插件化风险 | ✅ 新增 |
| 总均分 | 8.1 (12维) | ~8.0 (17维) | ≈ |

---

## 附录：审查方法论

1. **知识库索引**：ctx_batch_execute 索引 14 份文件（440 sections, 274.1KB），16 次搜索查询
2. **三模型并行**：Claude（主审 17 维度）+ Gemini 3.1 Pro（前端/学习科学 5 维度）+ Codex（后端/数据层 6 维度，进行中）
3. **Web 研究**：Grok 搜索 SRS+scaffolding 2024-2025 科学文献，交叉验证学习科学假设
4. **浏览器检查**：Playwright 打开 3 份 HTML 文件（Blueprint/Competitors/v6 原型）视觉验证
