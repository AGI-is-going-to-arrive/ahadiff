# AhaDiff FSRS 决策文档

> 生成时间：2026-04-21
> 决策：**采用 FSRS-6 替代 SM-2 作为 v0.1 SRS 调度算法**
> 来源：Claude + Codex + Gemini 三模型共识 + Web 研究（2024-2025 文献）+ Codex CLI 深度调研（2026-04-21，212 events，6 官方源取证）

---

## 一、决策摘要

| 项目 | SM-2（原方案） | FSRS-6（新方案） |
|------|--------------|-----------------|
| 算法基础 | 1987 年固定 EF 衰减公式 | 2023-2024 DSR 三分量记忆模型 |
| 参数数量 | 2 (EF, interval) | 21 (可优化，opaque array，不写死数量) |
| 遗忘曲线建模 | 指数衰减（不精确） | 幂律衰减（empirically validated） |
| 自适应能力 | 无 | Optimizer 自动训练个人参数 |
| 复习效率 | 基线 | 减少 20-30% 复习量（RemNote 经验值，中置信） |
| 长期保留 | 基线 | FSRS-6 预测优于 SM-17（benchmark 旁证，中高置信） |
| Python 库 | 需自行实现 | `pip install fsrs` (py-fsrs v6.3.1) |
| Anki 内置 | 默认（逐步被替代） | 23.10 引入原生支持（需手动启用） |

## 二、科学依据

### 2.1 学术研究

| 来源 | 年份 | 结论 | 置信度 |
|------|------|------|--------|
| Ye et al. "A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling" | 2024 | FSRS 基于随机最短路径优化，比 SM-2 更精确预测遗忘 | High |
| Jacinto et al. IEEE "SRS for Markup and Scripting Languages" | 2024 | SRS 在编程语言教学中有效 | High |
| 2024 STEM meta-analysis (IJ STEM Ed) | 2024 | 间隔检索在 STEM 课程中有小但正面效果 | High |
| 2025 Irec framework | 2025 | FSRS 作为元认知撤架有效，但需配合情境触发回忆 | Medium |
| FSRS Benchmark (GitHub open-spaced-repetition) | 2024-2025 | FSRS-6 在 10,000+ 用户数据集上优于 SM-2/SM-17/Leitner | High |

### 2.2 工业界实践

| 产品 | SRS 算法 | 备注 |
|------|---------|------|
| **Anki** | FSRS（23.10 引入，需手动启用） | 从 SM-2 逐步迁移到 FSRS |
| Mochi | SR（算法未公开） | 官方文档未明确写出 FSRS（低-中置信） |
| **RemNote** | **FSRS v6（已内置）** | 建议默认 weights + ≥1000 reviews 后 auto-train |
| Obsidian Decks 插件 | FSRS 6 | 社区插件 `dscherdi/decks` 明确使用 FSRS 6 |
| Exercism | 无 SRS（练习制） | — |
| CodeCombat | 无 SRS（关卡制） | — |

## 三、FSRS 对 AhaDiff 的适配评估

### 3.1 代码学习的特殊性

| 特征 | 影响 | FSRS 应对 |
|------|------|----------|
| 概念间有强依赖（函数调用链） | 遗忘一个导致关联概念也失效 | FSRS 的 Difficulty 参数捕获复杂度 |
| 代码片段比单词卡更长 | 检索难度更高 | 适当降低 desired_retention（0.85-0.88） |
| diff 生成卡片质量参差 | LLM 可能生成歧义题目 | mark-wrong signal 反馈到 FSRS Rating |
| 三段式撤架叠加 SRS | 撤架层级影响卡片难度 | 映射撤架级别到 FSRS 初始参数 |

### 3.2 推荐配置

```python
from fsrs import Scheduler, Card, Rating
from datetime import timedelta, timezone

# AhaDiff 默认配置
AHADIFF_FSRS_CONFIG = {
    "desired_retention": 0.9,          # Anki 官方默认值，高置信
    "learning_steps": (
        timedelta(minutes=1),           # 首次学习 1 分钟后复习
        timedelta(minutes=10),          # 第二次 10 分钟后
    ),
    "relearning_steps": (
        timedelta(minutes=10),          # 遗忘后 10 分钟重学
    ),
    "maximum_interval": 365,            # 代码学习最长间隔 1 年（非 100 年）
    "enable_fuzzing": True,             # 避免同一天大量卡片到期
}

# ⚠️ 关键约束（Codex 调研发现）
# 1. py-fsrs 强制 UTC — 所有时间戳统一 UTC，last_reviewed_at_utc
# 2. weights 数量不写死 — 当前 21 个，但不同版本可能不同
#    schema 中只保存 opaque JSON array + scheduler_version
# 3. 不把 weights 数量写进 contract-freeze.md
```

### 3.2.1 三段式撤架映射（Codex 改进版）

