# 麦麦随机盲盒 · MCD Random Box

> 麦当劳程序员创意开发大赛参赛作品（非官方）· 基于麦当劳 MCP 能力

**一句话介绍**：不知道吃啥？**一键开启麦当劳盲盒**——从你可用券里随机抽一张真实套用，算出券后惊喜价，确认即下单（生成待支付订单，付款在麦当劳 App 完成）。简单、好玩、真能省。

## 为什么做这个？

点麦当劳最常见的场景其实是"随便来点/不知道吃啥"。现有参赛作品多在"算卡路里"或"纯省钱"，而**最自然的下单动作应该是"一键盲盒"**：你不用选，AI 替你抽，还顺手把券用满，最后只问你一句"就这单？"——这才是真正的一键下单。

## 核心功能

- 🎲 **一键盲盒**：说一句"随机来一份麦当劳"/"帮我盲盒点"，即刻抽到一份搭配（主食+小食/饮品）
- 🎟️ **自动省钱**：用 `query-store-coupons` 取该店可用券，盲盒从券里随机抽 1 张，把券的 `couponId`+`couponCode` 真实塞进订单项，由 `calculate-price` 算出**券后惊喜价**（平台单笔仅支持 1 张券）
- 🏪 **到店 / 外送都行**：外送自动用已存配送地址（`delivery-query-addresses`）；到店首次给一次「城市+关键词」后本地缓存门店，之后一句话即点
- 🍀 **幸运签**：每份盲盒附一句随机幸运语，增加趣味与分享欲（利于传播/Star）
- 🤖 **WorkBuddy 原生**：以 WorkBuddy Skill 形式交付，对话即点

## 适用人群

- "不知道吃啥"综合征患者
- 想省心、不想做选择的人
- 想顺手用掉麦当劳优惠券的人
- 喜欢盲盒/抽奖趣味、愿意分享的年轻用户

## 目录结构

```
mcd-random-box/
├── README.md                  # 本文件
├── CONTEST_DECLARATION.md     # 参赛声明（官方原文件，不可改）
├── MCP_INTEGRATION.md         # MCP Server / Tool / 调用流程 / 业务价值
├── mcp-config.example.json    # 脱敏 MCP 配置示例（仅环境变量占位符）
├── SKILL.md                   # WorkBuddy Skill 定义（核心交付物）
├── workbuddy.md               # WorkBuddy 对话上下文导出（专项奖励必交）
├── scripts/
│   └── random_box.py          # 盲盒随机抽选（离线趣味部分）
└── assets/
    └── menu_nutrition.json    # 麦当劳餐品真实营养数据（来自 list-nutrition-foods）
```

## 安装与使用

### 1. 配置麦当劳 MCP（WorkBuddy）

将下面的配置写入 WorkBuddy 的 MCP 配置文件（把 Token 换成你自己的）：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

> 详细步骤见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)。**切勿把真实 Token 提交到仓库。**

### 2. 在 WorkBuddy 中一句话点单

直接对 WorkBuddy 说，例如（**越短越好**）：

- 完整句："随机来一份麦当劳" / "帮我盲盒点，到店自取" / "不知道吃啥，给我抽个盲盒，用券省点"
- 极简触发词（打字最少，推荐）：**盲盒麦当劳 / 盲盒mdl / 盲盒麦麦 / 盲盒mc / 盲盒麦**、**随机麦当劳 / 随机mdl / 随机麦麦 / 随机mc / 随机麦**、**抽麦当劳 / 抽mc**
- **多人份**：在触发词后加人数即可放大份量，如 **盲盒麦当劳 2人份 / 随机mdl 三人 / 抽麦 双人份 / 麦麦盲盒 4人 / 盲盒mc 多人**
- 也可只说 **"来个麦"** 表达"帮我决定"（单独的"盲盒""随机"不再触发，避免与其他 Skill 撞车）

WorkBuddy 会加载本仓库的 `SKILL.md`，调用麦当劳 MCP：取可用券 → 盲盒抽 1 张券 → 把券码塞进订单项 → 算券后价 → 你确认 → 创建订单（`create-order` 返回 `payH5Url` 支付链接，付款在麦当劳 App / 微信小程序完成）。

### 3. 命令行试跑盲盒

```bash
# 离线趣味（无需 token，基于营养数据随机 + 幸运签）
python scripts/random_box.py
python scripts/random_box.py --avoid 猪柳,烟肉

# 在线真实模式（带券下单；--confirm 才建单，--cancel 建完即撤做零资损演示）
export MCD_MCP_TOKEN=<你的Token>
python scripts/random_box.py --city 北京 --keyword 王府井 --people 2 --confirm --cancel
python scripts/random_box.py --order-type 2            # 外送：自动用已存配送地址
```

示例输出：

```json
{
  "lucky_tag": "盲盒开出了隐藏款快乐",
  "box": [
    { "name": "板烧鸡腿堡", "kcal": 391, "protein": 23, "fat": 17, "carb": 35 },
    { "name": "圆筒冰淇淋", "kcal": 93, "protein": 2, "fat": 3, "carb": 14 }
  ],
  "total_kcal": 484.0
}
```

## 技术说明

- **SKILL.md** 是核心：它指导 WorkBuddy 智能体在"盲盒点单"意图下调用麦当劳 MCP 工具（选品、领券、算价、下单）。
- **scripts/random_box.py** 是盲盒完整引擎（在线模式真实调麦当劳 MCP）：
  - 盲盒从 `query-store-coupons` 返回的可用券里随机抽 1 张，用券自己的 `products[].productCode`（促销 SKU）作为订单项，并**同时带 `couponId` + `couponCode`**（缺一个 MCP 会报"使用优惠券需要couponId和couponCode"）；
  - `calculate-price` / `create-order` 自动算出券后价（单位**分**）；付款在麦当劳 App 完成。
  - 离线无 token 时退化为趣味随机（基于 `assets/menu_nutrition.json`）。

## 合规与免责

- 本项目为大赛创意作品，由参赛者独立开发，**非麦当劳官方产品**。
- 餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准；输出仅供参考，不构成营养或医疗建议。
- 项目已包含 `CONTEST_DECLARATION.md` 原创性、合规与信息安全声明，配置文件中不含真实密钥。
