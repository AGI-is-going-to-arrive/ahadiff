# 37 条借鉴点纳入决策表

> 来源：`.claude/team-plan/ahadiff-competitors-research.md` Part G
> 决策依据：Codex 后端分析 + Gemini 前端/UX 分析 + Claude 综合编排
> 日期：2026-04-20
> **v4 — 三轮三模型交叉 review 后最终版**
>
> **核心原则**：所有 37 条均为"借思想/机制 + AhaDiff 特化重写"，无一条可直接照搬原项目代码。

---

## 决策总览

| 分类 | 条数 | 占比 |
|------|:---:|:---:|
| **纳入 v0.1** | 10 | 27% |
| **已覆盖**（现有设计已有 AhaDiff 变体） | 10 | 27% |
| **延后 v0.2+** | 13 | 35% |
| **不适用** | 4 | 11% |

### 优先级校正（vs 原始标注）

- **P0 不应照搬**：#2（5列TSV，与 HC-15 的 10 列冲突）、#9（eval_mode 列，同上）、#18（quick-scan，v0.1 deterministic verifier 已够）
- **P1 应升档为 P0**：#34（按语言排序，是 #32/#33 clip 策略的必要配套）
- **P0 已被现有设计吸收**：#1 #7 #14 #15 #20 #24 #35（不需要再单独立项）

---

## 逐条决策表

### G.1 autoresearch（6 条）

| # | 借鉴点 | 原级 | 决策 | 理由 | 落地模块 |
|:--:|---|:--:|---|---|---|
| 1 | `^key:value` stdout 协议 | P0 | **已覆盖** | HC-10 已冻结 `^wiki_score:` 协议 | L5 `eval/evaluator.py` |
| 2 | 5 列 TSV 日志 | P0 | **已覆盖** | HC-15 已固定 10 列，不回退 | L5 `eval/results.py` |
| 3 | `gc.disable()` + 定期 collect | P2 | **延后 v0.2+** | CLI/LLM 主路径无证据表明 GC 是瓶颈 | — |
| 4 | 时间预算制 TIME_BUDGET | P1 | **延后 v0.2+** | v0.1 已有 token/cost/round budget，时间预算需真实数据 | — |
| 5 | NEVER STOP 自主循环 | P1 | **不适用** | 与 `improve --rounds N` + 成本门禁 + 人工确认点冲突 | — |
| 6 | redirect stdout+stderr 到 run.log | P0 | **纳入 v0.1** | `> run.log 2>&1`；**必须写入 `.ahadiff/runs/<run_id>/run.log`**（HC-1）；**场景分治**：`improve/eval/benchmark/agent-run` 默认纯 log 禁 tee；`learn/verify` 人类 CLI 可选 tee 回显精简进度 | L5 `runs/<run_id>/run.log` |

### G.2 darwin-skill（6 条）

| # | 借鉴点 | 原级 | 决策 | 理由 | 落地模块 |
|:--:|---|:--:|---|---|---|
| 7 | 8 维加权 Rubric + 严格 `>` | P0 | **已覆盖** | 8 维体系 + 严格改进规则已写进设计 | L5 `eval/rubric.py` |
| 8 | test-prompts.json 测试集 | P1 | **已覆盖** | v0.1 已有 benchmark fixture 等价方案 | L5 `benchmarks/` |
| 9 | results.tsv 增 eval_mode 列 | P0 | **不适用** | 与 HC-15 固定 10 列直接冲突 | — |
| 10 | 文件体积 >150% 阈值拒提交 | P1 | **延后 v0.2+** | v0.1 先用简洁性准则更稳 | — |
| 11 | 异常处理决策表（10 场景） | P0 | **纳入 v0.1** | git/revert/TSV 失败路径多，缺显式决策表会让 ratchet 不可靠 | L5 `core/errors.py` + `eval/ratchet.py` |
| 12 | HTML 卡片 3 主题 + 截图 | P2 | **延后 v0.2+** | v0.1 只做 Warm 单主题，多主题增加前端资产维护成本 | — |

### G.3 SkillCompass（10 条）