> **核心原则**：scaffolding_level 是 UI 展示层，不进入 FSRS optimizer。
> FSRS 只吃 rating + review log。撤架由 FSRS memory state **驱动**，非反向映射。

```python
# 撤架由 FSRS stability + recent rating 驱动（非 initial_stability_modifier）
def compute_scaffolding_level(card: Card) -> Literal["full", "hint", "compact"]:
    """
    full:    Learning/Relearning 阶段，或最近出现 Again，或 stability < 3d
    hint:    已进入 Review 且 3d <= stability < 14d
    compact: stability >= 14d 且最近 2 次为成功回忆（Good/Hard 或 Good/Good）
    """
    if card.state in (State.Learning, State.Relearning):
        return "full"
    if card.stability < 3.0:
        return "full"
    if card.stability < 14.0:
        return "hint"
    # stability >= 14d，检查最近 2 次是否都成功
    if last_two_ratings_successful(card):
        return "compact"
    return "hint"
```

### 3.3 Quiz Rating 映射

> **Codex 建议**：v0.1 只暴露 Good/Hard/Wrong 三按钮，不强行暴露 Easy。
> Easy 可在 v0.2 作为高级选项开放。

| 用户操作 | FSRS Rating | 说明 |
|---------|-------------|------|
| quiz 答对 | Rating.Good (3) | 正常回忆（v0.1 默认） |
| quiz 答对但犹豫 | Rating.Hard (2) | 困难回忆 |
| quiz 答错 | Rating.Again (1) | 需重学，回到 full 撤架 |
| quiz 答错（安全/误解题） | Rating.Again (1) | **额外生成 misconception 卡** |
| mark-wrong | Rating.Again (1) | 用户标记卡片有误 |
| SRS 翻牌 Good | Rating.Good (3) | — |
| SRS 翻牌 Hard | Rating.Hard (2) | — |
| SRS 翻牌 Wrong | Rating.Again (1) | — |

**Misconception 卡生成规则**（Codex 新增建议）：
- 触发条件：quiz 答错 + 题目涉及安全/误解风险（如把不安全 claim 当真）
- 行为：额外生成一张 `misconception` 类型卡片，强化正确理解
- 比单纯 "答错就 reset interval" 更贴合 code-review 学习目标

### 3.4 Optimizer 自适应策略（Codex 改进版）

> **关键修正**：冷启动阈值从"100 张卡片"改为"500-1000 次有效 review"，
> 与 Anki/RemNote/FSRS tutorial 官方建议对齐。

```
冷启动（<500 次 review）：使用 FSRS-6 默认 weights + desired_retention=0.90
                         不做 optimizer，不做 migrate-and-reschedule
积累期（500-999 次 review）：可选手动 optimize，微调 desired_retention
成熟期（≥1000 次 review）：Optimizer 计算完整个人参数 + optimal_retention
```

**重训触发双门槛**（来源：Anki Manual + FSRS tutorial）：
- 门槛 A：距上次训练 ≥ 30 天
- 门槛 B：当前 preset 新增有效 review 数 ≥ max(512, 上次训练样本数 × 50%)
- 满足 A **或** B 时，异步跑 optimizer
- 手动触发：`ahadiff review --optimize`
- 数据截断：参考 Anki `Ignore cards reviewed before`，支持按时间窗截断训练集

**weights 存储约束**：
- schema 只保存 `weights: JSON array`（opaque）+ `scheduler_version: str`
- 不在 contract-freeze.md 或 schema 中写死 weights 数量
- 当前 py-fsrs 6.3.1 为 21 个，但 RemNote 文档仍写 17 个（版本漂移）

## 四、实施影响

### 4.1 需修改的 Task

| Task | 修改内容 |
|------|---------|
| Task 10 | QuizQuestion → FSRS Rating 映射 |
| Task 15 | SM-2 → FSRS scheduler 实现（`pip install fsrs`） |
| Task 0 | pyproject.toml 添加 `fsrs` 依赖 |
| CLAUDE.md | "SM-2" → "FSRS-6" |

### 4.2 数据模型变更

```python
# ReviewCard schema 变更（Codex 改进版）
class ReviewCard(BaseModel):
    # ... existing fields ...
    # SM-2 字段（删除）
    # ease_factor: float = 2.5
    # interval: int = 0
    # reps: int = 0

    # FSRS 字段（新增）
    fsrs_card_json: str            # Card 对象 JSON 序列化（opaque）
    scheduler_preset_id: str       # 调度器 preset（支持多 preset）
    desired_retention: float = 0.9 # 该卡的 retention 目标
    scaffolding_level: Literal["full", "hint", "compact"] = "full"
    last_rating: int | None = None # 1-4
    last_reviewed_at_utc: str | None = None  # ISO 8601 UTC（py-fsrs 强制 UTC）
```

### 4.3 review.sqlite schema 变更

