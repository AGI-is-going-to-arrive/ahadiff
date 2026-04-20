# Codex Review Report

**审查对象**：
1. `.claude/team-plan/ahadiff-competitors-research.md` Part G（37 条借鉴点）
2. `AhaDiff-Competitors-Research.html` `<section id="borrow">` + `borrowData` / `top10List` / 渲染函数

**审查时间**：2026-04-20

---

## 1. 引用准确性

| # | 抽查借鉴 | file:line | 真实对比 | 判定 |
|---|---------|-----------|----------|------|
| #1 | `^key:value` stdout 协议 | `train.py:L622-L630` | 实际 L622: `print(f"val_bpb: {val_bpb:.6f}")` 开始的 KV 输出块，完全匹配 | ✅ |
| #3 | gc.disable() + gc.collect() | `train.py:L592-L598` | 实际 L592-598: `gc.collect(); gc.freeze(); gc.disable()` + 5000 步手动 collect，完全匹配 | ✅ |
| #7 | 8 维加权 Rubric | `SKILL.md:L29-L51` | 实际 L29-51: 结构 60 分 + 效果 40 分表格 + "严格高于"规则，完全匹配 | ✅ |
| #11 | 异常处理决策表 | `SKILL.md:L270-L286` | 实际 L270-286: 10 行异常场景表（不在 git / TSV 损坏等），完全匹配 | ✅ |
| #20 | `<<<UNTRUSTED_SKILL_BEGIN>>>` | `prompts/d4-functional.md:L30-L32` | 实际 L30-32: `<<<UNTRUSTED_SKILL_BEGIN>>>` + `{SKILL_CONTENT}` + END，完全匹配 | ✅ |
| #23 | SHA256 缓存 + frontmatter 剥离 | `graphify/cache.py:L10-L41` | 实际 L10-41: `_body_content()` 剥 frontmatter + `file_hash()` 含 `\x00` 分隔符，完全匹配 | ✅ |
| #15 | 减分制 + fatal cap | `lib/structure-validator.js:L524-L534, L49-L63` | 实际 L524-534: `calculateSubScore` 减分制；L49-63: `fatalFrontmatter/fatalYaml/fatalBody` cap 逻辑，完全匹配 | ✅ |
| #14 | D3 Security Gate | `shared/scoring.md:L36-L42` | 实际 Security Gate 从 L40 开始，L36-37 是 rationale 说明。核心扣分表在 L48-53 | ⚠️ |

**准确率：7/8 准确 + 1/8 轻微偏差（可接受）**

- ⚠️ #14 的 `L36-L42` 偏差约 4 行（Security Gate 标题在 L40，扣分表在 L48-53）。内容正确但行号起止略偏。不影响理解。

---

## 2. 数据完整性

- **条目数**：37 / 期望 37 ✅
- **优先级分布**：P0=19 P1=15 P2=3 ✅（与 HTML stats 声明完全一致）
- **编号连续**：1-37 不重不漏 ✅
- **字段完整**：全部 37 条均含 `n / proj / pri / title / loc / how / apply` ✅
- **重复编号**：无 ✅

---

## 3. HTML/JS 语法问题

- [S-1] `${CLAUDE_PLUGIN_ROOT}` 在模板字符串中已用 `\${CLAUDE_PLUGIN_ROOT}` 正确转义 ✅（L1964）
- [S-2] `<`, `>`, `&` 在 `how` / `title` / `apply` 字段中已正确转义为 `&gt;` `&lt;` `&amp;`（共 13 处确认）✅
- [S-3] `\x00` 在反引号中已正确双转义为 `\\x00`（L1996）✅
- [S-4] Filter 点击事件通过 `el.addEventListener('click', ...)` 委托绑定（L2121-2131），用 `e.target.closest('.filter-btn')` 正确匹配 ✅

**无语法问题。**

---

## 4. 逻辑问题

- [L-1] **两个筛选器组合**：`renderBorrow()` 同时读取 `#borrowProjFilter .active` 和 `#borrowPriFilter .active` 的 dataset 值做 AND 组合筛选 ✅（L2097-2101）
- [L-2] **"全部" 重置**：proj 筛选器的 "全部" 按钮 `data-bp="all"`，pri 筛选器的 "任意" 按钮 `data-bpr="all"`。各自独立切换 active 状态，互不影响 ✅
- [L-3] **DOM 就绪调用**：`renderTop10()` 和 `renderBorrow()` 在 `</body>` 前的 `<script>` 末尾调用（L2133-2134），此时 DOM 已就绪 ✅
- [L-4] **响应式断点**：`top10-grid` 用 1100/720/480，`borrow-grid` 用 1000/680，`borrow-stats` 用 700。层级合理，无重叠冲突 ✅

**无逻辑问题。**

---

## 5. 一致性问题

- [C-1] **分项目条数 vs 柱状图**：

  | 项目 | research.md | HTML chart | borrowData |
  |------|:-----------:|:----------:|:----------:|
  | autoresearch | 6 | 6 (3P0+2P1+1P2) | 6 ✅ |
  | darwin-skill | 6 | 6 (3P0+2P1+1P2) | 6 ✅ |
  | SkillCompass | 10 | 10 (6P0+4P1) | 10 ✅ |
  | graphify | 7 | 7 (2P0+4P1+1P2) | 7 ✅ |
  | Qodo PR-Agent | 8 | 8 (5P0+3P1) | 8 ✅ |

  全部一致。

- [C-2] **Top 10 清单一致性**：research.md G.6 表 10 行 vs HTML `top10List` 10 条：
  - 排名 1-10 完全一致 ✅
  - 编号引用（#30, #20, #31+#24, #13, #14+#15, #19, #32+#33, #1+#2, #23, #11）完全一致 ✅
  - 描述文字存在合理缩写（research.md 更详细，HTML 更精简），不影响准确性 ✅

- [C-3] **G.7 维度统计 — Warning**：
  - #31 同时出现在"数据结构/Schema"和"Prompt 工程"两类 — 合理（YAML 确实跨两维度）
  - #22 同时出现在"评估器实现"和"测试/Mock"两类 — 合理（analyze-results.js 确实跨两维度）
  - **但 #1（`^key:value` stdout）和 #5（NEVER STOP 自主循环）未出现在任何维度分类中**。总行数 37 是因为 #31 和 #22 各被重复计数一次（37 = 35 unique + 2 dupes），而 #1 和 #5 被遗漏。

---

## 6. 关键发现（Critical 级必须修复）

无 Critical 级问题。

---

## 7. 建议（非阻塞优化）

1. **[Info] G.7 维度统计缺 #1 和 #5**：`#1`（`^key:value` stdout）应归入"UX / 输出"或"数据结构/Schema"；`#5`（NEVER STOP 自主循环）应归入"CLI / 配置"或"错误处理 / 成本"。当前不影响 HTML 功能，仅 research.md 维度分类不完整。

   建议修复（research.md L285-292）：
   - UX / 输出：`3` → `4`，补 `#1 stdout 协议`
   - CLI / 配置：`2` → `3`，补 `#5 NEVER STOP`
   - 或者重新分配，移除 #31/#22 的跨维度重复

2. **[Info] #14 行号微调**：`scoring.md:L36-L42` 可改为 `scoring.md:L40-L55` 更精确覆盖 Security Gate + 扣分表段落。非阻塞。

---

**总结**：Part G 的 37 条借鉴点和 HTML 实现质量很高。引用准确率 7/8 + 1 条轻微偏差，数据完整性 100%，JS 语法无误，筛选逻辑正确，Top 10 一致。唯一值得修补的是 G.7 维度分类遗漏了 #1 和 #5 两个条目。
