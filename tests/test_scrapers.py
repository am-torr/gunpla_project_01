import sys
from pathlib import Path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message="urllib3")

import asyncio
asyncio.get_event_loop_policy().get_event_loop().set_debug(True)  # Async debug

import json
from app.comparison import analyze_stores
from datetime import datetime


print("=" * 70)
print("GUNPLA TRACKER - TESTS")
print("=" * 70)

scraped_data = {
    "hobby_planet": [],
    "hobby_link_japan": []
}

def test_import():
    print("\nTest 1: Import...")
    try:
        from app.scrapers.hobby_planet import HobbyPlanetScraper
        from app.scrapers.hobby_link_japan import HobbyLinkJapanScraper
        print(" ✅ PASS")
        return True
    except Exception as e:
        print(f" ❌ FAIL: {e}")
        return False

def test_init():
    print("\nTest 2: Initialize...")
    try:
        from app.scrapers.hobby_planet import HobbyPlanetScraper
        s = HobbyPlanetScraper()
        print(f" ✅ PASS: {s.store_name}")
        return True
    except Exception as e:
        print(f" ❌ FAIL: {e}")
        return False

async def test_scrape():
    print("\nTest 3: Scrape 5 products from Hobby Planet...")
    try:
        from app.scrapers.hobby_planet import HobbyPlanetScraper
        s = HobbyPlanetScraper()
        p = await s.scrape(limit=5)
        
        scraped_data["hobby_planet"] = p
        
        print(f" ✅ PASS: Scraped {len(p)} products\n")
        for i, x in enumerate(p[:3], 1):
            prod = x["product"]
            price = x["price"]
            # Handle both snake_case and camelCase
            name = prod.get("product_name") or prod.get("productName", "Unknown")
            grade = prod.get("grade", "N/A")
            price_val = price.get("price")
            price_str = f"{price_val:,.2f}" if price_val else "N/A"
            stock = price.get("stock_status") or price.get("stockStatus", "Unknown")
            
            print(f"[{i}] {name}")
            print(f"    {grade} | {price_str} | {stock}\n")
        
        return len(p) > 0
    except Exception as e:
        print(f" ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_hlj_scrape():
    print("Test 4: Scrape 5 products from HLJ...")
    try:
        from app.scrapers.hobby_link_japan import HobbyLinkJapanScraper
        s = HobbyLinkJapanScraper()
        p = await s.scrape(limit=5)
        
        scraped_data["hobby_link_japan"] = p
        
        print(f" ✅ PASS: Scraped {len(p)} products from HLJ\n")
        for i, x in enumerate(p[:3], 1):
            prod = x["product"]
            price = x["price"]
            # Handle both snake_case and camelCase
            name = prod.get("product_name") or prod.get("productName", "Unknown")
            grade = prod.get("grade", "Unknown")
            price_val = price.get("price")
            price_str = f"{price_val:,.0f}" if price_val else "N/A"
            stock = price.get("stock_status") or price.get("stockStatus", "Unknown")
            
            print(f"[{i}] {name[:50]}")
            print(f"    {grade} | {price_str} | {stock}\n")
        
        return len(p) > 0
    except Exception as e:
        print(f" ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_comparison():
    """Test 5: Store comparison analysis"""
    print("\nTest 5: Store Comparison Analysis...")
    try:
        from app.comparison import analyze_stores
        
        # Check if test_results.json exists
        if not Path("test_results.json").exists():
            print(" ⚠️  SKIP: No test_results.json found (scraper tests must run first)")
            return True  # Don't fail, just skip
        
        print()  # Blank line before comparison output
        analyze_stores("test_results.json")
        print(" ✅ PASS: Comparison analysis complete")
        return True
    except Exception as e:
        print(f" ❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    r = [
        test_import(),
        test_init(),
        await test_scrape(),
        await test_hlj_scrape()
    ]
    
    # Save results first
    print("\n 💾 Saving combined test results...")
    try:
        output = {
            "test_date": datetime.now().isoformat(),
            "stores": [
                {
                    "store_name": "Hobby Planet",
                    "products_scraped": len(scraped_data["hobby_planet"]),
                    "products": scraped_data["hobby_planet"]
                },
                {
                    "store_name": "Hobby Link Japan",
                    "products_scraped": len(scraped_data["hobby_link_japan"]),
                    "products": scraped_data["hobby_link_japan"]
                }
            ]
        }
        
        with open("test_results.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(" ✅ Saved: test_results.json")
    except Exception as e:
        print(f" ❌ Could not save results: {e}")
    
    # Now run comparison test
    r.append(test_comparison())
    
    passed = sum(r)
    
    print("\n" + "=" * 70)
    print(f"RESULT: {passed}/{len(r)} tests passed")
    print("=" * 70)
    
    if passed == len(r):
        print(" ✅ ALL TESTS PASSED!")
        return 0
    else:
        print(f" ⚠️  {len(r) - passed} tests failed")
        return 1

    print("\n🆚 Test 5: Store Comparison Analysis...")
    analyze_stores('test_results.json')  # Prints full report/table
    print(" ✅ PASS")

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