| # | 借鉴点 | 原级 | 决策 | 理由 | 落地模块 |
|:--:|---|:--:|---|---|---|
| 13 | eval-result.json Schema 强制 | P0 | **纳入 v0.1** | `score.json` 需稳定、机器可读 contract | L5 score report schema |
| 14 | D3 Security Gate | P0 | **已覆盖** | 安全 hard gate 已在 Task 2 + Task 11 锁定 | L2 + L5 |
| 15 | 减分制 + fatal cap | P0 | **已覆盖** | 扣分制 + 维度门禁已存在于设计 | L5 `rubric.py` + `gates.py` |
| 16 | output-guard.js 双级检查 | P1 | **延后 v0.2+** | agent-hook 增强，非 v0.1 主链路 | — |
| 17 | hooks.json PostToolUse | P1 | **延后 v0.2+** | 等 Task 19 install 稳定后再做 | — |
| 18 | quick-scan 三维快扫+缓存 | P0 | **延后 v0.2+** | deterministic verifier 已够闭环，需真实 latency 数据 | — |
| 19 | Tier 分类+Few-shot+算术验证行 | P0 | **纳入 v0.1** | 显著降低 judge 漂移和总分算错风险 | L5 judge prompts |
| 20 | `<<<UNTRUSTED>>>` 边界标记 | P0 | **已覆盖** | prompt injection 边界已在安全层规划 | L2 `safety/injection.py` |
| 21 | version-manifest.json | P1 | **延后 v0.2+** | prompt_version+rubric_version+git 已满足追溯 | — |
| 22 | V1-V7 统计指标+ASCII 图表 | P1 | **延后 v0.2+** | 需 benchmark 跑通后再建统计分析 | — |

### G.4 graphify（7 条）

| # | 借鉴点 | 原级 | 决策 | 理由 | 落地模块 |
|:--:|---|:--:|---|---|---|
| 23 | SHA256 内容寻址缓存 | P0 | **纳入 v0.1** | 本地 CLI 成本控制关键，collision key 必须一开始设计对 | L2 `llm/cache.py` |
| 24 | 枚举型 Schema 验证 | P0 | **已覆盖** | Pydantic + enum 常量已在设计中 | L3/L4 schemas |
| 25 | `_normalize_id()` 容错 | P1 | **延后 v0.2+** | graph overlay 深化后收益更大 | — |
| 26 | 平台字典驱动 install | P2 | **已覆盖** | Task 19 install registry 已吸收 | install/registry |
| 27 | benchmark token 缩减比 | P1 | **延后 v0.2+** | graphify 接入稳定后再做 | — |
| 28 | report.py 纯字符串拼接 | P1 | **不适用** | 代码风格偏好，非产品/架构增益 | — |
| 29 | PreToolUse hook 条件注入 | P1 | **延后 v0.2+** | graphify 为可选上下文，v0.1 不做默认 hook | — |

### G.5 Qodo PR-Agent（8 条）

| # | 借鉴点 | 原级 | 决策 | 理由 | 落地模块 |
|:--:|---|:--:|---|---|---|
| 30 | `__new/old hunk__` 格式化 | P0 | **纳入 v0.1** | 借协议思路，但需 AhaDiff 特化：PR-Agent 只给 new hunk 行号，AhaDiff 需 old/new 双侧可锚定（evidence viewer 需要） | L1 `git/parser.py` |
| 31 | YAML 输出+Pydantic 验证 | P0 | **纳入 v0.1** | 借"YAML 约束 + validator"模式；Pydantic 模型必须 AhaDiff 自研（PR-Agent 的是 review object，非 claim/lesson） | L3/L4 `claims/extract.py` |
| 32 | 双缓冲区 token 预算 | P0 | **纳入 v0.1** | 借 soft/hard buffer 机制；常量 1500/1000 是 PR-Agent 特定值，AhaDiff 需根据自身 prompt 结构重新标定 | L2 `llm/provider.py` |
| 33 | large_patch_policy skip/clip | P0 | **纳入 v0.1** | 借 skip/clip 语义名；必须同步 `degraded_run` 标记 + diff_coverage 扣分 + benchmark 排除规则 | L2 large-diff policy |
| 34 | 按主语言排序文件 | P1→**P0** | **纳入 v0.1** | 借排序思路；PR-Agent 按"仓库主语言"排，AhaDiff 应按"学习价值"排（核心逻辑 > 测试 > 配置 > glue code） | L2 file prioritization |
| 35 | key_issues 附 start/end_line | P0 | **已覆盖** | HC-3 已要求 source_hunks{file,start,end} | L4 claims schema |
| 36 | score + effort 双维度 | P1 | **不适用** | "审查 effort" 是 PR review 维度，非学习质量核心 | — |
| 37 | Jinja2 条件渲染 prompt | P1 | **延后 v0.2+** | v0.1 用多份显式 prompt 文件更可审计 | — |

---

## 纳入 v0.1 的 10 条汇总（按层排序）

