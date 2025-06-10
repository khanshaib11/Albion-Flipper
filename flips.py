import requests
import pandas as pd
import json
from datetime import datetime, timedelta

# CONFIGURATION
ROYAL_CITIES = ["Martlock", "Fort Sterling", "Lymhurst", "Bridgewatch", "Thetford", "Brecilien"]
ALL_MARKETS = ROYAL_CITIES + ["Black Market", "Caerleon"]
QUALITIES = [1, 2, 3, 4, 5]
FEE_RATE = 0.065
PROFIT_THRESHOLD = 50000      # Minimum profit in silver
PROFIT_PCT_THRESHOLD = 10     # Minimum profit percentage
MIN_VOLUME = 2                # Minimum BM buy volume
MAX_AGE_MINUTES = 60

API_URL = "https://www.albion-online-data.com/api/v2/stats/prices/{}?locations={}&qualities={}&server=asia"

RESOURCE_IDS = {
    "runes": ["T4_RUNE", "T5_RUNE", "T6_RUNE", "T7_RUNE", "T8_RUNE"],
    "souls": ["T4_SOUL", "T5_SOUL", "T6_SOUL", "T7_SOUL", "T8_SOUL"],
    "relics": ["T4_RELIC", "T5_RELIC", "T6_RELIC", "T7_RELIC", "T8_RELIC"]
}

# Enchanting cost table: (tier, from_enchant, to_enchant)
ENCHANT_COSTS = {
    (4, 0, 1): {"silver": 10000, "runes": 15},
    (4, 1, 2): {"silver": 20000, "runes": 30},
    (4, 2, 3): {"silver": 30000, "souls": 15},
    (5, 0, 1): {"silver": 20000, "runes": 20},
    (5, 1, 2): {"silver": 40000, "runes": 40},
    (5, 2, 3): {"silver": 60000, "souls": 20},
    (6, 0, 1): {"silver": 40000, "runes": 30},
    (6, 1, 2): {"silver": 80000, "runes": 60},
    (6, 2, 3): {"silver": 120000, "souls": 30},
    (7, 0, 1): {"silver": 80000, "runes": 40},
    (7, 1, 2): {"silver": 160000, "runes": 80},
    (7, 2, 3): {"silver": 240000, "souls": 40},
    (8, 0, 1): {"silver": 160000, "runes": 50},
    (8, 1, 2): {"silver": 320000, "runes": 100},
    (8, 2, 3): {"silver": 480000, "souls": 50},
}

def fetch_prices(item_id, cities, qualities):
    city_str = ",".join(cities)
    qual_str = ",".join(str(q) for q in qualities)
    url = API_URL.format(item_id, city_str, qual_str)
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        pass
    return []

def fetch_resource_prices():
    all_ids = []
    for ids in RESOURCE_IDS.values():
        all_ids.extend(ids)
    prices = fetch_prices(",".join(all_ids), ["Caerleon"], [1])
    res = {}
    for entry in prices:
        if entry["sell_price_min"] > 0 and is_recent(entry["sell_price_min_date"]):
            item_id = entry["item_id"]
            tier = int(item_id[1])
            if "RUNE" in item_id:
                res[("runes", tier)] = entry["sell_price_min"]
            elif "SOUL" in item_id:
                res[("souls", tier)] = entry["sell_price_min"]
            elif "RELIC" in item_id:
                res[("relics", tier)] = entry["sell_price_min"]
    # Fallback defaults if missing
    defaults = {
        ("runes", 4): 1000, ("runes", 5): 3000, ("runes", 6): 5000, ("runes", 7): 10000, ("runes", 8): 20000,
        ("souls", 4): 5000, ("souls", 5): 10000, ("souls", 6): 20000, ("souls", 7): 40000, ("souls", 8): 80000,
        ("relics", 4): 10000, ("relics", 5): 20000, ("relics", 6): 40000, ("relics", 7): 80000, ("relics", 8): 160000,
    }
    for k, v in defaults.items():
        if k not in res:
            res[k] = v
    return res

def is_recent(date_str):
    if not date_str:
        return False
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ")
        return datetime.utcnow() - dt < timedelta(minutes=MAX_AGE_MINUTES)
    except Exception:
        return False

def parse_tier_and_enchant(item_id):
    # e.g. T6_2H_CURSEDSTAFF@3
    parts = item_id.split("_")
    tier = int(parts[0][1:]) if parts[0].startswith("T") and parts[0][1:].isdigit() else 0
    enchant = 0
    if "@" in item_id:
        enchant = int(item_id.split("@")[1])
    return tier, enchant

def get_item_name(item_id):
    # Simplified readable name
    base = item_id.split("@")[0]
    enchant = item_id.split("@")[1] if "@" in item_id else "0"
    tier = base.split("_")[0][1:]
    name = base.split("_", 1)[1] if "_" in base else base
    return f"T{tier} {name.replace('_', ' ')} .{enchant}"

def calc_enchant_cost(tier, from_enchant, to_enchant, resource_prices):
    key = (tier, from_enchant, to_enchant)
    cost = ENCHANT_COSTS.get(key)
    if not cost:
        return None
    total = cost.get("silver", 0)
    for mat, qty in cost.items():
        if mat == "silver":
            continue
        total += resource_prices.get((mat, tier), 0) * qty
    return total

