# DeepSeek BYOK Provider 前端支持评估报告

本报告对 ahadiff viewer 前端（React 19 SPA，目录位于 `viewer/src/`）的 Provider 配置界面对 DeepSeek 作为 BYOK (Bring Your Own Key) provider 的支持现状进行了深度评估，并提出了相应的改动方案。

> 2026-06-16 更新：本文是修复前评估记录。当前工作树已在前端和后端接入 `openai_compat` provider class，并保留 DeepSeek BYOK 配置提示；官方 DeepSeek v4 flash/pro 的 thinking cascade 已接入，前端会在后端 `modelLimits.thinking.supported=true` 后渲染对应 Thinking Level 控件和 hint。

---

## 1. 相关配置组件与文件定位

前端涉及提供商配置、模型限额预览及状态管理的核心组件与逻辑主要定位如下：

- **配置与编辑卡片组件**：
  - [ProviderCard.tsx](viewer/src/components/ProviderCard.tsx)：负责提供商配置的核心组件。包含 `ProviderCard`（主卡片）、`ProviderEditForm`（编辑表单，包括别名、类型、Base URL、API Key、最大输出限制等）以及 `ProviderDetailView`（只读详情，展示探测出的 Context 长度及 limits source 标记）。
  - [ProviderCard.css](viewer/src/components/ProviderCard.css)：提供商卡片的 CSS 布局和暗色/高对比度 fallback 样式。

- **页面管理器**：
  - [SettingsPage.tsx](viewer/src/pages/SettingsPage.tsx)：设置页主入口，组织 `ProviderCard` 的列表网格，负责处理新建、保存、删除、连接探测（Probe）以及模型的角色选择（Generate / Judge）级联逻辑。

- **API 交互与契约数据结构**：
  - [providers.ts](viewer/src/api/providers.ts)：封装了提供商相关的异步 API。例如通过 `discoverModels` 获取远端模型列表，通过 `previewModelLimits` 预览特定模型和类型的上下文限制。
  - [types.ts](viewer/src/api/types.ts) 和 [schemas.ts](viewer/src/api/schemas.ts)：声明了 `ModelLimitsResponse` 的 Zod schema 及 TypeScript 接口。

- **国际化配置**：
  - [en.json](viewer/src/i18n/messages/en.json)：英文语言包。
  - [zh-CN.json](viewer/src/i18n/messages/zh-CN.json)：中文语言包。

---

## 2. DeepSeek BYOK 配置体验与兼容性评估

当用户尝试在 Settings 页面配置 DeepSeek 作为自定义提供商时，以下维度的体验和实现存在显著的问题或限制：

### 2.1 Model 名输入方式 (Model Name Input)
- **输入交互**：在编辑表单 `ProviderEditForm` 中，`model_name` 默认为普通文本输入框。如果用户已经填写了 `base_url` 与 `api_key`，点击刷新（`↻`）按钮可调用后端的 `discoverModels` 接口。若连接成功，前端会将文本框转换为 `<select>` 下拉菜单，列出探测到的模型。
- **痛点与局限**：目前缺乏对 DeepSeek 的内置预设，文本框的 placeholder 仍硬编码显示 `gpt-5.5`（由 `PROVIDER_EXAMPLES.openai` 决定），对于初次配置 DeepSeek 的用户不够直观，需要手动打字输入 `deepseek-v4-flash` 或 `deepseek-v4-pro`。

