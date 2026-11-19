"""
Oroboros: lee la base de precios de Auctionator (SavedVariables/Auctionator.lua) como
segunda fuente de precios. Solo lectura; sin dependencias externas.

Formato (comprobado en Auctionator 341, ver docs/fuentes-de-precios.md):
  AUCTIONATOR_PRICE_DATABASE = { __dbversion = 8, [<clave de mercado>] = <tabla o cadena CBOR> }
  por objeto: m = último mínimo; h[día] = mínimo más alto del día; l[día] = mínimo más bajo
  (solo si difiere de h); a[día] = mayor cantidad publicada vista ese día.
  día = días desde el 1/1/2020 (hora local).
Al salir del juego Auctionator guarda el mercado actual como cadena CBOR.
"""
import datetime
import struct

DAY0 = datetime.date(2020, 1, 1)


# ----------------------------------------------------------------------
# CBOR (RFC 8949): solo lo que usa Auctionator
# ----------------------------------------------------------------------
def cbor_decode(data):
    value, end = _cbor(data, 0)
    if end != len(data):
        raise ValueError(f"CBOR: sobran {len(data) - end} bytes")
    return value


def _cbor(b, i):
    ib = b[i]
    major, info = ib >> 5, ib & 31
    i += 1
    if major == 7:
        simple = {20: False, 21: True, 22: None, 23: None}
        if info in simple:
            return simple[info], i
        fmt = {25: (">e", 2), 26: (">f", 4), 27: (">d", 8)}.get(info)
        if not fmt:
            raise ValueError(f"CBOR: valor simple {info} no soportado")
        return struct.unpack(fmt[0], b[i:i + fmt[1]])[0], i + fmt[1]
    if info < 24:
        n = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        n = int.from_bytes(b[i:i + size], "big")
        i += size
    elif info == 31:
        n = None                                    # longitud indefinida
    else:
        raise ValueError(f"CBOR: longitud {info} no válida")
    if major == 0:
        return n, i
    if major == 1:
        return -1 - n, i
    if major in (2, 3):
        s = b[i:i + n]
        return s.decode("utf-8", "replace"), i + n
    if major == 4:
        out = []
        while (n is None and b[i] != 0xFF) or (n is not None and len(out) < n):
            v, i = _cbor(b, i)
            out.append(v)
        return out, (i + 1 if n is None else i)
    if major == 5:
        out, k = {}, 0
        while (n is None and b[i] != 0xFF) or (n is not None and k < n):
            key, i = _cbor(b, i)
            out[key], i = _cbor(b, i)
            k += 1
        return out, (i + 1 if n is None else i)
    if major == 6:                                  # etiqueta: se ignora
        return _cbor(b, i)
    raise ValueError(f"CBOR: tipo {major}")


def cbor_encode(v):
    """Codificador mínimo (para las pruebas)."""
    def head(major, n):
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
    if v is None:
        return b"\xf6"
    if isinstance(v, bool):
        return b"\xf5" if v else b"\xf4"
    if isinstance(v, int):
        return head(0, v) if v >= 0 else head(1, -1 - v)
    if isinstance(v, float):
        return b"\xfb" + struct.pack(">d", v)
    if isinstance(v, str):
        e = v.encode("utf-8")
        return head(3, len(e)) + e
    if isinstance(v, (list, tuple)):
        return head(4, len(v)) + b"".join(cbor_encode(x) for x in v)
    if isinstance(v, dict):
        return head(5, len(v)) + b"".join(cbor_encode(k) + cbor_encode(x) for k, x in v.items())
    raise TypeError(type(v))


# ----------------------------------------------------------------------
# Lectura del SavedVariables
# ----------------------------------------------------------------------
def day_to_date(day):
    return (DAY0 + datetime.timedelta(days=int(day))).isoformat()


def load(path):
    """Devuelve {"markets": {clave: {itemID: registro}}, "last_scan": epoch o None}."""
    from oroboros_export import LuaParser
    # latin-1 conserva cada byte tal cual: la base viene en una cadena binaria
    with open(path, encoding="latin-1") as fh:
        sv = LuaParser(fh.read(), binary=True).assignments()
    db = sv.get("AUCTIONATOR_PRICE_DATABASE") or {}
    markets = {}
    for key, raw in db.items():
        if key == "__dbversion":
            continue
        if isinstance(raw, str):
            raw = cbor_decode(raw.encode("latin-1"))
        if not isinstance(raw, dict):
            continue
        items = {}
        for item_key, rec in raw.items():
            # "g:id:nivel" (equipo por nivel) y "p:especie" (mascotas) no los usa Oroboros
            if not isinstance(rec, dict) or not str(item_key).isdigit():
                continue
            if isinstance(rec.get("old"), dict) and rec.get("pending"):
                rec = rec["old"]
            items[int(item_key)] = {
                "m": rec.get("m"),
                "h": _days(rec.get("h")), "l": _days(rec.get("l")), "a": _days(rec.get("a")),
            }
        markets[str(key)] = items
    state = sv.get("AUCTIONATOR_SAVEDVARS") or {}
    times = [t for t in (state.get("TimeOfLastReplicateScan"), state.get("TimeOfLastBrowseScan"))
             if isinstance(t, (int, float))]
    return {"markets": markets, "last_scan": int(max(times)) if times else None}


