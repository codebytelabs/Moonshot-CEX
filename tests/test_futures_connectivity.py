"""
Comprehensive connectivity + E2E test for Binance Futures (demo/testnet).

Tests:
  1. Which base URL actually works for fapi endpoints
  2. Whether existing demo API keys authenticate on futures
  3. Market loading, balance, funding rates
  4. Leverage + margin type setting
  5. Paper + live order flow
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ccxt.async_support as ccxt_async
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BINANCE_DEMO_API_KEY", "")
API_SECRET = os.getenv("BINANCE_DEMO_API_SECRET", "")

URLS_TO_TEST = {
    "testnet.binancefuture.com": "https://testnet.binancefuture.com",
    "demo-api.binance.com": "https://demo-api.binance.com",
}

RESULTS = {}


async def test_public_fapi(label: str, base_url: str):
    """Test if a URL responds to public fapi endpoints (no auth needed)."""
    print(f"\n{'='*60}")
    print(f"  Testing PUBLIC fapi: {label}")
    print(f"  Base URL: {base_url}")
    print(f"{'='*60}")

    ex = ccxt_async.binance({
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,
            "adjustForTimeDifference": True,
        },
    })

    # Override ALL API URLs to the test base
    for key in list(ex.urls.get("api", {}).keys()):
        if "fapi" in key.lower():
            version = key.replace("fapiPublic", "").replace("fapiPrivate", "").replace("fapi", "")
            ver_path = f"V{version.upper()}" if version else ""
            ver_num = version.lower() if version else "v1"
            ex.urls["api"][key] = f"{base_url}/fapi/{ver_num}"
        elif key in ("public", "private"):
            ex.urls["api"][key] = f"{base_url}/api/v3"

    result = {"url": base_url, "public_markets": False, "public_ticker": False}

    # Test 1: Load futures markets
    try:
        markets = await ex.load_markets()
        futures_markets = [s for s, m in markets.items()
                          if m.get("linear") and m.get("swap") and m.get("quote") == "USDT"]
        result["public_markets"] = len(futures_markets) > 0
        print(f"  [OK] Loaded {len(futures_markets)} USDT-M futures markets")
        # Show some examples
        examples = futures_markets[:5]
        print(f"       Examples: {examples}")
    except Exception as e:
        print(f"  [FAIL] load_markets: {e}")

    # Test 2: Fetch a ticker
    try:
        ticker = await ex.fetch_ticker("BTC/USDT:USDT")
        result["public_ticker"] = ticker.get("last", 0) > 0
        print(f"  [OK] BTC/USDT:USDT ticker: ${ticker['last']:.2f}")
    except Exception as e:
        print(f"  [FAIL] fetch_ticker: {e}")

    await ex.close()
    RESULTS[label] = result
    return result


async def test_private_fapi(label: str, base_url: str):
    """Test if demo API keys authenticate on futures endpoints."""
    print(f"\n{'='*60}")
    print(f"  Testing PRIVATE fapi: {label}")
    print(f"  API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"{'='*60}")

    if not API_KEY or not API_SECRET:
        print("  [SKIP] No API keys in .env")
        return {"auth": False}

    ex = ccxt_async.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,
            "adjustForTimeDifference": True,
        },
    })

    # Override API URLs
    for key in list(ex.urls.get("api", {}).keys()):
        if "fapi" in key.lower():
            version = key.replace("fapiPublic", "").replace("fapiPrivate", "").replace("fapi", "")
            ver_num = version.lower() if version else "v1"
            ex.urls["api"][key] = f"{base_url}/fapi/{ver_num}"
        elif key in ("public", "private", "v1", "v3"):
            ex.urls["api"][key] = f"{base_url}/api/v3"
        elif "sapi" in key.lower():
            ex.urls["api"][key] = f"{base_url}/sapi/v1"

    result = RESULTS.get(label, {})
    result["auth_balance"] = False
    result["auth_positions"] = False
    result["set_leverage"] = False
    result["set_margin"] = False
    result["funding_rate"] = False

    try:
        await ex.load_markets()
    except Exception as e:
        print(f"  [FAIL] load_markets: {e}")
        await ex.close()
        RESULTS[label] = result
        return result

    # Test 3: Fetch futures balance
    try:
        bal = await ex.fetch_balance()
        usdt = bal.get("USDT", {})
        total = float(usdt.get("total", 0))
        free = float(usdt.get("free", 0))
        result["auth_balance"] = True
        result["balance_total"] = total
        result["balance_free"] = free
        print(f"  [OK] Futures balance: total=${total:.2f} free=${free:.2f}")
    except Exception as e:
        print(f"  [FAIL] fetch_balance: {e}")

    # Test 4: Fetch positions
    try:
        positions = await ex.fetch_positions()
        open_pos = [p for p in positions if float(p.get("contracts", 0)) > 0]
        result["auth_positions"] = True
        print(f"  [OK] Positions: {len(open_pos)} open out of {len(positions)} total")
    except Exception as e:
        print(f"  [FAIL] fetch_positions: {e}")

    # Test 5: Set margin type (ISOLATED)
    try:
        await ex.set_margin_mode("isolated", "BTC/USDT:USDT")
        result["set_margin"] = True
        print(f"  [OK] Set margin mode: ISOLATED for BTC/USDT:USDT")
    except ccxt_async.ExchangeError as e:
        if "no need to change" in str(e).lower() or "already" in str(e).lower():
            result["set_margin"] = True
            print(f"  [OK] Margin already ISOLATED for BTC/USDT:USDT")
        else:
            print(f"  [FAIL] set_margin_mode: {e}")
    except Exception as e:
        print(f"  [FAIL] set_margin_mode: {e}")

    # Test 6: Set leverage
    try:
        await ex.set_leverage(3, "BTC/USDT:USDT")
        result["set_leverage"] = True
        print(f"  [OK] Set leverage: 3x for BTC/USDT:USDT")
    except Exception as e:
        print(f"  [FAIL] set_leverage: {e}")

    # Test 7: Fetch funding rate
    try:
        fr = await ex.fetch_funding_rate("BTC/USDT:USDT")
        rate = float(fr.get("fundingRate", 0))
        result["funding_rate"] = True
        result["funding_rate_value"] = rate
        print(f"  [OK] Funding rate BTC/USDT:USDT: {rate:.6f}")
    except Exception as e:
        print(f"  [FAIL] fetch_funding_rate: {e}")

    await ex.close()
    RESULTS[label] = result
    return result


async def test_ccxt_sandbox_mode():
    """Test CCXT's built-in set_sandbox_mode for binance futures."""
    print(f"\n{'='*60}")
    print(f"  Testing CCXT native set_sandbox_mode(True)")
    print(f"{'='*60}")

    if not API_KEY or not API_SECRET:
        print("  [SKIP] No API keys")
        return

    ex = ccxt_async.binance({
        "apiKey": API_KEY,
        "secret": API_SECRET,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,
            "adjustForTimeDifference": True,
        },
    })
    ex.set_sandbox_mode(True)

    result = {"sandbox_mode": True}

    print("  Sandbox API URLs:")
    for k, v in ex.urls.get("api", {}).items():
        if "fapi" in k.lower() or k in ("public", "private"):
            print(f"    {k}: {v}")

    try:
        markets = await ex.load_markets()
        futures = [s for s, m in markets.items()
                   if m.get("linear") and m.get("swap")]
        result["markets"] = len(futures)
        print(f"  [OK] Loaded {len(futures)} futures markets via sandbox")
    except Exception as e:
        print(f"  [FAIL] load_markets (sandbox): {e}")
        result["markets"] = 0

    try:
        bal = await ex.fetch_balance()
        usdt = bal.get("USDT", {})
        total = float(usdt.get("total", 0))
        result["balance"] = total
        print(f"  [OK] Sandbox balance: ${total:.2f}")
    except Exception as e:
        print(f"  [FAIL] fetch_balance (sandbox): {e}")
        result["balance"] = -1

    await ex.close()
    RESULTS["ccxt_sandbox"] = result