### 2.2 Provider Class 选择项 (Provider Class Selection)
- **修复前核心缺陷**：前端 [ProviderCard.tsx](viewer/src/components/ProviderCard.tsx#L60-L69) 中定义的 `PROVIDER_CLASSES` 仅包含：
  `'openai', 'openai_responses', 'gemini', 'anthropic', 'azure', 'newapi', 'ollama', 'lmstudio'`。
  修复前缺失了 `openai_compat`（OpenAI 兼容）这一类型；当前工作树已补上。
- **兼容性后果**：
  - 若用户选择 `openai`：后端对应的 `OpenAIChatAdapter` 默认开启了 `supports_native_json_schema=True`。但 DeepSeek API 仅支持 `response_format=json_object`，**不支持** `json_schema`。当系统发起需要结构化输出的任务（Claims 提取或 Lesson 生成）时，后端会传递 `json_schema` 格式，**导致 DeepSeek API 报错而直接运行失败**。
  - 若用户误选为 `newapi` 或 `lmstudio`：由于后端在 registry 中将这两个类型重映射为了 `openai_compat`，因此会走不带 `json_schema` 的兼容模式，可以跑通。但这在 UI 配置上极具误导性，用户很难联想到配置 DeepSeek 时需要去选择 "lmstudio" 或 "newapi"。

### 2.3 误导性提示与预设 (Misleading Hints & Examples)
- **缺省示例**：`PROVIDER_EXAMPLES` 缺少 DeepSeek 的预设。当用户新建或切换提供商类型时，无法一键生成 DeepSeek 的 `base_url` 样例（`https://api.deepseek.com`），用户必须自行手动寻找并打字输入，容易出现拼写或路径斜杠错误。
- **密钥保存路径提示**：前端会根据 Scope 提示用户 API Key 写入本仓库的 `.env` 或全局目录。该部分的提示依然正常，但由于没有针对 DeepSeek 的优化，容易让用户在填写 API Key 时感到不确定。

### 2.4 Capability / Limits / Thinking 的显示现状
- **Limits (上下文与限制数) 匹配失效**：
  在后端的 [model_registry.json](src/ahadiff/llm/model_registry.json#L496-L514) 中，`deepseek-v4-flash` 和 `deepseek-v4-pro` 的 provider 声明均为 `"openai_compat"`。
  - 若用户在前端选择了 `openai` 作为 class，那么在获取预览限额（`/model-limits/preview`）时，后端无法在以 `openai` 为 key 的注册表中匹配到内置规格，导致**无法正确显示 1M context / 384K output 限制**，且前端的“推荐限制”快捷按钮失效。
- **Thinking (推理思考等级) 选项被隐藏**：
  - 前端定义的 `SUPPORTS_THINKING` 数组不包含 `openai` 或 `openai_compat`，且后端 [thinking.py](src/ahadiff/llm/adapters/thinking.py#L27-L51) 的 `thinking_policy_for` 也不支持 `openai` 与 `openai_compat` 类型。
  - 这意味着，即便 DeepSeek-V4-Pro 本身属于推理思考模型，前端也会因为类型限制而**完全隐藏思考等级（Thinking Level）下拉菜单**，用户在界面上根本无法启用或调整其 Reasoning 能力。
- **推理思考内容丢弃**：
  - 后端 `OpenAIChatAdapter`（`openai` 及 `openai_compat` 均继承自它）的 `parse_response` 会优先提取 `content`，只有在 `content` 缺失时才会 fallback 读取 `reasoning_content`。
  - DeepSeek 是在同级输出 `content` 与 `reasoning_content`。如果 `content` 有值，其推理思考链（Reasoning Chain）会在后端解析时被**丢弃**，前端将无法获得并展示该模型的完整思考过程。

---

## 3. 结论

**是否需要前端改动？**
**已完成核心配置与 reasoning 改动**：当前工作树已让用户在 Settings 中直接选择 `openai_compat` 来配置 DeepSeek BYOK。官方 DeepSeek v4 flash/pro 的 Thinking Policy 已由后端返回给前端，`reasoning_content` 也会被解析并保留。

### 3.1 适用条件 (Applicability)
- 仅适用于将 DeepSeek 官方 API 作为 BYOK provider 的场景；普通 OpenAI-compatible 中转服务仍以后端 metadata 为准，不会只因模型名相似就启用 DeepSeek thinking。
- 保证用户在 Settings 中能够直接选择 `openai_compat` 类型来解决 `json_schema` 的不兼容问题。

### 3.2 范围边界 (Scope)
- 本评估和后续方案仅限 ahadiff serve 的 Web 界面配置卡片及对应的 API 契约，不涉及 CLI 命令行下特定 LLM 管道的单独重构。

### 3.3 已知限制 (Known Limitations)
- 当前前端只在后端确认 `modelLimits.thinking.supported=true` 时暴露 `openai_compat` thinking hint 与 Thinking Level 控件。官方 DeepSeek v4 flash/pro 已支持；`deepseek-reasoner` 的 `reasoning_content` 可被保留，但不作为可调 thinking level 控件展示。

---

## 4. 前端修改技术方案

### 4.1 改造点 1：引入 `openai_compat` 选项并增加 DeepSeek 预设
在 [ProviderCard.tsx](viewer/src/components/ProviderCard.tsx) 中进行两处修改：
1. 在 `PROVIDER_CLASSES` 常量中追加 `'openai_compat'`：
   ```typescript
   const PROVIDER_CLASSES = [
     'openai',
     'openai_responses',
     ...
     'lmstudio',
     'openai_compat', // 追加此类型
   ] as const;
   ```
2. 在 `PROVIDER_EXAMPLES` 中新增 `openai_compat` 的默认配置，方便用户一键填写 DeepSeek 模版：
   ```typescript
   openai_compat: {
     base_url: 'https://api.deepseek.com',
     model_name: 'deepseek-v4-flash',
     api_key: 'sk-...',
   }
   ```

### 4.2 改造点 2：Thinking Level 配置的可见性与后端协同
1. 当前不应把 `'openai_compat'` 加入 `SUPPORTS_THINKING`，也不应渲染 `provider_thinking_hint_openai_compat`，除非后端先返回 `modelLimits.thinking.supported=true`。
2. **后端协同（已实现）**：DeepSeek reasoning 已由后端 [thinking.py](src/ahadiff/llm/adapters/thinking.py) 的 `thinking_policy_for` 返回给前端，并补齐 response parsing / cache schema。

### 4.3 改造点 3：i18n 翻译文件同步 (EN / ZH-CN)
翻译包中保留了 `openai_compat` 的思考提示键；当前 UI 只在后端 thinking policy 确认支持后渲染该 key。

#### 英文语言包追加
修改 [en.json](viewer/src/i18n/messages/en.json)：
```json
"provider_thinking_hint_openai_compat": "OpenAI Compatible reasoning (like DeepSeek) consumes extra completion tokens."
```

#### 中文语言包追加
修改 [zh-CN.json](viewer/src/i18n/messages/zh-CN.json)：
```json
"provider_thinking_hint_openai_compat": "OpenAI 兼容的推理（如 DeepSeek）会消耗额外的补全 tokens。"
```

### 4.4 改造点 4：跨浏览器注意事项
在修改前端样式和脚本时，应关注以下兼容性问题：
- **WebKit (Safari)**：Safari 浏览器在渲染 details/summary 折叠动画以及动态切换 model 的 `<select>` 下拉框时，可能会触发短暂的重绘抖动或高度塌陷。需要确保 flex/grid 容器内的高度自适应，并避免使用非标准的 CSS 滚动条和不兼容的 `ResizeObserver` 回调。
- **Firefox**：Firefox 对于 `input[type="password"]` 的内置自动填充及样式控制较为严格，可能产生特有的高对比度聚焦框偏移。应避免在 `ProviderCard.css` 中使用只针对 `-webkit-` 的伪类，同时保证暗色模式和 Forced Colors 下对比度符合 WCAG AA 级标准。
- **Chromium**：主流支持良好，但需要保证在缩放或窄屏容器查询下，DeepSeek 的长模型名称与 Base URL 能够正常进行 `word-break: break-all` 折行展示，避免撑破卡片布局。
