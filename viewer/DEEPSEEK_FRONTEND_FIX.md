# DeepSeek BYOK 前端支持改动报告

根据 `viewer/DEEPSEEK_FRONTEND_EVAL.md` 评估报告的建议，本轮对 ahadiff viewer 前端进行了针对 DeepSeek BYOK 的核心改动适配。

> 2026-06-16 更新：随后独立审查确认仅前端接入不完整；当前工作树已追加后端 `openai_compat` provider class 支持、DeepSeek/OpenRouter limits 修复、错误脱敏修复，以及官方 DeepSeek v4 flash/pro reasoning 支持。本文保留为前端过程记录，最终结论以 `.ccg/tasks/deepseek-windows-fix/REVIEW_INDEPENDENT.md` 为准。

---

## 1. 修改的文件列表

本次修复主要涉及以下 3 个文件：
1. **[ProviderCard.tsx](viewer/src/components/ProviderCard.tsx)**：
   - 在 `PROVIDER_CLASSES` 中追加 `'openai_compat'`，让用户能显式选择 OpenAI 兼容类型，解决 DeepSeek API 不支持 `json_schema` 报错的问题。
   - 在 `PROVIDER_EXAMPLES` 中新增 `openai_compat` 快捷模板（`base_url` 为 `https://api.deepseek.com`，推荐 model 示例 `deepseek-v4-flash`）。
   - `openai_compat` 的 thinking hint 由后端 `modelLimits.thinking.supported` 控制；官方 DeepSeek v4 flash/pro 支持时才展示 Thinking Level。
   - 优化 `ProviderEditForm`：
     - 若当前类为 `openai_compat`，则在下拉列表选项中使用友好翻译（`OpenAI Compatible` / `OpenAI 兼容`）。
     - 在提供商类型下拉框下方增加专门的提示文案 `provider_hint_deepseek`，告知用户在 BYOK 配置 DeepSeek 时应选用 `openai_compat`。
   - thinking 级联依赖后端 metadata，避免把普通 OpenAI-compatible 聚合器误判为 DeepSeek 官方 reasoning 路由。
2. **[en.json](viewer/src/i18n/messages/en.json)**：追加英文翻译项。
3. **[zh-CN.json](viewer/src/i18n/messages/zh-CN.json)**：同步追加对应的中文翻译项。

---

## 2. 新增 i18n Keys 列表

在 `en.json` 与 `zh-CN.json` 的 `Settings_page` 命名空间下，严格同步新增了以下 3 个 key：

| Key | 英文 (en) | 中文 (zh-CN) |
| :--- | :--- | :--- |
| `Settings_page.provider_thinking_hint_openai_compat` | OpenAI Compatible reasoning (like DeepSeek) consumes extra completion tokens. | OpenAI 兼容的推理（如 DeepSeek）会消耗额外的补全 tokens。 |
| `Settings_page.provider_class_openai_compat` | OpenAI Compatible | OpenAI 兼容 |
| `Settings_page.provider_hint_deepseek` | Tip: For DeepSeek BYOK, use 'openai_compat' to ensure JSON response compatibility and enable official v4 reasoning when supported. | 提示：对于 DeepSeek BYOK，请使用 'openai_compat' 作为提供商类型，以确保 JSON 响应兼容性，并在支持时启用官方 v4 推理。 |

---

## 3. 自测与验证结果

历史前端验证命令如下；当前修复轮的最终验证记录见 `.ccg/tasks/deepseek-windows-fix/REVIEW_FIXES.md`：
```bash
pnpm typecheck && pnpm build && pnpm vitest run
```
- **Typecheck**: 编译顺利通过，未抛出任何 TypeScript 类型错误。
- **Build**: 生产环境 bundle 编译正常完成，静态资源及 chunks 无报错。
- **Vitest Unit & Component Tests**: 历史记录曾通过；精确测试数量请以当前验证报告为准，避免把旧计数当作当前事实。

---

## 4. 跨浏览器注意事项

- **WebKit (Safari)**：Safari 对 `details/summary` 的原生渲染行为可能会在样式切换时导致抖动。由于新增的 DeepSeek 提示框是直接嵌入在 `provider-card__form-row` 内的普通段落，并未破坏或更改 summary 等骨架高度，因而在 WebKit 下不会引起重绘延迟或内容塌陷。
- **Firefox**：Firefox 具有其特有的 `input[type="password"]` 填充校验，本次改动没有触碰 password input 及其聚焦样式，保持了原本对 Forced Colors 和暗色模式的无缝渲染支持。
- **Chromium**：在极窄屏或容器缩放的情况下，新模板中 DeepSeek 的 Base URL `https://api.deepseek.com` 长度适中，且已受原有 `.provider-card__hint` 与 input `word-break: break-all` 的全局 CSS 样式约束，能完美折行，不会撑破卡片布局。

---

## 5. Thinking 级联说明

- **当前现状**：后端已实现官方 DeepSeek v4 flash/pro 的 policy 识别、请求体 `thinking` / `reasoning_effort` 生成，以及 `reasoning_content` 解析和缓存。
- **前端门禁**：`ProviderCard.tsx` 不把所有 `openai_compat` 都视为 thinking provider；只有后端 preview 返回 `modelLimits.thinking.supported=true` 时才展示 hint 与 Thinking Level 控件。