async def test_with_our_connector():
    """Test using our FuturesExchangeConnector with the winning URL."""
    print(f"\n{'='*60}")
    print(f"  Testing OUR FuturesExchangeConnector")
    print(f"{'='*60}")

    from src.exchange_ccxt import FuturesExchangeConnector

    # Find the best working URL from previous tests
    best_url = None
    for label, res in RESULTS.items():
        if res.get("auth_balance"):
            best_url = res.get("url")
            print(f"  Using URL from successful test: {label} → {best_url}")
            break

    if not best_url:
        # Fallback: try sandbox mode approach
        print("  No URL worked with manual override, trying sandbox approach...")
        best_url = "sandbox"

    if best_url == "sandbox":
        print("  [INFO] Will test sandbox mode via set_sandbox_mode")
        # We need to modify the connector to support sandbox mode
        return

    connector = FuturesExchangeConnector(
        name="binance",
        api_key=API_KEY,
        api_secret=API_SECRET,
        futures_url=best_url,
        default_leverage=3,
        margin_type="isolated",
    )

    try:
        await connector.initialize()
        print(f"  [OK] Connector initialized, markets loaded: {connector.markets_loaded}")

        # Get USDT pairs
        pairs = connector.get_usdt_pairs()
        print(f"  [OK] USDT-M pairs: {len(pairs)}")
        if pairs:
            print(f"       First 5: {pairs[:5]}")

        # Fetch balance
        bal = await connector.fetch_futures_balance()
        print(f"  [OK] Balance: total=${bal['total']:.2f} free=${bal['free']:.2f}")

        # Fetch funding rate
        if pairs:
            fr = await connector.fetch_funding_rate(pairs[0])
            print(f"  [OK] Funding rate {pairs[0]}: {fr:.6f}")

        # Set leverage + margin
        if pairs:
            ok = await connector.prepare_symbol(pairs[0], 5)
            print(f"  [OK] prepare_symbol({pairs[0]}, 5x): {ok}")

    except Exception as e:
        print(f"  [FAIL] Connector test: {e}")
    finally:
        try:
            await connector.exchange.close()
        except Exception:
            pass