| 层 | # | 借鉴点 | 模块 | 开发顺序 |
|---|:--:|---|---|:---:|
| **L1 Diff Capture** | 30 | hunk 格式化输入协议 | `git/parser.py` + prompt formatter | 1st |
| **L2 Context** | 32 | 双缓冲区 token 预算 | `llm/provider.py` + diff packer | 2nd |
| **L2 Context** | 33 | large_patch_policy skip/clip | L2 large-diff policy | 2nd |
| **L2 Context** | 34 | 按主语言排序文件优先级 | L2 file prioritization | 2nd |
| **L2 Context** | 23 | SHA256 内容寻址缓存 | `llm/cache.py` | 3rd |
| **L3/L4 Gen+Verify** | 31 | YAML 内部交换+Pydantic 验证 | `claims/extract.py` | 4th |
| **L5 Ratchet** | 6 | redirect stdout 到 `.ahadiff/runs/<run_id>/run.log` | run artifacts / logging | 5th |
| **L5 Ratchet** | 11 | 异常处理决策表（9 场景） | `core/errors.py` + `eval/ratchet.py` | 5th |
| **L5 Ratchet** | 13 | score.json Schema 强制 | score report schema | 5th |
| **L5 Ratchet** | 19 | Few-shot+Tier 分类+算术验证行 | judge prompts | 5th |

---

## 前端影响评估（Gemini 分析要点）

37 条中 **8 条直接影响前端**，按 UX 价值排序：

| 优先级 | # | 前端影响 | Warm v6 一致性 | 需要模板调整 |
|:---:|:---:|---|:---:|:---:|
| 1st | 35 | Diff+Evidence 页面行号锚点+双向跳转 | 一致（已有 Claim Inspector） | 需加 Vanilla JS 滚动 |
| 2nd | 13 | 全站 PASS/CAUTION/FAIL 三色徽章 | 完全一致 | 需 Jinja2 条件块 |
| 3rd | 36 | score+effort 双维度（Dashboard 分诊） | 不适用（已排除） | — |
| 4th | 7+14 | 8 维评分+Security Gate 阻断 | 一致（原型有 rubric 进度条） | 可选：条形图或雷达图 |
| 5th | 22 | ASCII 统计柱状图 | 不适用（延后） | — |
| 6th | 12 | 3 主题切换 | 与设计手册命名冲突 | 延后 |
| 7th | 2/9 | TSV 表格列定义 | 不适用（已排除） | — |

**关键前端决策**：
- #35 的行号锚定：Jinja2 渲染时注入 `id="L82"` + 轻量 Vanilla JS（<100行）实现 Click→ScrollIntoView
- #12 主题切换：设计手册命名 `Minimal/Warm/Editorial` 优先于原始 `swiss/terminal/newspaper`
- #13 三态色：完美匹配 Warm v6 的 `color.state.{success|warning|danger}` 变量

---

## 风险清单

| 风险 | 涉及条目 | 影响 | 缓解 |
|---|---|---|---|
| #2/#9 与 HC-15 冲突 | results.tsv 列数 | 破坏已冻结 contract | 显式否决原样引入 |
| #5 与 improve loop 语义冲突 | NEVER STOP 循环 | 设计文档漂移 | 统一为"有 budget/rounds/确认点"的循环 |
| #31 YAML/JSON 双协议 | LLM 交换格式 | artifact 层维护成本 | YAML 仅作 LLM 内部格式，落盘仍 JSON/JSONL |
| #32/#33 降级标记缺失 | clip 后的结果 | 用户误认为完整 | metadata.json + viewer 显式标记 `degraded_run` |
| #32/#33 评估公平性 | clip/skip 影响覆盖率 | diff_coverage 被系统性低估，benchmark 不可比 | score.json 和 results.tsv 必须标注 degraded；benchmark 报告排除 degraded runs |
| #23 缓存 key 不够严格 | SHA256 碰撞 | 错误复用或隐私泄漏 | key = content + path + redaction_config hash |
| #12 多主题提前开工 | 前端资产膨胀 | v0.1 scope 膨胀 | 严格延后到 v0.2+ |

---

## v0.1 不纳入清单

### 原则上不适用（与 AhaDiff 设计方向不符）

| # | 原因 |
|:--:|---|
| 2 | HC-15 已冻结 10 列，不回退到 5 列 |
| 5 | 与可控 improve loop 冲突，AhaDiff 不做无限自主循环 |
| 9 | 与 HC-15 冲突，eval_mode 信息可记录在 note 列（第 10 列） |
| 28 | 代码风格偏好，非架构决策 |
| 36 | PR review 维度，不适用于学习质量评估 |

