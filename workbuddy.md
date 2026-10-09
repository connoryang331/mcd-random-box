# WorkBuddy 开发对话上下文导出

> 本文件为 **WorkBuddy 专项奖励** 提交材料：内容为在腾讯 WorkBuddy 智能体中开发 / 调试本 Skill「麦麦随机盲盒 (MCD Random Box)」的对话上下文摘要。
> 全程在 WorkBuddy 对话中完成构思、MCP 配置、编码、调试与测试。文件已脱敏，不含真实 Token / 手机号 / 地址。

## 1. 创作起点（对话意图）

用户诉求：「帮我想一个更好的 idea，作为参赛作品。要求非常简单，**一键下单**」，并希望**尽量减少打字**。

在 WorkBuddy 对话中收敛出的核心创意：**麦当劳「随机盲盒」一键点单**——不知道吃啥时，AI 替你抽一份搭配，还顺手把优惠券用满，最后只问一句「就这单？」。

## 2. 在 WorkBuddy 中完成的关键工作

- **交付形态**：封装为 WorkBuddy Skill（`SKILL.md`，YAML frontmatter `name` + `description`），配合盲盒引擎脚本 `scripts/random_box.py`；由 WorkBuddy 的 MCP 连接器调用麦当劳 `mcd-mcp`（streamable HTTP，`https://mcp.mcd.cn`，`Authorization: Bearer ${MCD_MCP_TOKEN}`）。
- **MCP 能力梳理**：在对话中逐一验证了麦当劳 MCP 工具（约 35 个），确认下单仅 `create-order`（生成**待支付**订单并返回 `payH5Url`），**MCP 本身无扣款接口**，付款在麦当劳 App / 小程序完成。
- **真实跑通下单链路**：`query-nearby-stores` → `query-meals` → `query-store-coupons` → `calculate-price` → `create-order`（生成待支付单）→ `cancel-order`（演示用零资损清理）。
- **触发词优化（减少打字）**：对话中反复打磨触发词，最终为「(盲盒|随机|抽) + (麦当劳|麦麦|麦|mc|mdl|金拱门)」组合，并支持**多人份**追加（如「盲盒麦当劳 2人份 / 随机mc 三人」）；移除「盲盒」「随机」单独触发以免与其他 Skill 撞车。

## 3. 在 WorkBuddy 中定位并修复的问题（对话调试记录）

- **「领券但算价不生效」**：定位为券是**商品级**优惠——必须把券自己的促销 SKU `productCode` 作为订单项，且**同时携带 `couponId` + `couponCode`**（缺一报错）；单笔订单平台仅支持 **1 张券**。
- **门店打烊**：`query-meals` 返回 `success:false / code=600057（门店可能已关闭或不在营业时间）`，原逻辑会静默产出无意义盲盒；改为**显式报错**并提示换门店/时段。
- **健壮性**：过滤 `canWithOrder=false` 的不可下单组合；忌口同时作用于「券」与「常规餐品」；发送 MCP 前剥离内部 `_name` 字段；离线极端忌口时友好提示。

## 4. 测试与验证（对话内完成）

- **离线趣味模式**：基于 `assets/menu_nutrition.json` 随机抽取，多随机种子/多人份均正常。
- **在线真实模式**：多个门店验证券后价计算正确（券真实套用，如 3 人份券后 ¥241.40），并覆盖「打烊门店明确报错」「忌口作用于券」「多人份放大」等场景。

## 5. 与 WorkBuddy 的关联说明

- 创意构思、MCP 连接配置、`README.md` / `MCP_INTEGRATION.md` 撰写、`scripts/random_box.py` 编码调试、MCP 工具连通性与券机制验证，**均真实在腾讯 WorkBuddy 对话中完成**；
- 交付物为 WorkBuddy 原生 Skill，可直接在 WorkBuddy 对话中一句话点单。

> 备注：导出时已确认不含真实 MCP Token、手机号、地址等敏感信息；仓库内 MCP 配置一律使用 `${MCD_MCP_TOKEN}` 占位符。
