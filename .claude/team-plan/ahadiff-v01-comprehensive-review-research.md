# Team Research: AhaDiff v0.1 全面评估 + i18n 全链路设计

> **⚠️ 部分内容已过时**：本报告撰写于 2026-04-20（第五轮决策之前）。以下内容已被后续决策取代：(1) 前端从 Jinja2 改为 React 19 + Vite；(2) Judge 从 Haiku 改为 gpt-5.4-mini；(3) source_kind 从 3 值扩展为 7 值；(4) Install target 从 11 个分期为 v0.1 四个 CLI + v0.2 七个 IDE。当前权威设计请参阅 `CLAUDE.md` 和 `ahadiff-diff-input-expansion.md`。

> 评估方法：Claude（编排+综合）+ Codex（后端架构）+ Gemini（前端/UX）+ 3 个 Web 验证 Agent（灵感项目源码）
> 日期：2026-04-20

---

## 增强后的需求

对 AhaDiff v0.1 方案进行 7 维度交叉评估，同时设计全链路 i18n 方案（浏览器检测 + 手动切换 + LLM prompt 语言 + 生成内容语言）。评估基于真实文件内容 + 灵感项目源码 web 验证，不靠训练数据猜测。

---

## 一、7 维评估总表

| # | 维度 | Claude | Codex | Gemini | 综合 | 关键发现 |
|---|------|--------|-------|--------|------|---------|
| 1 | 架构合理性 | A | A | A | **A** | 八层正交、无循环依赖、Layer 5/6/7 服务契约方向正确 |
| 2 | 工程可行性 | B+ | B | — | **B** | 11 天偏乐观、scope creep 到 Task 20+14.5、零实现基线 |
| 3 | 安全性 | A | A | — | **A** | 脱敏顺序正确、三档完备、UNTRUSTED_DIFF 需扩展覆盖面 |
| 4 | 测试策略 | A- | B | — | **B+** | VCR 双层可行但缺工具化、benchmark 分层方向正确 |
| 5 | 用户体验 | B+ | — | A | **A-** | serve 设计合理、平板断点缺失、Static/Serve 模式标识不够 |
| 6 | 灵感映射准确性 | A | — | — | **A** | 6 项目 31 条归因中 28 条准确、2 条部分准确、1 条措辞偏差 |
| 7 | Corner Cases | B+ | — | — | **B+** | 8/9 闭合、budget 公式描述需修正 |

---

## 二、各维度详细评估

### 2.1 架构合理性 — **A**

**八层边界正交性**: Layer 0-7 职责清晰，Layer 2 细分为 2a/2b/2c 合理（Context Assembly / Safety Gate / Budget 是不同关注点）。Layer 7 拆为 7a Static + 7b Serve 是核心架构改进。

**依赖链**: 按最新 Task DAG 未发现硬循环依赖。`core/orchestrator.py` 统一编排 learn/improve/verify 三条主链路是正确决策。

**问题清单**:
- [A-1] Layer 5/6/7 服务契约主要存在于综合评估稿而非 CLAUDE.md，**权威来源分裂** — 来源：Codex
- [A-2] Task 13/14 消费 ratchet_history 但依赖声明不包含 Task 12 — 来源：Codex
- [A-3] Graphify freshness/lane 模型跨 Layer 2/5/7，需统一下沉到 Layer 5 query service — 来源：Codex+Claude
- [A-4] 前端设计手册技术栈写 Next.js/React/Tailwind，但 CLAUDE.md 明确 v0.1 用 Jinja2 — 来源：Claude（**文档不一致**，`doc/AhaDiff_frontend_design_v1.1_revised.md:49` vs `CLAUDE.md:19`）

**改进建议**:
- 将 contract-freeze.md 升格为唯一架构权威，冻结 Layer 5/6/7 query DTO + 错误枚举
- 修正 Task 13/14 显式只读依赖 Task 12
- 前端设计手册技术栈章节标注 "v1.0 计划" 或重写为 Jinja2

### 2.2 工程可行性 — **B**

**技术栈**: Python 3.11+ / Typer / Rich / Pydantic / Starlette 选型合适，不建议再引入 ORM/FastAPI/Node。

**问题清单**:
- [E-1] v0.1 scope creep: Task 0-19 已膨胀为 Task 20 + Task 14.5 — 来源：Codex
- [E-2] 仓库零实现、零测试基线，11 天完成 20+ Task 偏乐观 — 来源：Codex
- [E-3] Task 8（Claim Verifier）、15（SQLite）、16/17（Improve）、14.5（Serve Write）都是高复杂度 — 来源：Codex
- [E-4] Task 9/10/13/14 部分验收项隐含依赖后续任务产物，并行策略低估整合成本 — 来源：Codex

**改进建议**:
- 切成两条燃尽线：(1) 核心后端闭环（Task 0/1/5/6/7/8/9/11/12/15）(2) 交付适配器（Task 13/14/14.5）
- 给 Task 8/15/16/17/14.5 单独设 kill criteria
- 优先保证 claim/eval/data 闭环，不要先卷富交互