### 本版延后（v0.2+ 有价值，但 v0.1 优先级不够）

| # | 原因 |
|:--:|---|
| 18 | quick-scan 三维快扫有价值，但 v0.1 deterministic verifier 已够闭环；待真实 latency/cost 数据后再评估纳入 |

---

## 源码深度验证（v3 — 三模型交叉验证）

> Codex 73/100 + Claude 逐行验证 + Gemini 95/100

### 验证结论：方向正确，但 5 条需精确化表述

**核心原则修正**：10 条借鉴点应理解为**"借思想 + AhaDiff 重写"**，而非"直接搬代码"。

| # | 原表述 | 源码验证结果 | 修正后表述 |
|:--:|---|---|---|
| 6 | redirect stdout | 实际是 `> run.log 2>&1`（含 stderr），tee 被禁是因 agent context flooding | **保留**：stdout+stderr 写入 `.ahadiff/runs/<run_id>/run.log`；CLI 模式可用 tee 兼顾回显 |
| 11 | 异常决策表（9场景） | 实际 **10 场景**（非 9）；#8/#9 是 darwin-skill 特有；AhaDiff 还需补 provider timeout / secret gate / cache corruption / degraded run 等场景 | **重写**：以 darwin-skill 10 场景为 seed，扩展 AhaDiff 专属错误分类（约 15+ 场景） |
| 13 | eval-result.json Schema | SkillCompass 是 **6 维 skill 评估**，字段含 skill_name/skill_type；AhaDiff 是 8 维 lesson 评估 | **重写**：借鉴五元组作为**默认 envelope**，但非所有维度统一结构：`safety_privacy` 走 `pass/findings/tools_used`（参照 SkillCompass security 维度）；`diff_coverage` 走 deterministic counts；其余 6 维可用 `score+max+details+sub_scores+issues` |
| 19 | Tier+Few-shot+算术验证行 | Tier A/B/C 是 skill 输出类型分类，不适用于 lesson；Example B 有 score 不一致 bug；AhaDiff 8 维权重文档尚未冻结 | **分阶段**：先借 few-shot 校准方法论 + 算术自检概念（代码层 assert），等 8 维权重冻结后再写具体示例和公式 |
| 23 | SHA256 内容寻址缓存 | 原实现是 **per-file extraction cache**（非 LLM 调用缓存）；key 用 repo-relative 路径 + .md frontmatter 剥离 | **重写**：借鉴内容寻址 + 相对路径可移植性思想；AhaDiff cache key = `SHA256(diff_content + \x00 + source_ref + \x00 + prompt_version + \x00 + model_id + \x00 + rubric_version + \x00 + redaction_config_hash + \x00 + context_bundle_hash)`，其中 `source_ref` 为规范化 repo-relative 引用，`context_bundle_hash` 涵盖 graph/spec/context 选取 |

### 前端 Corner Cases（Gemini 补充）

| 场景 | 处理方式 |
|---|---|
| 空 diff（0 hunks） | L1 层拦截，viewer 渲染 Empty State；不生成残缺 Diff 表格 |
| 全部被 skip 的 large diff | 状态为 FAIL/ABORTED，Lesson 页面展示 Error State + 红色警告 |
| #32/#33 降级标记 | 复用 Warm v6 的 `.demo-banner` 组件扩展为 `.alert.degraded` |
| score.json 嵌入 data_bundle | 作为子树嵌入，Jinja2 模板层做变量映射，不直接解析嵌套 |
| #35 行号跳转 a11y | 目标元素需 `tabindex="-1"` + `element.focus()` |

### 8 维权重收敛预警（v4 精确化）

仓内存在**两组权重**，且维度命名不一致：

| 来源 | acc | evi | diff_cov | learn | quiz/recall | spec | conc | safety |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| README.md / README.en.md / 前端设计稿 | 20 | **15** | **15** | **15** | 10 | 10 | 8 | **7** |
| doc/CLAUDE.md / 知返设计坐标 / 最终方案 | 20 | **18** | **14** | **14** | 10 | 10 | 8 | **6** |

维度命名漂移：CLAUDE.md 写 `quiz_transfer`，README.md 写 `Recall Transfer`。
Hard gate 漂移：README 写 `Accuracy <14 FAIL`，competitors-research 写 `<15 FAIL`。

**行动项**：v0.1 开发前必须统一权重为单一真相源，#19 算术验证行在此之后才能落地。

---

## 审查记录

