import os
import shutil
from pathlib import Path

TEST_DATA = (Path(__file__).resolve().parent.parent / "work" / "backend-live-test-data").resolve()
if TEST_DATA.exists():
    shutil.rmtree(TEST_DATA)
os.environ["TRADING_AI_DATA_DIR"] = str(TEST_DATA)

from fastapi.testclient import TestClient
from backend.main import app


def assert_ok(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True, body
    return body["data"]


def test_complete_real_data_chain():
    with TestClient(app) as client:
        by_name = assert_ok(client.get("/api/market/stock/search", params={"q": "茅台"}))
        by_code = assert_ok(client.get("/api/market/stock/search", params={"q": "600519"}))
        assert by_name[0]["symbol"] == "600519" and by_code[0]["name"] == "贵州茅台"

        stock_quote = assert_ok(client.get("/api/market/stock/quote", params={"symbol": "600519"}))
        assert stock_quote["price"] > 0 and stock_quote["volume"] > 0 and stock_quote["source"]
        stock_kline = assert_ok(client.get("/api/market/stock/kline", params={"symbol": "600519", "interval": "1d", "limit": 300}))
        assert len(stock_kline["candles"]) >= 250 and stock_kline["indicators"]["latest"]["ma20"] is not None

        crypto_search = assert_ok(client.get("/api/market/crypto/search", params={"q": "BTC"}))
        assert crypto_search[0]["pair"] == "BTC/USDT"
        for symbol in ("BTC", "ETH"):
            quote = assert_ok(client.get("/api/market/crypto/quote", params={"symbol": symbol}))
            assert quote["price"] > 0 and quote["high"] >= quote["low"] and quote["source"]
        crypto_kline = assert_ok(client.get("/api/market/crypto/kline", params={"symbol": "BTC", "interval": "1h", "limit": 300}))
        assert len(crypto_kline["candles"]) >= 250 and crypto_kline["indicators"]["latest"]["rsi"] is not None

        prediction = assert_ok(client.post("/api/ai/predict", json={"symbol": "BTC", "asset_type": "crypto", "interval": "1h"}))
        assert prediction["model"]["name"] == "RandomForestClassifier" and prediction["model"]["walk_forward"] is True
        for horizon in ("1h", "4h", "1d"):
            p = prediction["predictions"][horizon]
            assert abs(p["prob_up"] + p["prob_flat"] + p["prob_down"] - 100) < 0.02
            assert p["walk_forward_samples"] > 0

        for strategy in ("ma", "macd", "rsi", "ai", "ai_technical"):
            result = assert_ok(client.post("/api/backtest/run", json={"symbol": "BTC", "asset_type": "crypto", "interval": "1h", "strategy": strategy, "initial_cash": 10000, "limit": 300}))
            assert result["initial_cash"] == 10000 and len(result["equity_curve"]) >= 250 and result["run_id"] > 0
        assert len(assert_ok(client.get("/api/backtest/history"))) == 5

        created = client.post("/api/watchlist", json={"symbol": "SOL", "name": "Solana", "asset_type": "crypto"})
        assert created.status_code == 201
        assert any(x["symbol"] == "SOL" for x in assert_ok(client.get("/api/watchlist")))
        assert_ok(client.delete("/api/watchlist/SOL"))

        buy = assert_ok(client.post("/api/paper/order", json={"symbol": "BTC", "asset_type": "crypto", "side": "BUY", "amount": 1000}))
        assert buy["price"] > 0 and buy["fee"] > 0
        positions = assert_ok(client.get("/api/paper/positions"))
        btc = next(x for x in positions if x["symbol"] == "BTC")
        assert btc["market_value"] > 0 and btc["current_price"] > 0
        sell = assert_ok(client.post("/api/paper/order", json={"symbol": "BTC", "asset_type": "crypto", "side": "SELL", "quantity": btc["quantity"]}))
        assert sell["side"] == "SELL"
        assert len(assert_ok(client.get("/api/paper/orders"))) == 2


def teardown_module():
    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA)

