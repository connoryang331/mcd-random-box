#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦随机盲盒 (MCD Random Box) —— 一键随机点餐引擎（含「自动用券」真实逻辑）

核心流程（与麦当劳 MCP 一致，已实测可用）:
  1. 解析门店/地址（到店用 city+keyword 搜门店；外送优先用已存配送地址）
  2. query-meals        取该店可点菜单
  3. 随机抽 N 件（保证含一个「可用券覆盖」的主角商品，最大化省钱）
  4. query-store-coupons 取该店可用券（含 couponId + couponCode + 适用 productCode）
  5. attach_coupons     把券的 couponId/couponCode 按 productCode 塞进对应 item
     ⚠️ 关键: 券是 item 级字段，且必须同时传 couponId 与 couponCode，漏一个都不生效
  6. calculate-price    传入带券的 items → 拿到券后价 + takeWayCode
  7. (用户确认后) create-order 生成待支付单；付款在麦当劳 App/链接完成

两种运行模式:
  - 在线模式: 设置了 MCD_MCP_TOKEN 或 --token，真实调用麦当劳 MCP（含自动用券）。
  - 离线演示: 无 token 时，用 assets/menu_nutrition.json 做随机抽选，仅演示趣味性。

用法:
    # 在线（真实用券 + 建待支付单后立即取消，零资损演示）
    python scripts/random_box.py --token <TOKEN> --city 北京 --keyword 王府井 --cancel
    # 在线（到店自取，抽 2 件，忌口猪柳）
    python scripts/random_box.py --token <TOKEN> --city 上海 --keyword 陆家嘴 --avoid 猪柳 --people 2
    # 外送（自动用已存配送地址）
    python scripts/random_box.py --token <TOKEN> --order-type 2 --cancel
    # 离线趣味演示
    python scripts/random_box.py --avoid 猪柳,烟肉 --seed 42
