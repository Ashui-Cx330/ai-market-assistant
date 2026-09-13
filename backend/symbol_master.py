"""Canonical asset identity shared by prediction, settlement and research."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from .database import connection
from .market import canonical_symbol, normalize_crypto, normalize_stock_symbol
from .symbol_registry import search as registry_search


@dataclass(frozen=True)
class SymbolIdentity:
    canonical_symbol: str
    market: str
    exchange: str
    asset_type: str
    display_name: str
    currency: str
    timezone: str
    session: str
    provider_symbol: str
    active: bool = True
    delisted: bool = False
    sector: str | None = None
    industry: str | None = None
    aliases: str = ""
    source: str = "deterministic identity rules"

    def payload(self) -> dict:
        return asdict(self)


def _identity(symbol: str, asset_type: str, name: str | None = None) -> SymbolIdentity:
    if asset_type == "crypto":
        base = normalize_crypto(symbol)
        return SymbolIdentity(base, "CRYPTO", "OKX", "crypto", name or base, "USDT", "UTC",
                              "24x7", f"{base}-USDT", aliases=f"{base}USDT|{base}/USDT|{base}-USDT")
    value = canonical_symbol(symbol, "stock")
    raw = normalize_stock_symbol(value)
    if raw.isdigit():
        exchange = "SSE" if value.endswith(".SH") else "SZSE"
        return SymbolIdentity(value, "CN", exchange, "stock", name or raw, "CNY", "Asia/Shanghai",
                              "09:30-11:30,13:00-15:00", raw,
                              aliases=f"{raw}|{raw}.{'SS' if exchange == 'SSE' else 'SZ'}")
    return SymbolIdentity(raw, "US", "US", "stock", name or raw, "USD", "America/New_York",
                          "09:30-16:00 America/New_York", raw,
                          aliases=f"{raw}|NASDAQ:{raw}|NYSE:{raw}")


def resolve(value: str, asset_type: str | None = None) -> SymbolIdentity:
    raw = value.strip()
    inferred = asset_type
    if inferred is None:
        compact = raw.upper().replace("/", "").replace("-", "")
        inferred = "crypto" if compact.endswith("USDT") else "stock"
    matches = registry_search(raw, inferred, 5)
    exact = matches[0] if matches else None
    symbol = exact["symbol"] if exact else raw
    identity = _identity(symbol, inferred, exact.get("name") if exact else None)
    if exact:
        identity = SymbolIdentity(**{**identity.payload(), "exchange": exact.get("exchange") or identity.exchange,
                                     "display_name": exact.get("name") or identity.display_name,
                                     "source": exact.get("source") or identity.source})
    persist(identity)
    return identity


def persist(identity: SymbolIdentity) -> None:
    row = identity.payload()
    with connection() as conn:
        conn.execute("""INSERT INTO symbol_master(canonical_symbol,market,exchange,asset_type,display_name,
            currency,timezone,session,provider_symbol,aliases,active,delisted,sector,industry,source,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(canonical_symbol,market) DO UPDATE SET
            display_name=excluded.display_name,provider_symbol=excluded.provider_symbol,aliases=excluded.aliases,
            active=excluded.active,delisted=excluded.delisted,sector=COALESCE(excluded.sector,symbol_master.sector),
            industry=COALESCE(excluded.industry,symbol_master.industry),source=excluded.source,updated_at=excluded.updated_at""",
            (row["canonical_symbol"], row["market"], row["exchange"], row["asset_type"], row["display_name"],
             row["currency"], row["timezone"], row["session"], row["provider_symbol"], row["aliases"],
             int(row["active"]), int(row["delisted"]), row["sector"], row["industry"], row["source"],
             datetime.now(timezone.utc).isoformat()))


def alias_search(query: str, asset_type: str | None = None, limit: int = 20) -> list[dict]:
    kinds = [asset_type] if asset_type else ["stock", "crypto"]
    rows: list[dict] = []
    for kind in kinds:
        for match in registry_search(query, kind, limit):
            identity = _identity(match["symbol"], kind, match.get("name"))
            rows.append(identity.payload())
    seen = set()
    return [row for row in rows if not ((row["canonical_symbol"], row["market"]) in seen or
            seen.add((row["canonical_symbol"], row["market"])))] [:limit]