```text
Codex 分析 (SESSION: 019da6fe-5314-7ff1-9729-ae19e7eaa346)
  - 逐条判定 37 条，按七层架构映射
  - 发现 HC-15 冲突（#2, #9）
  - 建议 #34 升档为 P0 配套项
  - 风险：#31 双协议、#23 缓存 key、#32/#33 降级标记

Gemini 分析 (SESSION: a27328a3-e820-4042-913c-cd05af920149)
  - 识别 8 条前端影响点
  - UX 价值排序：#35 > #13 > #36 > #7/#14 > #22
  - 主题命名冲突：坚守设计手册 Minimal/Warm/Editorial
  - 建议 #35 用 Vanilla JS 实现（兼顾 HC-5）

Claude 综合
  - 合并两方分析，消除冲突
  - #36 Codex 判"不适用" vs Gemini 排 3rd → 采纳 Codex（后端权威）
  - 最终纳入 10 条、不适用 5 条、延后 v0.2+ 含 #18 共 14 条

交叉 Review 修复 (v2)
  Codex Review (80/100):
  [W-fix] #12 延后理由从"HC-5 冲突"改为"v0.1 scope / 资产维护成本"
  [W-fix] #6 补 HC-1 落盘路径约束：.ahadiff/runs/<run_id>/run.log
  [W-fix] #18 从"显式否决"移到"本版延后"分类
  [W-fix] 风险表补 #32/#33 对 diff_coverage/benchmark 可比性的影响
  [I-fix] #7+#14 前端表述从"需升级为雷达图"改为"可选：条形图或雷达图"

  Gemini Review r1 (99/100):
  [W-note] #35 实现时需关注 a11y：target 元素加 tabindex="-1" 支持 programmatic focus
  [I-note] 延后的 #22 页面需设计 empty state 避免不完整感

最终验证 (v4) — 2026-04-20
  Codex (62/100):
  [C-fix] #30-#34 从"可直接借"改为"借机制 + AhaDiff 特化"
    #30: PR-Agent 只给 new hunk 行号，AhaDiff 需 old/new 双侧
    #31: Pydantic 模型必须自研（review object ≠ claim/lesson）
    #32: 1500/1000 是 PR-Agent 特定常量，AhaDiff 需重新标定
    #33: 必须同步 degraded_run + diff_coverage 扣分 + benchmark 排除
    #34: 按"学习价值"排序而非"仓库主语言"排序
  [C-fix] #23 cache key 补 rubric_version + context_bundle_hash
  [W-fix] #6 tee 限定场景：agent-loop 禁 tee，human-CLI 可选 tee
  [W-fix] #13 safety_privacy 走 pass/findings 结构，不强制 sub_scores
  [W-fix] #19 权重冲突精确化：两组文档 + 命名漂移 + hard gate 漂移

  Claude 最终验证 (NEEDS_IMPROVEMENT → 已修):
  [fix] #23 补 rubric_version（rubric 变更使缓存失效）
  [fix] #13 safety_privacy 结构差异化（参照 SkillCompass security）
  [fix] "权重不一致"精确化为命名漂移 + 两组数值

  Gemini r2 (87/100):
  [W-note] 超大 DOM 需限制渲染行数，超长字符串需 word-break
  [W-note] degraded 状态需 role="alert" + aria-live
  [W-note] 8 维图表必须数据驱动，禁止硬编码维度名/满分值
  [I-note] v0.1 明确废弃 React/Next.js，统一 Jinja2 + Vanilla JS

源码深度验证 (v3) — 2026-04-20
  Codex (73/100): 5 条全部在 repo/ 中定位到真实源码；
    [P0] #13 不能直接搬 Schema（6维 skill 评估 ≠ 8维 lesson 评估）
    [P0] #19 Tier A/B/C 语义不适配；8 维权重文档未收敛
    [P0] #23 是 per-file cache 非 LLM cache；key 需要多因子重写
    [P1] #11 实际 10 场景非 9；需补 AhaDiff 特有错误面
    [P1] #6 "不用 tee" 是 agent 场景约束，CLI 可用 tee

  Claude 逐行验证：5 条全部逐行 Read 确认；
    Example B 有 score 不一致 bug（3.35→3 但 JSON 写 4）
    graphify cache.py 有 3 个遗漏细节（相对路径/frontmatter 剥离/fallback）
    验证报告：.claude/team-plan/borrow-points-verification-report.md

  Gemini (95/100): 前端 corner cases 补充；
    空 diff / 全 skip / degraded 标记 / a11y focus 管理
    CSS Variables 写法必须保持，不能为赶进度写死 HEX```
```
