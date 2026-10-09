# MCP 集成说明（MCP_INTEGRATION.md）

## 1. 使用的麦当劳 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>`（Token 来自麦当劳开放平台 https://open.mcd.cn/mcp） |
| 限流 | 每 Token 每分钟最多 600 次请求（超出返回 429） |

> 配置示例见仓库根目录 `mcp-config.example.json`（已脱敏，仅使用 `${MCD_MCP_TOKEN}` 环境变量占位符）。

## 2. 实际使用的 Tools

本项目真实调用了以下麦当劳 MCP 工具（共 35 个可用工具中，本 Skill 用到约 12 个）：

### 盲盒选品
| Tool | 用途 |
|---|---|
| `query-meals` | 按场景（到店 orderType=1 / 外送 orderType=2）查询可点餐品，作为盲盒抽取的来源 |

### 自动省钱（核心卖点）
| Tool | 用途 |
|---|---|
| `auto-bind-coupons` | 把卡包里"未领取"的券先领进来（确保后续有券可用） |
| `available-coupons` | 查询可领取的优惠券列表 |
| `query-store-coupons` | 查询指定门店+订单类型下可用券；**必须传 storeCode+orderType+beType**，每项返回 `couponId`、`couponCode`、适用商品 `products[].productCode` |
| `calculate-price` | 计算含优惠后的价格（返回 `price` 单位**为分**）；用券商品的 item 须同时带 `couponId`+`couponCode` |

> ⚠️ **用券关键（踩坑点）**：麦当劳 MCP 的券是**商品级**优惠，且优惠券自己的 `products[].productCode`（促销 SKU）**就是可下单的商品行**。把该 `productCode` 作为 order item 的 `productCode`，并**同时**在 item 内附带 `couponId` 与 `couponCode`（缺一个 MCP 都会返回"使用优惠券需要couponId和couponCode"），`calculate-price`/`create-order` 才会给出券后价。**单笔订单仅支持 1 张券**（多张会报"暂不支持多张券使用"）。

### 一键下单
| Tool | 用途 |
|---|---|
| `create-order` | 创建**待支付**订单（到店/外送），需用户确认；返回 `payH5Url` 支付链接，用户在浏览器/App 打开该链接完成付款 |
| `query-nearby-stores` | 到店自取/得来速门店查询（默认沿用上次门店） |
| `delivery-query-addresses` / `delivery-query-stores` | 外送地址与可配送门店 |

### 智能默认（让"一键"更顺）
| Tool | 用途 |
|---|---|
| `delivery-query-addresses` | 外送时查询用户已存配送地址；**若返回非空，自动选用，无需询问**（这是 MCP 侧能"自动拿到本地地址"的唯一途径） |
| `query-nearby-stores` | 到店自取门店查询（需 `city`+`keyword`；MCP **无法获取用户定位/默认门店**，首次给一次后由脚本缓存在 `.random_box_config.json`） |
| `now-time-info` | 获取当前时间，用于活动/预约判断 |
| `campaign-calendar` | 查询当月活动，给盲盒加一句"今日有XX活动"的氛围提示 |

> 📍 **关于"默认拿到用户本地地址"**：麦当劳 MCP **不提供用户定位或默认门店**（实测 `delivery-query-addresses` 仅返回用户主动保存过的地址，新账号为空）。因此：外送可自动用已存地址；到店需用户首次提供「城市+关键词」一次，之后本地缓存，实现"一句话即点"。本仓库 `scripts/random_box.py` 已实现该缓存逻辑。

## 3. 调用流程

```
用户:"随机来一份麦当劳" / "帮我盲盒点"
        │
        ▼
┌─────────────────────────────┐
│ 0. 智能默认(可选)            │  order-list / query-order 取上次门店或地址
│    → 决定 到店 / 外送         │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 1. 盲盒选品（以券为核心）     │  query-store-coupons(storeCode+orderType+beType) 取可用券
│                             │  从可用券里随机抽 1 张 → 用券的 products[].productCode
│                             │  （促销SKU）作为订单项，并带 couponId+couponCode
│                             │  可选再垫 1~2 件常规餐品（来自 query-meals，不挂券）
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ 2. 算券后惊喜价              │  calculate-price(items) → price(分) 即券后总价
│                             │  展示: 抽中餐品 + 券后价 + 省多少 + 幸运签
└─────────────────────────────┘
        │  展示: 抽中餐品 + 原价 + 券后价 + 省多少 + 幸运签
        ▼
┌─────────────────────────────┐
│ 3. 确认 → create-order       │  仅当用户明确确认才生成待支付订单（到店/外送）；create-order 返回 payH5Url 支付链接，用户在浏览器/App 打开完成付款
└─────────────────────────────┘
```

## 4. 业务价值

- **极致简单**：用户无需选择，一句话即触发"抽+省+下单"，是最贴近"一键下单"的体验。
- **真实省钱**：盲盒从 `query-store-coupons` 可用券里抽 1 张，把券码（couponId+couponCode + 促销SKU）真实塞进订单项，`calculate-price` 实算券后价，用户体感惊喜。
- **易传播**：盲盒+幸运签具备分享属性，利于 Star 增长（排行榜只看公开 Star）。
- **真实可用**：选品、领券、算价、生成订单（create-order）全部经由麦当劳官方 MCP 实时完成；付款在麦当劳 App/小程序完成，满足"真实使用麦当劳 MCP"的参赛要求。
- **合规友好**：不对比/贬低其他品牌，输出不构成专业建议，注明以官方实时结果为准。