if __name__ == "__main__":
    # Load items
    try:
        with open("latest.json", encoding="utf-8") as f:
            all_items = json.load(f)
        ITEMS = [item["UniqueName"] for item in all_items]
    except Exception:
        ITEMS = [
            "T4_2H_CURSEDSTAFF", "T5_2H_CURSEDSTAFF", "T6_2H_CURSEDSTAFF",
            "T7_2H_CURSEDSTAFF", "T8_2H_CURSEDSTAFF"
        ]
    resource_prices = fetch_resource_prices()
    flips = []
    for item_id in ITEMS:
        base_id = item_id.split("@")[0]
        tier, _ = parse_tier_and_enchant(base_id)
        for quality in QUALITIES:
            # Fetch all enchant levels for this item/quality
            price_data = {}
            for enchant in [0, 1, 2, 3]:
                id_e = f"{base_id}@{enchant}" if enchant else base_id
                prices = fetch_prices(id_e, ALL_MARKETS, [quality])
                for entry in prices:
                    key = (enchant, entry["city"])
                    price_data[key] = entry
            # All city/city direct flips (same enchant)
            for enchant in [0, 1, 2, 3]:
                for buy_city in ALL_MARKETS:
                    for sell_city in ALL_MARKETS:
                        if buy_city == sell_city:
                            continue
                        buy = price_data.get((enchant, buy_city))
                        sell = price_data.get((enchant, sell_city))
                        if not buy or not sell:
                            continue
                        if not buy.get("sell_price_min", 0) or not sell.get("buy_price_max", 0):
                            continue
                        if not is_recent(buy.get("sell_price_min_date")) or not is_recent(sell.get("buy_price_max_date")):
                            continue
                        if sell.get("buy_price_max_vol", 0) < MIN_VOLUME:
                            continue
                        buy_price = buy["sell_price_min"]
                        sell_price = sell["buy_price_max"]
                        profit = sell_price * (1-FEE_RATE) - buy_price
                        profit_pct = 100 * profit / buy_price if buy_price else 0
                        if profit > PROFIT_THRESHOLD and profit_pct > PROFIT_PCT_THRESHOLD:
                            flips.append({
                                "Type": "Direct",
                                "Item Name": get_item_name(f"{base_id}@{enchant}" if enchant else base_id),
                                "Buy Enchant": enchant,
                                "Buy City": buy_city,
                                "Buy Price": buy_price,
                                "Sell Enchant": enchant,
                                "Sell City": sell_city,
                                "Sell Price": sell_price,
                                "Enchant Cost": 0,
                                "Total Cost": buy_price,
                                "Profit": profit,
                                "Profit %": profit_pct,
                                "Quality": quality,
                                "Volume": sell.get("buy_price_max_vol", 0)
                            })
            # Enchant flips (buy lower enchant, enchant up, sell higher)
            for from_enchant, to_enchant in [(0, 1), (1, 2), (2, 3)]:
                for buy_city in ALL_MARKETS:
                    for sell_city in ALL_MARKETS:
                        if buy_city == sell_city:
                            continue
                        buy = price_data.get((from_enchant, buy_city))
                        sell = price_data.get((to_enchant, sell_city))
                        if not buy or not sell:
                            continue
                        if not buy.get("sell_price_min", 0) or not sell.get("buy_price_max", 0):
                            continue
                        if not is_recent(buy.get("sell_price_min_date")) or not is_recent(sell.get("buy_price_max_date")):
                            continue
                        if sell.get("buy_price_max_vol", 0) < MIN_VOLUME:
                            continue
                        buy_price = buy["sell_price_min"]
                        sell_price = sell["buy_price_max"]
                        enchant_cost = calc_enchant_cost(tier, from_enchant, to_enchant, resource_prices)
                        if enchant_cost is None:
                            continue
                        total_cost = buy_price + enchant_cost
                        profit = sell_price * (1-FEE_RATE) - total_cost
                        profit_pct = 100 * profit / total_cost if total_cost else 0
                        if profit > PROFIT_THRESHOLD and profit_pct > PROFIT_PCT_THRESHOLD:
                            flips.append({
                                "Type": f"Enchant {from_enchant}->{to_enchant}",
                                "Item Name": get_item_name(base_id),
                                "Buy Enchant": from_enchant,
                                "Buy City": buy_city,
                                "Buy Price": buy_price,
                                "Sell Enchant": to_enchant,
                                "Sell City": sell_city,
                                "Sell Price": sell_price,
                                "Enchant Cost": enchant_cost,
                                "Total Cost": total_cost,
                                "Profit": profit,
                                "Profit %": profit_pct,
                                "Quality": quality,
                                "Volume": sell.get("buy_price_max_vol", 0)
                            })
    # Output to Excel
    if flips:
        df = pd.DataFrame(flips)
        df = df.sort_values(by="Profit", ascending=False)
        df.to_excel("albion_auto_flips.xlsx", index=False)
        print(f"Exported {len(df)} flips to albion_auto_flips.xlsx")
    else:
        print("No profitable flips found with current thresholds.")