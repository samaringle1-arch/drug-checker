import asyncio
import httpx

BASE = "https://rxnav.nlm.nih.gov/REST"

async def try_url(client, label, url):
    print(f"\n  [{label}]")
    print(f"  URL: {url}")
    try:
        r = await client.get(url, timeout=10)
        print(f"  Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  Keys: {list(data.keys())}")
            print(f"  SUCCESS - this endpoint works!")
            return True
        else:
            print(f"  Body: {r.text[:100]}")
    except Exception as e:
        print(f"  ERROR: {e}")
    return False

async def main():
    rxcui_para = "161"
    rxcui_asp  = "1191"

    async with httpx.AsyncClient() as client:

        print("=== Testing different RxNav endpoints ===")

        # Current approach - probably failing
        await try_url(client, "A - list with +",
            f"{BASE}/interaction/list.json?rxcuis={rxcui_para}+{rxcui_asp}")

        # Space encoded as %20
        await try_url(client, "B - list with %20",
            f"{BASE}/interaction/list.json?rxcuis={rxcui_para}%20{rxcui_asp}")

        # Single drug endpoint - most reliable
        await try_url(client, "C - single drug (para)",
            f"{BASE}/interaction/interaction.json?rxcui={rxcui_para}")

        # Single drug endpoint for aspirin
        await try_url(client, "D - single drug (aspirin)",
            f"{BASE}/interaction/interaction.json?rxcui={rxcui_asp}")

        # Different path structure
        await try_url(client, "E - no .json extension",
            f"{BASE}/interaction/list?rxcuis={rxcui_para}+{rxcui_asp}")

        # Try with sources param
        await try_url(client, "F - with sources param",
            f"{BASE}/interaction/list.json?rxcuis={rxcui_para}+{rxcui_asp}&sources=ONCHigh")

        # Try DrugBank source
        await try_url(client, "G - DrugBank source",
            f"{BASE}/interaction/list.json?rxcuis={rxcui_para}+{rxcui_asp}&sources=DrugBank")

asyncio.run(main())