```sql
CREATE TABLE cards (
    id TEXT PRIMARY KEY,
    concept TEXT NOT NULL,
    run_id TEXT NOT NULL,
    -- FSRS 字段（Codex 改进版）
    fsrs_state TEXT NOT NULL,       -- Card JSON（opaque，不解构 weights）
    scheduler_preset_id TEXT NOT NULL DEFAULT 'default',
    scheduler_version TEXT NOT NULL, -- e.g. "fsrs-6.3.1"
    desired_retention REAL NOT NULL DEFAULT 0.9,
    due_date TEXT NOT NULL,          -- ISO 8601 UTC
    stability REAL NOT NULL,
    difficulty REAL NOT NULL,
    reps INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    scaffolding_level TEXT NOT NULL DEFAULT 'full',
    last_rating INTEGER,             -- 1-4
    last_review_utc TEXT,            -- ISO 8601 UTC（py-fsrs 强制）
    -- 元数据
    source_ref TEXT,
    file_id TEXT,
    display_path TEXT,
    created_at_utc TEXT NOT NULL     -- ISO 8601 UTC
);

-- Optimizer 参数存储（不写死 weights 数量）
CREATE TABLE scheduler_presets (
    preset_id TEXT PRIMARY KEY,
    weights TEXT NOT NULL,            -- JSON array（opaque，当前 21 个）
    desired_retention REAL NOT NULL DEFAULT 0.9,
    scheduler_version TEXT NOT NULL,
    total_reviews INTEGER NOT NULL DEFAULT 0,
    last_optimized_utc TEXT,
    created_at_utc TEXT NOT NULL
);

-- Review log（供 Optimizer 训练用）
CREATE TABLE review_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES cards(id),
    rating INTEGER NOT NULL,          -- 1-4
    reviewed_at_utc TEXT NOT NULL,     -- ISO 8601 UTC
    elapsed_days REAL NOT NULL,
    scheduled_days REAL NOT NULL,
    state TEXT NOT NULL                -- Learning/Review/Relearning
);
```

## 五、Codex 调研独有发现

> 以下为 Codex CLI 深度调研（212 events，6 官方源直接取证）的独有贡献

### 5.1 学术引用修正
- FSRS 学术主引文应回到 **2022 KDD（MaiMemo DHP/SSP 路线）**，而非 GitHub wiki
- FSRS 源自 MaiMemo 的 DHP model（DSR 变体）
- "20-30% fewer reviews" 是 **RemNote 单点经验值（中置信）**，非 RCT 结论

### 5.2 代码学习适用性判定
- **"代码学习可用 SRS"**：中高置信（IEEE FIE 2024 直接证据）
- **"代码卡可直接照搬语言学习参数"**：中低置信（无直接论文）
- **建议**：用 FSRS 作底座，但通过 A/B 数据验证代码卡的最佳 retention 和 scaffolding 阈值

### 5.3 关键工程约束
1. **py-fsrs 强制 UTC**：所有时间戳统一 `_utc` 后缀
2. **weights opaque**：不写死数量到 schema/contract，当前 21 个可能变
3. **SRS 最小单元**：应是单条 claim/misconception/guardrail，**不是**整篇 lesson
4. **Anki FSRS 代际**：23.10 = 早期原生支持，25.07 = FSRS-6
5. **SM-2 fallback**：保留 feature-flag（`--scheduler sm2`），不做默认路径

### 5.4 Misconception 卡机制
- 安全/误解题答错 → 额外生成 misconception 卡 → 强化正确理解
- 比 "答错 reset interval" 更贴合 AhaDiff code-review 学习目标

## 六、结论

**FSRS-6 对 AhaDiff 项目明确有帮助**（Claude + Codex + Gemini 三模型共识）：

1. **减少复习负担**：代码学习者每天复习量减少 20-30%（RemNote 经验值，中置信）
2. **更精确调度**：DSR 三分量模型比 SM-2 启发式公式更贴合真实记忆（高置信）
3. **自适应**：Optimizer 可根据用户实际表现调整参数，双门槛触发（高置信）
4. **零维护成本**：`pip install fsrs` 即用，无需自行实现调度算法（高置信）
5. **行业趋势**：Anki 23.10 引入原生 FSRS（需手动启用）、RemNote 已内置 FSRS v6（高置信）
6. **撤架由 stability 驱动**：scaffolding_level 从静态映射升级为 FSRS memory state 驱动（Codex 改进）
7. **Misconception 卡**：安全题答错额外生成纠错卡，提升 code-review 学习效果（Codex 新增）

**desired_retention 推荐值**：
- 代码学习起步：**0.9**（Anki 官方默认，高置信）
- 用户可在 Settings 页面调整：0.85-0.95（>0.97 容易失控）
- Optimizer 成熟后（≥1000 reviews）：自动计算最优值

**置信度声明**：
- "FSRS 更省 review"：高置信（定性），中置信（定量 20-30%）
- "代码学习适用 SRS"：中高置信（IEEE FIE 2024 直接证据）
- "代码卡参数可照搬"：中低置信（需 A/B 验证）