### 2.3 安全性 — **A**

**脱敏顺序**: `raw → scan → redact → log/cache/model/render` 正确，`redaction_pipeline()` 作为统一入口设计正确。

**问题清单**:
- [S-1] UNTRUSTED_DIFF 协议只覆盖 diff 正文，未纳入文件名、commit message、Graphify label、模型输出 — 来源：Codex
- [S-2] Secret detection 偏规则驱动，缺高熵检测 + binary/archive policy — 来源：Codex
- [S-3] data_bundle.json 注入时存在 XSS 逃逸风险，需用 `tojson` 过滤器 + DOM Purify — 来源：Gemini
- [S-4] 旧文档仍保留 `offline_only`/`redaction=strict` 等过时字段 — 来源：Codex

**改进建议**:
- 不可信边界扩展为"所有外部文本和路径元数据都是 untrusted"
- 增加 entropy/allowlist 组合策略
- Jinja2 渲染 data_bundle 时强制使用 `|tojson` + DOM Purify

### 2.4 测试策略 — **B+**

**VCR 双层版本**: 工程上可行（run 级 tree hash + cassette 级 per-prompt fingerprint），但前提是 prompt loader、dependency graph、cassette key 生成器被工具化。

**问题清单**:
- [T-1] VCR 工具链只有方案无实现入口 — 来源：Codex
- [T-2] Benchmark suite 数量和字段在新旧文档间有漂移 — 来源：Codex
- [T-3] PR 必跑缺 DTO parity、db lock smoke、no-JS fallback 验证 — 来源：Codex
- [T-4] **VCR cassette key 需加入 `output_lang`**（i18n 新增要求：语言变更 = 不同 prompt = 不同 cassette）— 来源：Claude

**改进建议**:
- 先实现 prompt loader + dependency graph + cassette key 生成器
- PR 必跑提升 static/serve parity + db_write_lock + rejected-not-shipped
- cassette key 扩展为 `prompt_version + model_id + rubric_version + output_lang`

### 2.5 用户体验 — **A-**