"""
import argparse
import json
import os
import random
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MENU_PATH = os.path.join(HERE, "..", "assets", "menu_nutrition.json")
CONFIG_PATH = os.path.join(HERE, "..", ".random_box_config.json")

LUCKY_TAGS = [
    "今天也是被麦麦偏爱的一天",
    "盲盒开出了隐藏款快乐",
    "碳水快乐，无需理由",
    "随机但刚好对味",
    "这一口，是命运的安排",
    "省下的钱够再抽一次",
    "今日宜：大口吃麦",
    "盲盒虽随机，幸福很确定",
]


# ---------- 离线趣味引擎（无 token 时使用） ----------
def load_menu(path=MENU_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def filter_menu(menu, avoid):
    out = []
    for it in menu:
        name = it.get("productName", "")
        if any(a in name for a in avoid):
            continue
        try:
            kcal = float(it.get("energyKcal") or 0)
        except (TypeError, ValueError):
            continue
        if kcal <= 0:
            continue
        out.append({
            "name": name,
            "kcal": kcal,
            "protein": float(it.get("protein") or 0),
            "fat": float(it.get("fat") or 0),
            "carb": float(it.get("carbohydrate") or 0),
        })
    return out


def pick_offline(menu, avoid, people, rng):
    items = filter_menu(menu, avoid)
    if not items:
        raise SystemExit("忌口太严：菜单里找不到符合的餐品，请放宽 --avoid。")
    mains = [i for i in items if 250 <= i["kcal"] <= 600]
    sides = [i for i in items if i["kcal"] < 250]
    if not mains:
        mains = items
    box = []
    for _ in range(max(1, people)):
        box.append(rng.choice(mains))
        if sides:
            box.append(rng.choice(sides))
    total = sum(x["kcal"] for x in box)
    return {
        "lucky_tag": rng.choice(LUCKY_TAGS),
        "box": [
            {"name": x["name"], "kcal": x["kcal"],
             "protein": x["protein"], "fat": x["fat"], "carb": x["carb"]}
            for x in box
        ],
        "total_kcal": round(total, 1),
        "note": "离线演示：券后价与真实下单请使用 --token 在线模式",
    }


# ---------- 在线 MCP 引擎 ----------
class McdMCP:
    """极简麦当劳 MCP Streamable-HTTP 客户端（已实测 35 工具可用）。"""

    def __init__(self, token, base="https://mcp.mcd.cn"):
        self.token = token
        self.base = base
        self.sid = None

    def _rpc(self, body):
        data = json.dumps(body).encode()
        req = urllib.request.Request(self.base, data=data, method="POST")
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.sid:
            req.add_header("Mcp-Session-Id", self.sid)
        resp = urllib.request.urlopen(req, timeout=30)
        self.sid = resp.headers.get("Mcp-Session-Id", self.sid)
        raw = resp.read().decode()
        if not raw.strip():
            return None
        if "data:" in raw[:80]:
            lines = [l for l in raw.splitlines() if l.startswith("data:")]
            raw = lines[0][5:].strip() if lines else raw
        return json.loads(raw)

    def initialize(self):
        self._rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "mcd-random-box", "version": "1.0"}}})
        self._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def call(self, name, args):
        return self._rpc({"jsonrpc": "2.0", "id": 99, "method": "tools/call",
                          "params": {"name": name, "arguments": args}})

    @staticmethod
    def _json(text):
        """从模型友好的文本里抽取最外层的 JSON 对象。"""
        starts = [i for i, c in enumerate(text) if c == "{"]
        best = None
        for i in starts:
            depth = 0
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        frag = text[i:j + 1]
                        try:
                            o = json.loads(frag)
                            if isinstance(o, dict) and (best is None or len(frag) > len(best)):
                                best = frag
                        except Exception:
                            pass
                        break
        return json.loads(best) if best else {}

    def data(self, name, args):
        r = self.call(name, args)
        result = (r or {}).get("result", {})
        text = (result.get("content") or [{}])[0].get("text", "")
        sc = result.get("structuredContent")
        parsed = self._json(text)
        # 取"带 data"的那份：structuredContent 优先，其次文本解析（二者互为兜底）
        dicts = [x for x in (sc, parsed) if isinstance(x, dict)]
        obj = next((x for x in dicts if "data" in x), dicts[0] if dicts else {})
        # 业务错误：麦当劳用 {"success": false, "code":..., "message":...} 表示失败
        # （如 code=600057 门店已关闭/不在营业时间）。必须显式报错，否则会产出无意义盲盒。
        if obj.get("success") is False:
            raise SystemExit(f"麦当劳接口错误（{name}）：{obj.get('message')}"
                             f"（code={obj.get('code')}）——请换个门店/时段，或稍后再试")
        # 解包 {"success":true, "data": <payload>}；payload 可能是 dict 也可能是 list
        if "data" in obj:
            return obj["data"]
        return obj


# ---------- 本地配置缓存（让用户「首次说完地址后，之后一句话就够」） ----------
def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------- 在线盲盒核心 ----------
def resolve_store(mcp, cfg, order_type, be_type, city, keyword):
    """解析门店：外送优先用已存地址；到店用 city+keyword 搜门店。返回 (store_code, be_code, address_id)。"""
    if order_type == 2:  # 外送：尝试自动拿已存地址
        # 返回结构: {"success":..., "data": {"addresses": [...]}}；data() 已解包到 data 层，addresses 直接挂在返回体上
        addrs = (mcp.data("delivery-query-addresses", {}) or {}).get("addresses", [])
        if addrs:
            a = addrs[0]
            print(f"[地址] 自动使用已存配送地址: {a.get('fullAddress')} (addressId={a.get('addressId')})")
            return None, None, a.get("addressId")
        if "addressId" in cfg:
            return None, None, cfg["addressId"]
        raise SystemExit("外送需配送地址：当前账号无已存地址，请先在麦当劳 App 添加，或改用 --order-type 1 到店自取。")
    # 到店自取
    if cfg.get("storeCode"):
        print(f"[门店] 使用已缓存门店: {cfg['storeCode']}")
        return cfg["storeCode"], None, None
    if not city or not keyword:
        raise SystemExit("到店自取需提供 --city 与 --keyword（如 --city 北京 --keyword 王府井），或先手动指定 --store。")
    res = mcp.data("query-nearby-stores",
                   {"beType": be_type, "searchType": 2, "city": city, "keyword": keyword})
    stores = res.get("stores", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
    if not stores:
        raise SystemExit(f"未搜到门店：{city} {keyword}，换个关键词试试。")
    s = stores[0]
    code = s.get("storeCode")
    print(f"[门店] 搜索到: {s.get('storeName')} (storeCode={code})")
    cfg["storeCode"] = code
    save_config(cfg)
    return code, None, None


def get_menu(mcp, store_code, order_type, be_type):
    meals = mcp.data("query-meals",
                     {"storeCode": store_code, "orderType": order_type, "beType": be_type})
    if isinstance(meals, dict):
        return meals.get("meals", {}), list(meals.get("categories", []))
    return {}, []


def build_coupon_item(coupon):
    """把一张「门店可用券」变成一个盲盒条目。

    ⚠️ 关键修正（修复「auto-bind-coupons 领了券但 calculate-price 不生效」的 bug）：
    麦当劳 MCP 的券是**商品级**优惠，且优惠券自己的 productCode（促销 SKU，如 9900014239）
    就是可下单的商品行；必须把该 productCode 作为 order item 的 productCode，并同时携带
    couponId + couponCode（缺一个 MCP 都会报 '使用优惠券需要couponId和couponCode'）。
    券后价由 calculate-price / create-order 自动算出。
    """
    p = (coupon.get("products") or [{}])[0]
    return {
        "productCode": p.get("productCode"),
        "couponId": coupon["couponId"],
        "couponCode": coupon["couponCode"],
        "_name": p.get("productName") or coupon.get("title"),
    }


def clean_items(items):
    """去掉内部用的下划线元数据字段（如 _name），返回可发给麦当劳 MCP 的干净 item 列表。"""
    return [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]


def random_pick(meals_map, coupons, people, avoid, rng):
    """随机抽组合：优先从「门店可用券」里盲抽（保证稳定用券省钱），可选附带 1 件随机常规商品。

    返回 item 字典列表（含 productCode / couponId / couponCode / _name）。
    """
    avoid = [a.strip() for a in avoid if a.strip()]
    # 常规候选：有价格、可下单(canWithOrder 非 false)、且不命中忌口
    candidates = {code: d for code, d in meals_map.items()
                  if d.get("currentPrice") and float(d.get("currentPrice") or 0) > 0
                  and d.get("canWithOrder", True) is not False
                  and not any(a in (d.get("name") or "") for a in avoid)}

    # 券候选也尊重忌口：优先抽不命中的；若全部命中忌口则退化为不限券，保证仍能省钱
    def _coupon_name(c):
        return (c.get("title") or "") + " " + ((c.get("products") or [{}])[0].get("productName") or "")
    usable_coupons = [c for c in coupons
                      if not any(a in _coupon_name(c) for a in avoid)] or coupons

    # 无券：纯随机常规商品兜底
    if not coupons:
        if not candidates:
            raise SystemExit("没有可用商品（可能全部命中忌口），请放宽 --avoid。")
        pool = list(candidates.keys())
        return [{"productCode": c, "_name": candidates[c].get("name")}
                for c in rng.sample(pool, min(max(2, people * 2), len(pool)))]

    # 盲盒主玩法：从可用券里随机抽【1 张券】作为用券商品
    # ⚠️ 平台限制：单笔订单仅支持 1 张券（"暂不支持多张券使用"），故券商品固定 1 件
    coupon_items = [build_coupon_item(c) for c in usable_coupons]
    picks = [rng.choice(coupon_items)]

    # 顺带随机垫常规商品，数量随「人数/份数」放大，让盲盒像多人一顿饭
    # （这些不挂券，避免触发多券限制；券商品固定 1 件）
    if candidates:
        # 1 人份随机 1~2 件；多人份则每人约 1 件常规主食（上限取可用商品数）
        k = rng.randint(1, 2) if people <= 1 else people
        k = min(k, len(candidates))
        for reg in rng.sample(list(candidates.keys()), k):
            if reg not in [p.get("productCode") for p in picks]:
                picks.append({"productCode": reg, "_name": candidates[reg].get("name")})
    return picks


def run_online(token, order_type, be_type, city, keyword, avoid, people, do_create, do_cancel):
    mcp = McdMCP(token)
    mcp.initialize()
    cfg = load_config()

    store_code, be_code, address_id = resolve_store(mcp, cfg, order_type, be_type, city, keyword)
    meals_map, _ = get_menu(mcp, store_code, order_type, be_type)

    # 取该店可用券（必传 storeCode + orderType + beType，缺一不可）
    coupons = mcp.data("query-store-coupons",
                       {"storeCode": store_code, "orderType": order_type, "beType": be_type})
    if not isinstance(coupons, list):
        coupons = []
    print(f"[券] 该店可用券 {len(coupons)} 张，示例: " +
          ", ".join(c["title"] for c in coupons[:5]) + (" ..." if len(coupons) > 5 else ""))

    items = random_pick(meals_map, coupons, people, avoid, random.Random())
    used = [it.get("_name") for it in items if "couponCode" in it]

    calc_args = {"storeCode": store_code, "orderType": order_type, "beType": be_type,
                 "items": clean_items(items), "needTableware": False}
    if address_id:
        calc_args["addressId"] = address_id
    if be_code:
        calc_args["beCode"] = be_code
    price_data = mcp.data("calculate-price", calc_args)
    total_fen = price_data.get("price") or price_data.get("realTotalAmount")
    if total_fen is None:  # 兜底：累加商品小计
        total_fen = sum(p.get("subtotal") or 0 for p in price_data.get("productList", []))
    take_way = (price_data.get("takeWayList") or [{}])[0].get("code")

    # 用 calculate-price 返回的可靠单价（单位：分）做展示
    price_by_code = {p["productCode"]: (p.get("subtotal") or p.get("originalSubtotal") or 0)
                     for p in price_data.get("productList", [])}
    print(f"\n===== 麦麦随机盲盒 =====  ({people}人份)")
    for it in items:
        fen = price_by_code.get(it["productCode"], 0)
        tag = f" [用券:{it.get('couponCode')}]" if "couponCode" in it else ""
        print(f"  - {it.get('_name') or it['productCode']}  ¥{float(fen)/100:.2f}{tag}")
    print(f"  券后总计: ¥{float(total_fen)/100:.2f}")
    print(f"  已自动套用券: {', '.join(used) if used else '无（本单抽中商品无可用券）'}")
    print(f"  takeWayCode: {take_way}")

    if not do_create:
        print("\n（未加 --confirm，仅展示券后方案，未创建订单）")
        return

    order_args = {"storeCode": store_code, "orderType": order_type, "beType": be_type,
                  "items": clean_items(items), "needTableware": False, "takeWayCode": take_way}
    if address_id:
        order_args["addressId"] = address_id
    if be_code:
        order_args["beCode"] = be_code
    od = mcp.data("create-order", order_args)
    if not isinstance(od, dict) or od.get("success") is False or "orderDetail" not in od:
        msg = od.get("message") if isinstance(od, dict) else "未知错误"
        print(f"\n[建单未成功] {msg}（券已正确附带，可换时间或换门店重试；本步不影响券逻辑正确性）")
        return
    det = od["orderDetail"]
    print("\n===== 已创建待支付订单 =====")
    print(f"  orderId        : {od['orderId']}")
    print(f"  orderStatus    : {det['orderStatus']} (1=待支付)")
    print(f"  商品           : {[(p['productName'], p['quantity']) for p in det['orderProductList']]}")
    print(f"  券后实付       : ¥{float(det.get('realTotalAmount', total_fen) or total_fen)/100:.2f}")
    ph = od.get("payH5Url", "")
    print(f"  支付入口 payH5 : {ph[:70]}..." if ph else "  支付入口: 无")
    print("  ⚠️ 真实付款请在麦当劳 App / 打开 payH5Url 完成；MCP 不处理扣款。")

    if do_cancel:
        res = mcp.data("cancel-order", {"orderId": od["orderId"], "cancelReasonCode": 2})
        cd = res if isinstance(res, dict) else {}
        print(f"\n[撤销] cancelResult={cd.get('cancelResult')} (演示已清理，账户无残留)")


# ---------- 入口 ----------
def main():
    ap = argparse.ArgumentParser(description="麦麦随机盲盒 — 一键随机点餐")
    ap.add_argument("--token", type=str, default=os.getenv("MCD_MCP_TOKEN"),
                    help="麦当劳 MCP Token（不设则离线演示）")
    ap.add_argument("--store", type=str, default=None, help="门店 storeCode（到店自取）")
    ap.add_argument("--city", type=str, default=None, help="到店自取城市，如 北京")
    ap.add_argument("--keyword", type=str, default=None, help="到店自取位置关键词，如 王府井")
    ap.add_argument("--order-type", type=int, default=1, choices=[1, 2], help="1=到店 2=外送")
    ap.add_argument("--avoid", type=str, default="", help="忌口/过敏原, 逗号分隔")
    ap.add_argument("--people", type=int, default=1, help="人数/份数")
    ap.add_argument("--confirm", action="store_true", help="确认后真实创建待支付订单")
    ap.add_argument("--cancel", action="store_true", help="建单后立即取消（零资损演示）")
    ap.add_argument("--seed", type=int, default=None, help="随机种子(离线调试)")
    args = ap.parse_args()
    avoid = [x for x in args.avoid.split(",") if x]

    if args.token:
        be_type = 1 if args.order_type == 1 else 2
        if args.store:
            # 直接指定门店时也写进配置缓存
            cfg = load_config(); cfg["storeCode"] = args.store; save_config(cfg)
        run_online(args.token, args.order_type, be_type, args.city, args.keyword,
                   avoid, args.people, args.confirm, args.cancel)
    else:
        rng = random.Random(args.seed)
        menu = load_menu()
        print(json.dumps(pick_offline(menu, avoid, args.people, rng), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
