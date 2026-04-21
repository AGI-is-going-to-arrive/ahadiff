[根目录](../CLAUDE.md) > **ui**

# ui -- UI 原型模块

## 模块职责

存放知返 AhaDiff 的 HTML/CSS/JS 前端原型，以 Warm 风格为默认方向，经过 v1 到 v6 共 6 个迭代版本。所有原型为自包含 HTML 文件（内联 CSS + JS），可直接在浏览器中打开预览。

## 入口与启动

```bash
# 打开最新版本
open "ui/AhaDiff Warm v6.html"

# 或使用本地 HTTP 服务器（解决跨域字体加载等问题）
cd ui && python3 -m http.server 8765
```

## 对外接口

无 API 接口。原型为静态 HTML，仅供视觉和交互验证。

## 关键依赖与配置

### 外部依赖（通过 CDN 加载）

| 依赖 | 用途 |
|------|------|
| Google Fonts | Newsreader / Inter / JetBrains Mono / Noto Serif SC |

### 设计变量（CSS Custom Properties）

Warm 风格核心色值：

| 变量 | v1-v4 值 | v5 值 | 说明 |
|------|----------|-------|------|
| `--paper` | `#FAF9F5` | `#FAF8F2` | 页面底色（暖白纸感） |
| `--accent` | `#D97757` | `#D27050` | 主强调色（Clay Orange） |
| `--ink` | `#1F1E1B` | `#1C1B18` | 主文字色 |
| `--add-bg` | `#E4EFE0` | `#E4EFE0` | diff 新增行背景 |
| `--del-bg` | `#F6DCD5` | `#F6DCD5` | diff 删除行背景 |
| `--success` | `#2F6F4F` | `#2F6F4F` | 成功/验证通过 |
| `--warning` | `#B4791F` | `#B4791F` | 警告/CAUTION |

## 数据模型

无运行时数据。原型中使用硬编码的 mock 数据展示 UI 效果。

## 版本演进

| 文件 | 版本 | 说明 |
|------|------|------|
| `ahadiff-warm.html` | v1 | 初始 Warm 风格原型 |
| `ahadiff-warm-v2.html` | v2 | 第二次迭代 |
| `ahadiff-warm-v3 (1).html` | v3 | 第三次迭代（文件名含空格） |
| `AhaDiff Warm v4.html` | v4 | 品牌名大写统一 |
| `AhaDiff Warm v5.html` | v5 | 色值微调（accent 从 `#D97757` 调整为 `#D27050`） |
| `AhaDiff Warm v6.html` | v6 | 最新版本，v5 基础上增强（motion/a11y/布局优化） |

**注意**：根目录的 `AhaDiff Warm v6.html` 是 `ui/AhaDiff Warm v6.html` 的副本，用于快速预览。

## 设计规范对应

原型实现了前端设计手册（`doc/AhaDiff_frontend_design_v1.1_revised.md`）中定义的 Warm 风格：

- 暖白纸感底色
- Clay Orange 单 accent
- Newsreader serif 正文 + Inter sans UI 文字
- JetBrains Mono 代码字体
- Noto Serif SC 中文 serif

计划中的 3 风格 x 11 页面中，目前仅实现了 Warm 风格的部分页面。

## 已知问题

- **768px 平板视口断裂**：侧栏在 769-1024px 区间缺少 icon-only 迷你模式，遮罩缺失
- **外部 Google Fonts 依赖**：工程化时需移除，改为本地字体或 system-ui fallback
- **硬编码 mock 数据**：工程化时需替换为 React 组件 props + API data fetch
- **Rubric 进度条**：8 维应使用独立语义色（当前只有单色）
- **打印样式**：缺少 page-break-inside: avoid 和证据链保留

## 工程化迁移计划

Gemini(gemini-3.1-pro-preview) 负责设计评审和改进方案（不写代码），Claude 负责代码实现：
1. 以 v6.html 为参考，拆解为 React 19 + Vite + TypeScript 组件：`viewer/src/{components/,pages/,styles/,api/,i18n/}`
2. 添加 769-1024px icon-only 侧栏 + ≤768px 抽屉模式
3. 移除外部字体引用，内联 SVG favicon
4. 替换 mock 数据为 `ahadiff serve` REST API 数据获取
5. 补全 ARIA 属性和 `--muted-2` 对比度（#7A7463）
6. 实现 vanilla CSS 设计系统（CSS Custom Properties，不用 CSS 框架）

## 测试与质量

- 通过 Playwright MCP 进行浏览器自动化预览（截图见 `eval-screenshots/`）
- 手动检查响应式布局、暗色模式、字体加载
- 验收视口：375px / 768px / 1024px / 1440px 四个断点无断裂

## 常见问题 (FAQ)

**Q: 为什么原型是自包含 HTML 而非 React 组件？**
A: 当前处于设计探索阶段，自包含 HTML 可零依赖快速预览和迭代，便于非工程人员查看。工程化首版将迁移到 **React 19 + Vite + vanilla CSS**（`viewer/` 目录），通过 `ahadiff serve` 启动本地 Starlette 服务提供 REST API 数据。

**Q: v5 与 v4 的主要区别？**
A: 色值微调，`--accent` 从 `#D97757` 变为 `#D27050`，`--paper` 从 `#FAF9F5` 变为 `#FAF8F2`，整体色温略有偏移。

**Q: 文件名不规范（含空格、括号）如何处理？**
A: 这是设计迭代过程中的历史遗留。建议在进入工程阶段时统一重命名为 `ahadiff-warm-v1.html` 到 `ahadiff-warm-v5.html` 格式。

## 相关文件清单

| 文件 | 说明 |
|------|------|
| `ahadiff-warm.html` | Warm v1 原型 |
| `ahadiff-warm-v2.html` | Warm v2 原型 |
| `ahadiff-warm-v3 (1).html` | Warm v3 原型 |
| `AhaDiff Warm v4.html` | Warm v4 原型 |
| `AhaDiff Warm v5.html` | Warm v5 原型 |
| `AhaDiff Warm v6.html` | Warm v6 原型（最新） |

## 变更记录 (Changelog)

| 时间 | 变更 |
|------|------|
| 2026-04-19 21:26:58 | 初始创建 ui/CLAUDE.md |
| 2026-04-20 | 同步修订：补充已知问题和工程化迁移计划、更新多模型协作分工 |
| 2026-04-21 | 同步第五轮决策：迁移目标从 Jinja2 改为 React 19 + Vite + vanilla CSS，数据从模板嵌入改为 REST API |