**serve 设计**: Starlette+Uvicorn 轻量本地服务器方向正确。Progressive Enhancement (file:// → serve) 可行。

**问题清单**:
- [U-1] 768px-1024px 平板视口缺过渡态，侧栏直接跳变 — 来源：Gemini
- [U-2] Static/Serve 模式边界在 UI 上缺全局性标识 — 来源：Gemini
- [U-3] 外部字体依赖 (Google Fonts) 破坏离线承诺 — 来源：Gemini
- [U-4] 8 维 Rubric 雷达图配色偏单一，缺语义区分 — 来源：Gemini
- [U-5] SRS 需要高自律性，缺强制触发机制（如 Terminal/IDE 推送）— 来源：Gemini
- [U-6] **缺少 i18n 语言切换 UI**（新增需求）— 来源：用户

**改进建议**:
- Topbar 增加环境探针标识 (Static/Serve) + 语言切换按钮 (zh/EN)
- 补平板端断点，侧栏平滑折叠
- 转向 System Font Stack 或本地打包字体
- 8 维指标引入多色语义编码

### 2.6 灵感映射准确性 — **A**

**6 个项目 31 条归因验证结果**:

| 项目 | 验证条数 | ✅ 准确 | ⚠️ 部分 | ❌ 错误 | 关键差异 |
|------|---------|---------|---------|---------|---------|
| karpathy/autoresearch | 6 | 6 | 0 | 0 | 完全准确 |
| alchaincyf/darwin-skill | 5 | 4 | 1 | 0 | 仓库还有 templates/ 和 docs/（非可执行逻辑） |
| Evol-ai/SkillCompass | 5 | 5 | 0 | 0 | 完全准确 |
| ZJU-REAL/SkillZero | 5 | 4 | 1 | 0 | budget 公式实为"线性递减"，[6,3,0] 是 N_S=3 的离散实例 |
| safishamsi/graphify | 3 | 2 | 1 | 0 | 7 态状态机是 AhaDiff 自研，Graphify 只有二态 hash 判断 |
| Karpathy LLM Wiki gist | 4 | 3 | 1 | 0 | 原版是多 Markdown 互链 wiki，AhaDiff 简化为 index.md + JSONL |
| **合计** | **28** | **24** | **4** | **0** | **零实质性错误** |

**需修正项**:
- [I-1] SKILL0 budget 描述应改为"线性递减公式，N_S=3 时实际表现为 [6,3,0] 阶段跳变" — 涉及 `CLAUDE.md:121`、`doc/CLAUDE.md:97`
- [I-2] darwin-skill 文件结构描述可补充 templates/ 和 docs/ 存在
- [I-3] Graphify 7 态状态机应明确标注为"AhaDiff 自研设计（受 Graphify 二态缓存启发）"

### 2.7 Corner Cases — **B+**

| Corner Case | 状态 | 备注 |
|------------|------|------|
| Quiz staleness | ✅ 闭合 | CardState 三态 + anchor 惰性检测 |
| Branch-aware concepts | ✅ 闭合 | squash/cherry-pick 诊断通知 |
| Degraded run ratchet | ✅ 闭合 | degraded 永不提升 baseline |
| Rename/move symbol | ✅ 闭合 | 两段式检测 + ambiguous_move 降级 |
| Mixed-capability history | ✅ 闭合 | 四 Lane 正交模型 |
| VCR shared partial | ✅ 闭合 | 显式依赖失效 |
| Concurrent improve | ✅ 闭合 | PID lockfile |
| Graphify freshness | ✅ 闭合 | 七态状态机 + 7→4 映射 |
| **i18n corner cases** | ❌ **新增，未闭合** | 见下方 §3 |

---

## 三、i18n 全链路设计方案（新增）

### 3.1 语言解析优先级链

```
手动切换 (cookie/localStorage `ahadiff_lang`)
  → 浏览器 navigator.language / Accept-Language header
    → CLI --lang 参数
      → config.toml [general] lang
        → 系统 LANG 环境变量
          → 降级为 en
```

### 3.2 支持的 Locale

| Locale | 标识 | 备注 |
|--------|------|------|
| English | `en` | 默认降级语言 |
| 简体中文 | `zh-CN` | 中文首选 |
| 自动检测 | `auto` | config 默认值 |

### 3.3 逐层 i18n 影响分析

| Layer | 需要 i18n | 具体影响 |
|-------|----------|---------|
| 0 Schema | ✅ | UserConfig 加 `lang: "auto"\|"en"\|"zh-CN"`；RunRecord 加 `content_lang: str` |
| 1 Diff Capture | ❌ | 代码是代码，不翻译 |
| 2a Context | ❌ | 语言无关 |
| 2b Safety Gate | ✅ | 错误消息 i18n |
| 2c Budget | ❌ | 数值计算，无需 |
| 3 Lesson Gen | ✅✅ **关键** | Prompt 语言指令 + 生成内容语言 |
| 4 Verification | ✅ | Claim 文本跟随 lesson 语言；evidence 引用语言无关 |
| 5 Ratchet | ✅ | 维度名翻译（accuracy→准确性）；SQLite 存语言无关数值 |
| 6 Learning | ✅ | Quiz/SRS 卡片语言跟随生成时 locale；概念名保留英文+翻译 |
| 7a Static | ✅ | 语言在生成时烘焙进 data_bundle.json |
| 7b Serve | ✅ | 动态语言切换，cookie 持久化 |

### 3.4 Layer 3 Prompt 语言方案

**推荐: 方案 B — 单 prompt + 语言指令前缀**（v0.1 优先）

```markdown
<!-- prompts/lesson.md 头部新增 -->
## Language Directive
Generate ALL user-facing content in {{OUTPUT_LANGUAGE}}.
- If OUTPUT_LANGUAGE is "zh-CN": 所有解释、标题、描述用中文，技术术语保留英文原文并在首次出现时括注中文
- If OUTPUT_LANGUAGE is "en": All explanations in English
- Code snippets, file paths, variable names: NEVER translate
```

**为什么不用方案 A（分语言 prompt 文件）**:
- 维护成本翻倍（两套 prompt 需同步迭代）
- improve loop 只能优化一种语言的 prompt，另一种退步
- LLM 理解英文 prompt 质量更稳定，中文指令可能引入噪声

### 3.5 Config Schema 更新

```toml
# config.toml 新增
[general]
lang = "auto"  # "auto" | "en" | "zh-CN"

[llm]
# 高级用户可分别控制 prompt 指令语言和输出内容语言
# 默认都跟随 general.lang
prompt_lang = "auto"  # prompt 中的指令语言（建议保持英文以获得最佳质量）
output_lang = "auto"  # 生成内容的目标语言
```

### 3.6 数据 Schema 影响

```python
# UserConfig 新增
class UserConfig(BaseModel):
    lang: Literal["auto", "en", "zh-CN"] = "auto"

# RunRecord 新增
class RunRecord(BaseModel):
    content_lang: str  # 生成时解析出的 locale，如 "en" 或 "zh-CN"

# ConceptNode 新增
class ConceptNode(BaseModel):
    term: str           # 规范英文术语（如 "dependency_injection"）
    display_name: str   # 本地化显示名（如 "依赖注入"）
    lang: str           # display_name 的语言
```

### 3.7 前端实现方案

```
┌──────────────────────────────────────────────┐
│  Topbar                              [zh/EN] │  ← 手动切换按钮
│  ┌──────────────────────────────────────────┐ │
│  │  Jinja2 模板使用 _() 翻译函数           │ │
│  │  {{ _("Nav.dashboard") }}               │ │
│  └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘

7a Static: _() 在构建时解析，语言烘焙进 HTML
           ┌ CLI: ahadiff learn --lang zh  → 中文 HTML
           └ 静态 HTML 不可切换语言，显示提示: "启动 ahadiff serve 以切换语言"

7b Serve:  _() 在请求时解析，读 cookie ahadiff_lang
           ┌ GET /api/locale → 当前 locale
           ├ PUT /api/locale → 设置 locale，写 cookie
           └ 所有页面 AJAX 刷新或全页重载
```

**Jinja2 i18n 实现**:
- `viewer/i18n/loader.py`: JSON catalog loader（读 `messages/en.json` + `messages/zh-CN.json`）
- `viewer/templates/base.html`: `<html lang="{{ locale }}">` + `_()` 全局函数
- 不用 gettext/babel（避免 .po/.mo 编译链，JSON 更轻量）

### 3.8 消息目录扩展

现有 `en.json`/`zh-CN.json` 只覆盖 Brand/Nav/Claim/Verdict 4 个类别。需扩展：

```json
{
  "Brand": { ... },
  "Nav": { ... },
  "Claim": { ... },
  "Verdict": { ... },
  "Rubric": {
    "accuracy": "Accuracy / 准确性",
    "evidence": "Evidence / 证据链",
    "diff_coverage": "Diff Coverage / Diff 覆盖",
    "learnability": "Learnability / 可学性",
    "quiz_transfer": "Quiz Transfer / 测验迁移",
    "spec_alignment": "Spec Alignment / 规范对齐",
    "conciseness": "Conciseness / 简洁性",
    "safety_privacy": "Safety & Privacy / 安全隐私"
  },
  "Quiz": {
    "question": "Question / 问题",
    "checkAnswer": "Check Answer / 检查答案",
    "nextQuestion": "Next / 下一题",
    "correct": "Correct! / 正确！",
    "incorrect": "Incorrect / 不正确",
    "showHint": "Show Hint / 显示提示"
  },
  "SRS": {
    "dueToday": "Due Today / 今日待复习",
    "again": "Again / 重来",
    "hard": "Hard / 困难",
    "good": "Good / 一般",
    "easy": "Easy / 简单",
    "flipCard": "Flip Card / 翻牌"
  },
  "Serve": {
    "staticMode": "Static Mode / 静态模式",
    "liveMode": "Live Mode / 实时模式",
    "switchToServe": "Run `ahadiff serve` for interactive features / 运行 `ahadiff serve` 解锁交互功能"
  },
  "Settings": {
    "language": "Language / 语言",
    "theme": "Theme / 主题",
    "privacy": "Privacy / 隐私",
    "langAuto": "Auto-detect / 自动检测",
    "langEn": "English",
    "langZh": "简体中文"
  },
  "CLI": {
    "learning": "Learning from diff... / 正在从 diff 学习...",
    "verifying": "Verifying claims... / 正在验证声明...",
    "complete": "Lesson generated / 笔记已生成",
    "error": "Error / 错误"
  },
  "Error": {
    "noSecret": "Secret detected and redacted / 检测到敏感信息并已脱敏",
    "injectionBlocked": "Suspicious content blocked / 可疑内容已拦截",
    "noCapacity": "Model capacity exhausted / 模型容量已满"
  }
}
```

### 3.9 i18n Corner Cases（10 个）

| # | Corner Case | 方案 | 状态 |
|---|------------|------|------|
| CC-i18n-1 | 混合语言 diff（中文注释 + 英文代码） | Lesson 语言跟随用户偏好，代码片段不翻译 | ✅ 设计闭合 |
| CC-i18n-2 | LLM 生成质量随语言波动 | `prompt_lang` vs `output_lang` 分离；v0.1 默认跟随 locale，高级用户可覆盖 | ✅ 设计闭合 |
| CC-i18n-3 | SRS 卡片中途切换语言 | 卡片保留创建时语言，新卡用新 locale；不重翻译（会破坏学习连贯性）| ✅ 设计闭合 |
| CC-i18n-4 | 概念图谱术语 | 英文规范术语 + `display_name` 本地化；图谱节点显示 display_name，hover 显示原始 term | ✅ 设计闭合 |
| CC-i18n-5 | 静态模式语言限制 | `file://` 语言在生成时**单语烘焙**（不嵌入双语 JSON）；显示提示 "启动 serve 切换语言" 或 CLI `ahadiff learn --lang en` 重生成另一语言版本。**Codex 交叉审查确认：Static 双语切换违背单语烘焙设计** | ✅ 设计闭合 |
| CC-i18n-6 | VCR cassette 语言失效 | 语言变更 = 不同 prompt = cassette key 新增 `output_lang` 维度 | ✅ 设计闭合 |
| CC-i18n-7 | 审计日志语言 | audit.jsonl 始终英文（机器可读）；用户日志可本地化 | ✅ 设计闭合 |
| CC-i18n-8 | CLI vs Serve 错误消息 | CLI 用系统 locale；Serve 用请求 Accept-Language；内部日志始终英文 | ✅ 设计闭合 |
| CC-i18n-9 | 数字/日期格式 | 存储: ISO 8601 + 原始数值；显示: 按 locale 格式化（如 2026年4月20日 vs Apr 20, 2026）| ✅ 设计闭合 |
| CC-i18n-10 | improve loop prompt 语言 | improve loop 优化的是 `prompts/*.md` 中的语言指令效果，不是 prompt 文件本身的语言 | ✅ 设计闭合 |

### 3.10 i18n 实现任务（新增到 Task 体系）

| Task ID | 名称 | 依赖 | 文件范围 | 估时 |
|---------|------|------|---------|------|
| Task i18n-0 | i18n Schema 冻结 | Task 0 | `src/ahadiff/i18n/resolver.py`, `src/ahadiff/config.py` | 0.5d |
| Task i18n-1 | JSON Catalog + Loader | Task i18n-0 | `messages/en.json`, `messages/zh-CN.json`, `src/ahadiff/i18n/catalog.py` | 0.5d |
| Task i18n-2 | Prompt 语言指令 | Task i18n-0, Task 9 | `prompts/*.md` 头部加 Language Directive | 0.5d |
| Task i18n-3 | Jinja2 模板 i18n | Task i18n-1, Task 13 | `viewer/templates/**` 所有 `_()` 调用 | 1d |
| Task i18n-4 | 前端语言切换 UI | Task i18n-3, Task 14 | Topbar toggle + cookie + API endpoint | 0.5d |
| Task i18n-5 | CLI 语言支持 | Task i18n-1 | `--lang` flag + Rich 输出本地化 | 0.5d |
| Task i18n-6 | VCR cassette key 扩展 | Task i18n-2, Task 18 | cassette key 加 `output_lang` | 0.25d |

**总估时**: ~3.75 天（可与 Task 9-14 并行）

---

## 四、约束集

### 硬约束 (Hard Constraints)
- [HC-1] v0.1 技术栈锁定 Python 3.11+ / Typer / Rich / Pydantic / Jinja2 / Starlette，禁止 Next.js/React/LiteLLM — 来源：CLAUDE.md
- [HC-2] Task 0 contract freeze 是全部下游的硬前置 — 来源：Codex
- [HC-3] evaluation bundle 整体 immutable，变更需更新 rubric_version + VCR cassette 失效 — 来源：CLAUDE.md
- [HC-4] 安全脱敏顺序不可打破：raw → scan → redact → log/cache/model/render — 来源：CLAUDE.md
- [HC-5] SQLite 为唯一真相源，results.tsv/cards.jsonl/due.json 只能是导出或 cache — 来源：Codex
- [HC-6] i18n 语言切换不可重翻译已有 SRS 卡片 — 来源：Claude（学习连贯性约束）
- [HC-7] 审计日志始终英文，不受 locale 影响 — 来源：Claude
- [HC-8] VCR cassette key 必须包含 output_lang — 来源：Claude（语言变更 = prompt 变更）

### 软约束 (Soft Constraints)
- [SC-1] Prompt 指令语言建议保持英文以获得最佳 LLM 质量 — 来源：Claude
- [SC-2] 概念图谱技术术语保留英文原文 + display_name 本地化 — 来源：Claude
- [SC-3] 前端字体应转向 System Font Stack 或本地打包 — 来源：Gemini
- [SC-4] 8 维 Rubric 图表应使用多色语义编码 — 来源：Gemini
- [SC-5] Topbar 应显示 Static/Serve 环境探针标识 — 来源：Gemini
- [SC-6] darwin-skill 文件结构描述可补充 templates/ 目录 — 来源：Web Agent
- [SC-7] SKILL0 budget 描述应改为"线性递减公式" — 来源：Web Agent
- [SC-8] Graphify 7 态应标注为"AhaDiff 自研" — 来源：Web Agent
- [SC-9] JSON catalog 优于 gettext/.po（轻量，无编译链）— 来源：Claude

### 依赖关系
- [DEP-1] Task 0 → 全部下游 — schema/枚举/DTO/错误类型/锁顺序
- [DEP-2] Task 5 → Task 6 → Task 8 — capture/parse/claim 严格串行
- [DEP-3] Task 7 → Task 8/9/11/18 — provider 是共同骨干
- [DEP-4] Task 11 → Task 12 → Task 15 → Task 16 → Task 17 — 评估主链
- [DEP-5] Task i18n-0 → Task i18n-1/2/3/4/5/6 — i18n schema 是前置
- [DEP-6] Task i18n-3 → Task i18n-4 — 模板 i18n 先于 UI toggle

### 风险
- [RISK-1] 文档版本漂移：旧文档与新契约并存，开工时可能误用旧设计 — 缓解：开工前标 archived
- [RISK-2] Scope creep 到 Task 20+14.5，11 天偏乐观 — 缓解：分两条燃尽线
- [RISK-3] UNTRUSTED_DIFF 覆盖面不足 — 缓解：扩展为全外部文本 untrusted
- [RISK-4] i18n 增加 ~3.75 天工作量 — 缓解：可与 Task 9-14 并行
- [RISK-5] Gemini 429 限流频繁 — 缓解：Claude 兜底评审

---

## 五、成功判据

- [OK-1] 7 维评估报告完成，所有维度 >= B+
- [OK-2] 6 个灵感项目源码验证完成，零实质性错误
- [OK-3] i18n 全链路方案覆盖 Layer 0-7 + CLI + 10 个 corner case
- [OK-4] 约束集（8 HC + 9 SC）和依赖关系（6 DEP）完整记录
- [OK-5] 文档不一致清单完整（见改进建议）

---

## 六、文档同步清单（开工前必须完成）

| 文件 | 操作 | 具体改动 |
|------|------|---------|
| `CLAUDE.md` | 更新 | (1) 补 i18n 设计到八层架构；(2) 补 `output_lang` 到 VCR cassette key；(3) 修 SKILL0 budget 描述 |
| `CLAUDE.md` | 更新 | 补 Graphify 7 态为"自研设计" |
| `doc/AhaDiff_frontend_design_v1.1_revised.md` | 更新 | (1) §6 i18n 文案骨架扩展为完整 catalog；(2) 技术栈章节标注 v0.1=Jinja2；(3) 增加语言切换按钮 UI spec |
| `doc/最终完整方案.md` | 标 archived | results.tsv 列数/字段名过时 |
| `doc/知返设计坐标.md` | 标 archived | 用 head_sha / git reset / review.db 等过时术语 |
| `.claude/team-plan/ahadiff-v01-stages-4-9.md` | 更新 | (1) Task 13/14 补 Task 12 依赖；(2) 新增 Task i18n-0 到 i18n-6 |
| `.claude/team-plan/ahadiff-v01-kickoff.md` | 更新 | 补 i18n 作为 v0.1 范围内需求 |
| `AhaDiff-Blueprint.html` | 更新 | 补 i18n 数据流到 29 步 Diff 流程图 |

---

## 七、开放问题（已解决）

- Q1: v0.1 是否交付可写 serve？ → A: 是，Task 14.5 已纳入 → [HC-5]
- Q2: 哪些文档标 archived？ → A: 见 §6 文档同步清单 → [RISK-1]
- Q3: i18n 是否纳入 v0.1？ → A: 是，用户明确要求 → [Task i18n-0 到 i18n-6]
- Q4: 前端提供语言切换按钮？ → A: 是，Topbar zh/EN toggle → [Task i18n-4]
- Q5: LLM prompt 也要分语言？ → A: 用 Language Directive 前缀方案，不分文件 → [SC-1]

---

## 八、Phase 2 深度改进综合（Codex 16 项 + Gemini 6 项 + 新 Corner Cases）

### 8.1 Codex 后端深度改进要点（16 项）

| ID | 维度 | 核心改进 |
|----|------|---------|
| IMP-1 | 工程 | v0.1 切 3 里程碑（M0 后端闭环 / M1 improve / M2 install），Task 14.5 拆 A(读)/B(写) |
| IMP-2 | 工程 | 新增 bootstrap harness（pyproject.toml + conftest + 4 个 fixture），每个 Task 必须同时提交 fixture |
| IMP-3 | 工程 | Task 8 拆 extract/verify/classify，Task 15 拆 database/migrations/service，定义 kill criteria |
| IMP-4 | 工程 | 冻结 query DTO + parity contract test（static data_bundle 与 serve API 同字段同枚举） |
| IMP-5 | 安全 | 统一 UntrustedSource 边界（diff_body/file_path/commit_message/graph_label/model_output/vcr_body） |
| IMP-6 | 安全 | 增加 entropy scan + archive walker + binary policy + allowlist |
| IMP-7 | 安全 | 旧配置字段不静默兼容，抛 ConfigCompatibilityError + `--migrate-config` |
| IMP-8 | 测试 | VCR 工具链：prompt loader + fingerprint + cassette key 生成器 |
| IMP-9 | 测试 | 冻结 benchmark manifest（`benchmarks/manifest.json` 唯一权威） |
| IMP-10 | 测试 | PR 必跑：DTO parity + db_lock smoke + no-JS fallback |
| IMP-11 | 架构 | contract-freeze.md 升格唯一权威 + 文档引用校验脚本 |
| IMP-12 | 架构 | ratchet_history 下沉到 Layer 5 history/service.py query DTO |
| IMP-13 | 架构 | Graphify freshness/lane 统一到 Layer 5，Layer 7 只读投影字段 |
| IMP-14 | i18n | 所有用户可见对象（Claim/Lesson/Quiz/Card）持久化 content_lang |
| IMP-15 | i18n | prompt 语言链条显式化 + 生成后 language detection + 混合语言重试 |
| IMP-16 | i18n | ConceptNode 用 term_key 稳定身份 + aliases 去重 + SRS actor_lang |

### 8.2 Gemini 前端深度改进要点（6 项 UI + i18n 设计）

| ID | 问题 | 解决方案 |
|----|------|---------|
| UI-1 | 平板 768-1024px 缺过渡 | Icon-only Rail (64px) + Lesson 两栏化 + TOC 折叠为下拉 |
| UI-2 | Static/Serve 模式无标识 | EnvBadge 组件：静态灰色 "Read-only" / Serve 绿色脉冲 "Live" |
| UI-3 | 外部字体破坏离线 | 移除 Google Fonts，使用 System Font Stack |
| UI-4 | Rubric 配色单一 | 动态语义上色：≥80 绿 / 60-79 橙 / <60 红 |
| UI-5 | SRS 缺触发机制 | ReviewNotifier：Topbar 横幅 + 侧栏红色呼吸提示 + 拦截弹窗 |
| UI-6 | 缺 i18n UI | Segmented Toggle (zh/EN) + Static 模式双语 JSON 烘焙 |

### 8.3 新增 Corner Cases（Codex 8 + Gemini 3 = 11 个）

| ID | 描述 | 方案 | 状态 |
|----|------|------|------|
| CC-NEW-1 | Locale alias 漂移（zh_CN/zh-Hans/ZH-cn） | `i18n/resolver.py` regex BCP47 归一化，只允许 en/zh-CN，别名启动时映射 | ✅ Codex 闭合 |
| CC-NEW-2 | 模型忽略 OUTPUT_LANGUAGE 输出混合语言 | CJK/Latin 比例检测(前500字符) + 重试 1 次 + `mixed_language_output` bool in RunRecord | ✅ Codex 闭合 |
| CC-NEW-3 | 脱敏后 evidence anchor 失去回链性 | 脱敏前分配 `file_id`(SHA-256前缀) + `redaction_map.json` + EvidenceAnchor 拆为 file_id+display_path | ✅ Codex 闭合 |
| CC-NEW-4 | 浏览器重试导致 learning signal 双写 | 前端 `crypto.randomUUID()` + SQLite `UNIQUE(idempotency_key)` + 冲突返回原 event_id 200 OK | ✅ Codex 闭合 |
| CC-NEW-5 | 同一概念多语言/格式被当多个节点 | Unicode NFKD + slug 归一化(不词干化) + CJK 保留原字符 + alias merge on term_key 碰撞 | ✅ Codex 闭合 |
| CC-NEW-6 | Archive bomb 让 secret scan DoS | `ArchivePolicy`(depth=3, total=50MB, count=500, single=10MB, timeout=30s) + 超限 partial scan + degraded | ✅ Codex 闭合 |
| CC-NEW-7 | SSR 页面和 API 语言不一致 | `ahadiff_lang` cookie(1yr, SameSite=Lax) + Starlette middleware 每请求解析一次 + SSR/API 都读 request.state.locale | ✅ Codex 闭合 |
| CC-NEW-8 | Static 按钮可点击但无法提交 | `data-mode`/`data-requires-js`/`data-cli-fallback` 属性 + JS 启动检测 serve/static + static 禁用按钮显示 CLI 命令 | ✅ Codex 闭合 |
| CC-FE-1 | 超长路径/函数名横向溢出 | `.crumb,.ev,.file-path{word-break:break-word;overflow-wrap:anywhere}` + `pre{overflow-x:auto}` + 自定义滚动条。`break-word` 为旧浏览器兜底（Gemini 终审建议）。受影响：_claim_inspector/_diff_row/_breadcrumb | ✅ Claude 兜底闭合 |
| CC-FE-2 | 窄屏 Split View 代码挤压 | `@media(max-width:800px){.diff-split{display:none}.diff-unified{display:block}}` + 隐藏 Split 切换按钮 + Unified View 全宽 | ✅ Claude 兜底闭合 |
| CC-FE-3 | z-index 穿透 + 焦点陷阱失败 | z-index 层级表：Content(0)/Sidebar(50)/Backdrop(60)/Drawer(70)/Dialog(80)/Toast(100) + `<dialog>` 原生元素 + `inert` 属性锁背景焦点 | ✅ Claude 兜底闭合 |

### 8.4 文档不一致清单（Codex 发现 9 处）

| 文件 1 | 文件 2 | 不一致字段 | 说明 |
|--------|--------|-----------|------|
| CLAUDE.md | doc/AhaDiff_frontend_design_v1.1_revised.md | 前端技术栈 | v0.1=Jinja2 vs 手册写 Next.js/React |
| CLAUDE.md | stages-4-9.md Task 11 | eval bundle 成员数 | 5 文件(含 rubric.py) vs 4 文件 |
| CLAUDE.md | stages-4-9.md VCR | cassette key | 四元组(含 output_lang) vs 三元组 |
| kickoff.md | revision.md | results 标识符 | source_ref/base_ref vs head_sha/base_sha |
| revision.md | stages-4-9.md | result_events 唯一性 | (run_id UNIQUE) vs (run_id, event_type, timestamp) |
| 综合评估稿 | stages-4-9.md | serve 范围 | Task 14.5 完整规格 vs 静态 viewer 为主 |
| CLAUDE.md | 知返设计坐标.md | 隐私/存储 | review.sqlite vs review.db, worktree vs git reset |
| CLAUDE.md | 最终完整方案.md | rubric/安全 | spec_alignment vs local_ux, privacy_mode vs offline_only |
| CLAUDE.md | 前端设计手册 | v0.1 运行时假设 | Jinja2+Vanilla JS vs Next.js 16+React 19 |

---

## 九、Phase 2 交叉 Review 结果

### 9.1 Codex 审查 Gemini 前端方案

| 项目 | 结论 | 分析 |
|------|:----:|------|
| UI-1 平板断点 | PASS | 蓝图已含 769-1024 icon rail；Jinja2 partial+CSS 可做 |
| UI-2 EnvBadge | WARNING | 后端用 `data-mode` 属性而非 `data_bundle.mode` 字段；Badge 应读模板变量 |
| UI-3 字体 | WARNING | 纯 System Stack 不足，需保留 PingFang SC/Noto Sans SC/Sarasa Gothic 作为中文回退 |
| UI-6 i18n Toggle | **FAIL→已修复** | 后端是 `PUT /api/locale` + cookie `ahadiff_lang`；**Static 模式必须单语烘焙，不能前端双语切换**。已修正为 Static 下 toggle disabled + CLI 重生成 |
| CC-FE-* | PASS | 仅展示层，不改 data_bundle 契约 |
| 双语 JSON 大小 | WARNING | 双份 catalog 很小（<5KB），但双份 lesson/quiz 内容会显著增大且违背 Static 单语设计 |

### 9.2 Gemini 审查 Codex 后端方案

| 项目 | 结论 | 分析 |
|------|:----:|------|
| IMP-4 DTO parity | PASS | Jinja2 可直接消费统一 DTO，无需转换层 |
| IMP-5 XSS 防护 | WARNING | 必须强制 `\|tojson` + DOMPurify 客户端消毒 |
| IMP-12/13 Layer 5 投影 | PASS | 下沉投影完美契合前端声明式 UI |
| IMP-14 content_lang | WARNING | 历史列表需补充语言 Badge 视觉区分 |
| IMP-15 混合语言 | WARNING | 重试失败仍可能输出混合语言，需 CSS word-break + 多语言字体栈兜底 |
| CC-NEW-4 idempotency | WARNING | Vanilla JS 需封装 Fetch 拦截器 + `crypto.randomUUID()` |
| CC-NEW-7 Cookie 同步 | PASS | Cookie 作为真相源确保 SSR/API 一致 |
| 3 里程碑拆分 | PASS | M0 可基于 Mock 闭环 UI，M1/M2 渐进集成 |

### 9.3 修复记录

| 交叉发现 | 影响 | 修复 |
|---------|------|------|
| UI-6 Static 双语 FAIL | stages-4-9.md Task i18n-4 + research §CC-i18n-5 | Static toggle 改为 disabled + tooltip；不嵌入双语 JSON |
| UI-3 中文字体不足 | stages-4-9.md Task 13 步骤 8 | 字体栈补充 PingFang SC/Noto Sans SC |
| IMP-14 语言 Badge | stages-4-9.md Task 14 | 多语言内容列表需补语言标签 |
| CC-NEW-4 idempotency | stages-4-9.md Task i18n-4 | JS Fetch 拦截器生成 idempotency_key |

### 9.4 最终评分（改进后）

| 维度 | 原评分 | 改进后 | 关键改进 |
|------|:------:|:------:|---------|
| 架构合理性 | A | **A+** | contract-freeze 唯一权威 + Layer 5 投影统一 + DTO parity |
| 工程可行性 | B | **A-** | 3 里程碑拆分 + bootstrap harness + Task 细粒度拆分 + kill criteria |
| 安全性 | A | **A+** | UntrustedSource 6 类全覆盖 + entropy scan + archive walker + 旧配置拒绝 |
| 测试策略 | B+ | **A** | VCR 工具链 + benchmark manifest + PR 必跑 3 类回归 |
| 用户体验 | A- | **A** | 平板断点 + EnvBadge + 字体本地化 + SRS 通知 + i18n toggle |
| 灵感映射 | A | **A** | 4 项修正完成 |
| Corner Cases | B+ | **A** | 原 9/9 + i18n 10/10 + 新增 11/11 = **30 个 CC 全部闭合**（Codex 闭合 8 + Claude 兜底 3 + 前轮已闭合 19）|