def _days(t):
    """{día (número o texto) → valor} → {"AAAA-MM-DD" → valor}."""
    if isinstance(t, list):                         # el parser convierte claves 1..n en lista
        t = {i + 1: v for i, v in enumerate(t)}
    out = {}
    for k, v in (t or {}).items():
        if str(k).lstrip("-").isdigit() and isinstance(v, (int, float)):
            out[day_to_date(k)] = v
    return out


def pick_market(markets):
    """Si hay varios mercados, el que tenga el día más reciente."""
    if not markets:
        return None
    def latest(items):
        return max((d for r in items.values() for d in r["h"]), default="")
    return max(markets, key=lambda k: (latest(markets[k]), len(markets[k])))


# ----------------------------------------------------------------------
# Mezcla en el SQLite de Oroboros
# ----------------------------------------------------------------------
def merge(con, atr, market, today=None):
    """Añade los datos de Auctionator al mercado `market` del SQLite.

    Gana Oroboros cuando tiene dato del mismo día (trae profundidad y valor de mercado);
    Auctionator rellena los días y objetos que falten y el precio actual si es más reciente.
    Devuelve (precios, días de histórico) añadidos o sustituidos.
    """
    key = pick_market(atr["markets"])
    if key is None:
        return 0, 0
    items = atr["markets"][key]
    have_hist = {(r[0], r[1]) for r in con.execute(
        "SELECT item_id, day FROM history WHERE market=?", (market,))}
    have_price = {r[0]: r[1] for r in con.execute(
        "SELECT item_id, t FROM prices WHERE market=?", (market,))}
    n_hist = n_price = 0
    for item_id, rec in items.items():
        con.execute("INSERT OR IGNORE INTO items (item_id) VALUES (?)", (item_id,))
        for day, high in rec["h"].items():
            if (item_id, day) in have_hist:
                continue
            low = rec["l"].get(day, high)
            con.execute("INSERT INTO history VALUES (?,?,?,?,?,?,?,?)",
                        (market, item_id, day, low, high, rec["a"].get(day), "atr", None))
            n_hist += 1
        if not rec["m"] or not rec["h"]:
            continue
        last = max(rec["h"])
        t = _day_ts(last, atr["last_scan"])
        old_t = have_price.get(item_id)
        if old_t is not None and _ts_day(old_t) >= last:
            continue                                # el de Oroboros es del mismo día o más nuevo
        con.execute("INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (market, item_id, rec["m"], rec["m"], rec["a"].get(last), None, t,
                     None, None, None, None, "atr"))
        n_price += 1
    con.commit()
    return n_price, n_hist


def _ts_day(t):
    return datetime.datetime.fromtimestamp(t).date().isoformat()


def _day_ts(day, last_scan):
    """Hora del dato: la del último escaneo si cae ese día; si no, mediodía de ese día."""
    if last_scan and _ts_day(last_scan) == day:
        return last_scan
    d = datetime.date.fromisoformat(day)
    return int(datetime.datetime(d.year, d.month, d.day, 12).timestamp())


# ----------------------------------------------------------------------
# Archivo permanente (esquema 2): Auctionator solo entra en el histórico diario
# ----------------------------------------------------------------------
def to_daily(con, atr, market):
    """Mete la base de Auctionator en `daily` del archivo como 'atr', sin pisar 'obs' ni 'oro'.
    Devuelve los días añadidos."""
    from oroboros_archive import market_id
    key = pick_market(atr["markets"])
    if key is None:
        return 0
    mid = market_id(con, market)
    n = 0
    for item_id, rec in atr["markets"][key].items():
        for day, high in rec["h"].items():
            cur = con.execute("INSERT OR IGNORE INTO daily VALUES (?,?,?,?,?,?,?,'atr',NULL)",
                              (mid, item_id, day, rec["l"].get(day, high), high, high, rec["a"].get(day)))
            n += cur.rowcount
    con.commit()
    return n
