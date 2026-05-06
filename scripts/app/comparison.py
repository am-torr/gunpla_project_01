# coding: utf-8
"""Store Comparison Module"""
from typing import Dict
import json
from pathlib import Path

def format_grade(raw):
    """Normalize raw grade strings for display."""
    if not raw or str(raw).strip() in ("?", "Unknown", "None"):
        return "Unspec"
    text = str(raw).strip().upper()
    if text.startswith(("MG", "MASTER")): return "MG"
    if text.startswith(("HG", "HIGH")): return "HG"
    if text.startswith("RG"): return "RG"
    if text.startswith("PG"): return "PG"
    if text.startswith("SD"): return "SD"
    return "Other"
    if 'stores' in data:
        for store_entry in data['stores']:
            stores_data[store_entry.get('store_name', 'Unknown')] = store_entry.get('products', [])
    
    products = {}
    currencies_used = set()
    
    for store, products_list in stores_data.items():
        for item in products_list:
            prod = item.get('product', {})
            price_data = item.get('price', {})
            name = prod.get('product_name', '').strip()
            if not name:
                continue
            norm_name = name.lower()
            if norm_name not in products:
                products[norm_name] = {'display_name': name, 'stores': {}, 'grade': prod.get('grade', 'Unknown')}
            p = price_data.get('price')
            curr = price_data.get('currency', 'PHP')
            currencies_used.add(curr)
            if p and p > 0:
                products[norm_name]['stores'][store] = {'price': float(p), 'currency': curr}
    
    PESO = 'â‚±'
    symbols = {'PHP': PESO, 'USD': '$', 'JPY': 'Â¥', 'EUR': 'â‚¬', 'GBP': 'Â£'}
    
    print('\n' + '='*75)
    print('GUNPLA PRICE COMPARISON REPORT'.center(75))
    print('='*75)
    print(f' Stores: {", ".join(stores_data.keys())}')
    print(f' Total products: {sum(len(p) for p in stores_data.values())}')
    print(f' Currencies: {", ".join(sorted(currencies_used))}')
    print('\n STORE EXCLUSIVES:')
    
    exclusives = {s: [] for s in stores_data.keys()}
    for name, d in products.items():
        if len(d['stores']) == 1:
            store = list(d['stores'].keys())[0]
            sd = d['stores'][store]
            exclusives[store].append({'name': d['display_name'], 'price': sd['price'], 'grade': d['grade'], 'curr': sd['currency']})
    
    total_ex = 0
    for store, items in exclusives.items():
        if items:
            curr_code = items[0]['curr']
            symbol = symbols.get(curr_code, curr_code + ' ')
            print(f'\n   {store} ({len(items)} exclusive, {curr_code}):')
            for i, item in enumerate(items[:5], 1):
                n = item['name'][:50] + '...' if len(item['name']) > 50 else item['name']
                print(f'     {i}. {n:<53} | {format_grade(item.get("grade")):<11} | {symbol}{item["price"]:>7,.2f}')
            if len(items) > 5:
                print(f'     ... +{len(items)-5} more')
            total_ex += len(items)
    
    print('\n PRICE COMPARISON:')
    comp = []
    for name, d in products.items():
        if len(d['stores']) > 1:
            prices = {s: info['price'] for s, info in d['stores'].items()}
            gap = max(prices.values()) - min(prices.values())
            if gap > 0:
                comp.append({'product': d['display_name'], 'stores': prices, 'gap': gap, 'best': min(prices, key=prices.get)})
    
    if comp:
        comp.sort(key=lambda x: x['gap'], reverse=True)
        avg = sum(r['gap'] for r in comp) / len(comp)
        print(f'\n SUMMARY:')
        print(f'   Unique: {len(products)}')
        print(f'   Exclusives: {total_ex}')
        print(f'   Comparable: {len(comp)}')
        print(f'   Avg gap: {symbols["PHP"]}{avg:,.2f}')
    else:
        print('  â„¹ All products are store-exclusive')
    
    print('\n' + '='*75 + '\n')
    return {'total': len(products), 'exclusives': total_ex, 'comparable': len(comp)}

def analyze_stores(results_file='test_results.json'):
    import json
    from collections import defaultdict
    
    with open(results_file) as f:
        data = json.load(f)
    
    all_names = defaultdict(list)
    
    for store_data in data['stores']:
        store_name = store_data['store_name']
        for item in store_data['products']:
            # CORRECT PATH: item['product']['product_name']
            name = item['product']['product_name'].split(' - ')[0].split(' (')[0]
            all_names[name].append(store_name)
    
    hp_only = [name for name, stores in all_names.items() if 'Hobby Planet' in stores and 'Hobby Link Japan' not in stores]
    hlj_only = [name for name, stores in all_names.items() if 'Hobby Link Japan' in stores and 'Hobby Planet' not in stores]
    both = [name for name, stores in all_names.items() if 'Hobby Planet' in stores and 'Hobby Link Japan' in stores]
    
    print("🆚 STORE EXCLUSIVES")
    print(f"HP ONLY ({len(hp_only)}): {hp_only[:5]}...")
    print(f"HLJ ONLY ({len(hlj_only)}): {hlj_only[:5]}...")
    print(f"BOTH ({len(both)}): {both[:3] if both else 'None'}")
    print(f"TOTAL UNIQUE: {len(all_names)}")


if __name__ == '__main__':
    analyze_stores()
# Add logging wrapper
import time
from app.logger import logger

if __name__ == "__main__":
    start = time.time()
    try:
        from . import analyze_stores  # Internal import
        results = analyze_stores("test_results.json")
        duration = int((time.time() - start) * 1000)
        metrics = {
            "total_products": len(results.get("products", {})),
            "exclusives": results.get("exclusives", 0),
            "comparable": results.get("comparable", 0),
            "avg_gap": getattr(results, "avg_gap", 0)
        }
        logger.log_run("comparison", "success", metrics, None, results, duration)
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        logger.log_run("comparison", "error", None, str(e), None, duration)
