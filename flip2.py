import requests
import csv
import time

API_BASE = "https://east.albion-online-data.com"
API_PATH = "/api/v2/stats/prices"
ROYAL_CITIES = [
    "Bridgewatch", "Martlock", "Fort Sterling",
    "Lymhurst", "Thetford", "Caerleon"
]
BLACK_MARKET = "Black Market"
ALL_LOCATIONS = ROYAL_CITIES + [BLACK_MARKET]
QUALITIES = [1,2,3,4,5]  # 1 = normal quality

ENCHANT_MATERIALS = {1: "RUNE", 2: "SOUL", 3: "RELIC"}
MATERIAL_COUNTS = {
    'one_handed': 288,
    'two_handed': 384,
    'armor_bag': 192,
    'helmet_boots_cape_offhand': 96
}
MIN_PROFIT = 10_000

def infer_item_type(item_id):
    if "2H" in item_id:
        return "two_handed"
    elif any(x in item_id for x in ["ARMOR", "BAG"]):
        return "armor_bag"
    elif any(x in item_id for x in ["HEAD", "SHOES", "CAPE", "OFF"]):
        return "helmet_boots_cape_offhand"
    else:
        return "one_handed"

def parse_tier(item_id):
    try:
        return int(item_id[1])
    except Exception:
        return None

def read_item_ids(filename):
    ids = []
    with open(filename, encoding="utf-8") as f:
        for line in f:
            parts = line.split(":")
            if len(parts) >= 2:
                unique = parts[1].strip()
                if unique:
                    ids.append(unique)
    return ids

def chunked(iterable, n):
    for i in range(0, len(iterable), n):
        yield iterable[i:i + n]

def fetch_prices(item_ids, locations, qualities):
    item_str = ",".join(item_ids)
    loc_str = ",".join(locations)
    qual_str = ",".join(str(q) for q in qualities)
    url = f"{API_BASE}{API_PATH}/{item_str}.json?locations={loc_str}&qualities={qual_str}"
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.json()

def fetch_mat_price(tier, mat_type):
    mat_item = f"T{tier}_{mat_type}"
    for city in ["Lymhurst", "Caerleon"]:
        url = f"{API_BASE}{API_PATH}/{mat_item}.json?locations={city}"
        resp = requests.get(url)
        if resp.status_code != 200:
            continue
        data = resp.json()
        for entry in data:
            price = entry.get("sell_price_min")
            if price and price > 0:
                return price
    return None

def main():
    # 1. Load all item ids (base items, e.g. T4_BLADE)
    base_item_ids = read_item_ids("albion_gear_map.txt")

    # 2. Prepare all possible enchanted item ids (e.g. T4_BLADE@1, T4_BLADE@2, T4_BLADE@3)
    all_item_ids = []
    for base_id in base_item_ids:
        all_item_ids.append(base_id)
        for ench in [1, 2, 3]:
            all_item_ids.append(f"{base_id}@{ench}")

    # 3. Fetch prices for all items and all cities/BM in batches
    all_item_ids = list(set(all_item_ids))
    price_rows = []
    batch_size = 80
    for batch in chunked(all_item_ids, batch_size):
        print(f"Fetching price batch: {batch[0]} ... {batch[-1]}")
        try:
            price_rows += fetch_prices(batch, ALL_LOCATIONS, QUALITIES)
        except Exception as e:
            print("Error fetching batch:", e)
            time.sleep(10)
            continue
        time.sleep(1)

    # 4. Organize price data for fast lookup
    price_lookup = {}
    for entry in price_rows:
        key = (entry['item_id'], entry['quality'], entry['city'])
        price_lookup[key] = entry

    # 5. Flip logic
    results = []
    for base_id in base_item_ids:
        tier = parse_tier(base_id)
        if not tier:
            continue
        item_type = infer_item_type(base_id)
        mats_needed = MATERIAL_COUNTS[item_type]

        # Try all enchant levels 0 (no enchant) to 3
        for enchant_level in [0, 1, 2, 3]:
            if enchant_level == 0:
                item_id = base_id
                enchant_cost = 0
                mat_type = ""
                mat_price = 0
            else:
                item_id = f"{base_id}@{enchant_level}"
                mat_type = ENCHANT_MATERIALS[enchant_level]
                mat_price = fetch_mat_price(tier, mat_type)
                if not mat_price:
                    continue
                enchant_cost = mats_needed * mat_price

            # Find lowest sell price for item, Lymhurst preferred, else Caerleon
            min_sell_price, min_city = None, None
            for city in ["Lymhurst", "Caerleon"]:
                entry = price_lookup.get((base_id, 1, city), {})
                price = entry.get("sell_price_min", 0)
                if price and (min_sell_price is None or price < min_sell_price):
                    min_sell_price = price
                    min_city = city
            if not min_sell_price:
                continue

            # Black Market buy price for the item (with current enchant)
            bm_entry = price_lookup.get((item_id, 1, BLACK_MARKET), {})
            bm_price = bm_entry.get("buy_price_max", 0)
            if not bm_price:
                continue

            total_cost = min_sell_price + enchant_cost
            profit = bm_price - total_cost

            if profit > MIN_PROFIT:
                results.append({
                    "base_item_id": base_id,
                    "enchant_level": enchant_level,
                    "item_id": item_id,
                    "buy_city": min_city,
                    "base_price": min_sell_price,
                    "mat_type": mat_type,
                    "mat_price": mat_price,
                    "mats_needed": mats_needed if enchant_level > 0 else "",
                    "enchant_cost": enchant_cost,
                    "total_cost": total_cost,
                    "bm_price": bm_price,
                    "profit": profit
                })

    # 6. Output results
    with open("albion_enchant_flip_profits.csv", "w", newline='', encoding="utf-8") as fout:
        fieldnames = [
            "base_item_id", "enchant_level", "item_id", "buy_city", "base_price",
            "mat_type", "mat_price", "mats_needed", "enchant_cost",
            "total_cost", "bm_price", "profit"
        ]
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    print("Done! See albion_enchant_flip_profits.csv for your profitable flips.")

if __name__ == "__main__":
    main()