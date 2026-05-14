"""
crypto_prices.py
Obtiene precios en tiempo real del top 50 cryptos en CLP.
Fuente principal: CoinGecko público (sin API key).
Fallback: Binance Public API para BTC/ETH/USDT.
Cache: 5 minutos via @st.cache_data.
"""
import sys
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")

import requests
import streamlit as st

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_URL   = "https://api.binance.com/api/v3/ticker/price"

# Top 50 fallback estático — se usa si la API no responde
# Formato: {coingecko_id: (symbol, nombre_display)}
TOP50_META = {
    "bitcoin":           ("BTC",  "Bitcoin"),
    "ethereum":          ("ETH",  "Ethereum"),
    "tether":            ("USDT", "Tether"),
    "binancecoin":       ("BNB",  "BNB"),
    "solana":            ("SOL",  "Solana"),
    "usd-coin":          ("USDC", "USD Coin"),
    "xrp":               ("XRP",  "XRP"),
    "dogecoin":          ("DOGE", "Dogecoin"),
    "toncoin":           ("TON",  "Toncoin"),
    "cardano":           ("ADA",  "Cardano"),
    "shiba-inu":         ("SHIB", "Shiba Inu"),
    "avalanche-2":       ("AVAX", "Avalanche"),
    "polkadot":          ("DOT",  "Polkadot"),
    "chainlink":         ("LINK", "Chainlink"),
    "tron":              ("TRX",  "TRON"),
    "bitcoin-cash":      ("BCH",  "Bitcoin Cash"),
    "near":              ("NEAR", "NEAR Protocol"),
    "matic-network":     ("MATIC","Polygon"),
    "litecoin":          ("LTC",  "Litecoin"),
    "internet-computer": ("ICP",  "Internet Computer"),
    "dai":               ("DAI",  "Dai"),
    "uniswap":           ("UNI",  "Uniswap"),
    "cosmos":            ("ATOM", "Cosmos"),
    "ethereum-classic":  ("ETC",  "Ethereum Classic"),
    "stellar":           ("XLM",  "Stellar"),
    "monero":            ("XMR",  "Monero"),
    "okb":               ("OKB",  "OKB"),
    "filecoin":          ("FIL",  "Filecoin"),
    "hedera-hashgraph":  ("HBAR", "Hedera"),
    "vechain":           ("VET",  "VeChain"),
    "algorand":          ("ALGO", "Algorand"),
    "the-sandbox":       ("SAND", "The Sandbox"),
    "decentraland":      ("MANA", "Decentraland"),
    "aave":              ("AAVE", "Aave"),
    "theta-token":       ("THETA","Theta Network"),
    "elrond-erd-2":      ("EGLD", "MultiversX"),
    "flow":              ("FLOW", "Flow"),
    "kucoin-shares":     ("KCS",  "KuCoin Token"),
    "eos":               ("EOS",  "EOS"),
    "neo":               ("NEO",  "NEO"),
    "quant-network":     ("QNT",  "Quant"),
    "chiliz":            ("CHZ",  "Chiliz"),
    "maker":             ("MKR",  "Maker"),
    "pancakeswap-token": ("CAKE", "PancakeSwap"),
    "curve-dao-token":   ("CRV",  "Curve DAO"),
    "injective-protocol":("INJ",  "Injective"),
    "aptos":             ("APT",  "Aptos"),
    "arbitrum":          ("ARB",  "Arbitrum"),
    "optimism":          ("OP",   "Optimism"),
    "sui":               ("SUI",  "Sui"),
}


@st.cache_data(ttl=300, show_spinner=False)
def get_top50_prices_clp() -> dict:
    """
    Retorna dict: {coingecko_id: {price_clp, price_usd, symbol, name, change_24h, ok}}
    Cache 5 minutos. En error devuelve precios vacíos con ok=False.
    """
    ids_param = ",".join(TOP50_META.keys())
    try:
        resp = requests.get(
            COINGECKO_URL,
            params={
                "vs_currency":           "clp",
                "ids":                   ids_param,
                "order":                 "market_cap_desc",
                "per_page":              50,
                "page":                  1,
                "sparkline":             False,
                "price_change_percentage": "24h",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        result = {}
        for coin in data:
            cid = coin["id"]
            result[cid] = {
                "price_clp":  coin.get("current_price", 0) or 0,
                "price_usd":  (coin.get("current_price", 0) or 0) / _get_usd_clp(),
                "symbol":     coin.get("symbol", "").upper(),
                "name":       coin.get("name", cid),
                "change_24h": coin.get("price_change_percentage_24h", 0) or 0,
                "ok":         True,
            }
        return result

    except Exception:
        return _fallback_binance()


def _get_usd_clp() -> float:
    """Obtiene USD/CLP desde mindicador.cl (ya usado en Dashboard)."""
    try:
        r = requests.get("https://mindicador.cl/api/dolar", timeout=4)
        return r.json()["serie"][0]["valor"]
    except Exception:
        return 920.0


def _fallback_binance() -> dict:
    """Fallback Binance para BTC, ETH, USDT cuando CoinGecko falla."""
    usd_clp = _get_usd_clp()
    result   = {}
    pairs    = {"bitcoin": "BTCUSDT", "ethereum": "ETHUSDT", "tether": "USDTUSDT"}
    for cid, pair in pairs.items():
        try:
            r = requests.get(BINANCE_URL, params={"symbol": pair}, timeout=5)
            price_usd = float(r.json()["price"])
            sym, name = TOP50_META[cid]
            result[cid] = {
                "price_clp":  price_usd * usd_clp,
                "price_usd":  price_usd,
                "symbol":     sym,
                "name":       name,
                "change_24h": 0.0,
                "ok":         True,
            }
        except Exception:
            pass
    return result


def buscar_coin(query: str, precios: dict) -> str | None:
    """
    Busca un coingecko_id dado un símbolo o nombre (case-insensitive).
    Ej: 'btc' → 'bitcoin' | 'usdt' → 'tether' | 'ethereum' → 'ethereum'
    """
    q = query.strip().lower()
    # Búsqueda directa por ID
    if q in precios:
        return q
    # Búsqueda por símbolo
    for cid, info in precios.items():
        if info["symbol"].lower() == q:
            return cid
    # Búsqueda por nombre parcial
    for cid, info in precios.items():
        if q in info["name"].lower():
            return cid
    # Fallback en metadatos estáticos
    for cid, (sym, nombre) in TOP50_META.items():
        if q == sym.lower() or q in nombre.lower():
            return cid
    return None