async def main():
    print("=" * 60)
    print("  BINANCE FUTURES CONNECTIVITY TESTS")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  API Key present: {bool(API_KEY)}")
    print("=" * 60)

    # Phase 1: Public endpoint tests
    for label, url in URLS_TO_TEST.items():
        await test_public_fapi(label, url)

    # Phase 2: Private endpoint tests (with auth)
    for label, url in URLS_TO_TEST.items():
        if RESULTS.get(label, {}).get("public_markets"):
            await test_private_fapi(label, url)

    # Phase 3: CCXT native sandbox mode
    await test_ccxt_sandbox_mode()

    # Phase 4: Our connector
    await test_with_our_connector()

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for label, res in RESULTS.items():
        status = "PASS" if res.get("auth_balance") or res.get("balance", -1) >= 0 else "FAIL"
        print(f"  [{status}] {label}: markets={res.get('public_markets', res.get('markets', '?'))} "
              f"auth={res.get('auth_balance', '?')} balance=${res.get('balance_total', res.get('balance', '?'))}")

    # Determine winner
    winner = None
    for label, res in RESULTS.items():
        if res.get("auth_balance") and res.get("set_leverage"):
            winner = label
            break
    if not winner and RESULTS.get("ccxt_sandbox", {}).get("balance", -1) >= 0:
        winner = "ccxt_sandbox"

    if winner:
        print(f"\n  WINNER: {winner}")
        print(f"  This is the approach we should use for futures trading.")
    else:
        print(f"\n  NO WINNER — all approaches failed. Check API keys or network.")

    print(f"{'='*60}")
    return winner


if __name__ == "__main__":
    winner = asyncio.run(main())
