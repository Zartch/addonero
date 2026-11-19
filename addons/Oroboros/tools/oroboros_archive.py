"""
Oroboros: archivo permanente de precios (docs/modelo-y-seguimiento.md, fase 1).

Única fuente de verdad de los precios, normalizada:
  markets       un mercado, una fila
  items         un producto, una fila (nombre, calidad, pila… y primera/última vez visto)
  scans         un escaneo, una fila (mercado, hora, completo o no)
  observations  escaneo × producto: min, mv, total, baratas, baratas con el umbral anterior
  daily         producto × día, para siempre (observaciones > histórico del juego > Auctionator)
  weekly_band   producto × semana ISO × franja: sumas de lo desaparecido, para siempre
  meta          versión del esquema

El addon guarda los últimos 12 escaneos en `OroborosDB.markets[mk].scans` como
`{t = epoch, data = "id,min,mv,qty,b,bp;..."}`; `append_scans` los añade aquí.
"""
import os
import shutil
import sqlite3

SCHEMA_VERSION = 2
KEEP_DAYS = 56          # escaneos en bruto: 8 semanas

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS markets (market_id INTEGER PRIMARY KEY, key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY, name TEXT, quality INTEGER, stack INTEGER, commodity INTEGER,
    ilvl INTEGER, vendor_sell INTEGER, vendor_buy REAL, first_seen INTEGER, last_seen INTEGER);
CREATE TABLE IF NOT EXISTS scans (
    scan_id INTEGER PRIMARY KEY, market_id INTEGER, t INTEGER, kind TEXT, n_items INTEGER,
    UNIQUE (market_id, t));
CREATE TABLE IF NOT EXISTS observations (
    scan_id INTEGER, item_id INTEGER,
    min REAL, mv REAL,          -- vacíos si el objeto se agotó
    qty INTEGER,                -- total publicado
    cheap INTEGER,              -- unidades a <= mínimo de este escaneo x 1,25
    cheap_prev INTEGER,         -- unidades a <= umbral barato del escaneo anterior
    PRIMARY KEY (scan_id, item_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS observations_item ON observations (item_id);
CREATE TABLE IF NOT EXISTS daily (
    market_id INTEGER, item_id INTEGER, day TEXT,
    min_low REAL, min_high REAL, mv REAL, qty_max INTEGER,
    src TEXT,                   -- obs (archivo) > oro (histórico del juego) > atr (Auctionator)
    t INTEGER,                  -- hora del último dato del día, si se conoce
    PRIMARY KEY (market_id, item_id, day)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS weekly_band (
    market_id INTEGER, item_id INTEGER, week TEXT, band INTEGER,
    gone_total REAL, gone_cheap REAL, hours REAL, n INTEGER, days INTEGER,
    price_med REAL, price_sum REAL, price_n INTEGER,
    PRIMARY KEY (market_id, item_id, week, band)) WITHOUT ROWID;
"""


# ----------------------------------------------------------------------
# Apertura y migración
# ----------------------------------------------------------------------
def _is_v1(path):
    if not os.path.exists(path):
        return False
    con = sqlite3.connect(path)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(scans)")]
        return "market" in cols and "item_id" in cols
    finally:
        con.close()


def open_archive(path):
    """Abre (o crea) el archivo con el esquema 2. Si es la tabla plana del 19/11, la migra
    dentro de una transacción y deja una copia `<archivo>.bak`."""
    migrate = _is_v1(path)
    if migrate:
        shutil.copy(path, path + ".bak")
    con = sqlite3.connect(path)
    if migrate:
        with con:
            con.execute("ALTER TABLE scans RENAME TO scans_v1")
            con.executescript(SCHEMA)
            for mk in [r[0] for r in con.execute("SELECT DISTINCT market FROM scans_v1")]:
                market_id(con, mk)
            con.execute("""INSERT INTO scans (market_id, t, kind, n_items)
                SELECT m.market_id, v.t, 'full', COUNT(*) FROM scans_v1 v JOIN markets m ON m.key = v.market
                GROUP BY m.market_id, v.t""")
            con.execute("""INSERT INTO observations
                SELECT s.scan_id, v.item_id, v.min, v.mv, v.qty, v.cheap, v.cheap_prev
                FROM scans_v1 v JOIN markets m ON m.key = v.market JOIN scans s ON s.market_id = m.market_id AND s.t = v.t""")
            con.execute("DROP TABLE scans_v1")
            con.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    else:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
        con.commit()
    return con


def market_id(con, key):
    con.execute("INSERT OR IGNORE INTO markets (key) VALUES (?)", (key,))
    return con.execute("SELECT market_id FROM markets WHERE key=?", (key,)).fetchone()[0]


# ----------------------------------------------------------------------
# Escaneos y productos
# ----------------------------------------------------------------------
def insert_scan(con, market, t, rows, kind="full"):
    """Añade un escaneo. rows: [(item_id, min, mv, qty, cheap, cheap_prev)].
    Devuelve False si ese escaneo (mercado y hora) ya estaba."""
    mid = market_id(con, market)
    if con.execute("SELECT 1 FROM scans WHERE market_id=? AND t=?", (mid, int(t))).fetchone():
        return False
    cur = con.execute("INSERT INTO scans (market_id, t, kind, n_items) VALUES (?,?,?,?)",
                      (mid, int(t), kind, len(rows)))
    sid = cur.lastrowid
    con.executemany("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?)",
                    [(sid, *r) for r in rows])
    return True


def _rows(data):
    for entry in (data or "").split(";"):
        f = entry.split(",") if entry else []
        if len(f) != 6:
            continue
        num = lambda x: float(x) if x else None
        yield (int(f[0]), num(f[1]), num(f[2]), int(f[3]), int(f[4]), int(f[5]))


def _as_list(x):
    if isinstance(x, dict):
        return [x[k] for k in sorted(x)]
    return list(x or [])


def _as_dict(x):
    if isinstance(x, list):
        return {i + 1: v for i, v in enumerate(x)}
    return x or {}


def upsert_items(con, db, seen):
    """Mantiene `items`: datos del catálogo del juego y primera/última vez visto en un escaneo.
    seen: {item_id: (primera_t, última_t)} de los escaneos añadidos ahora."""
    items, vendor = _as_dict(db.get("items")), _as_dict(db.get("vendor"))
    ids = {int(k) for k in items} | {int(k) for k in vendor} | set(seen)
    for i in ids:
        it = items.get(i) or items.get(str(i)) or {}
        first, last = seen.get(i, (None, None))
        c = it.get("c")
        con.execute("""INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (item_id) DO UPDATE SET
              name = COALESCE(excluded.name, name), quality = COALESCE(excluded.quality, quality),
              stack = COALESCE(excluded.stack, stack), commodity = COALESCE(excluded.commodity, commodity),
              ilvl = COALESCE(excluded.ilvl, ilvl), vendor_sell = COALESCE(excluded.vendor_sell, vendor_sell),
              vendor_buy = COALESCE(excluded.vendor_buy, vendor_buy),
              first_seen = MIN(COALESCE(first_seen, excluded.first_seen), COALESCE(excluded.first_seen, first_seen)),
              last_seen = MAX(COALESCE(last_seen, excluded.last_seen), COALESCE(excluded.last_seen, last_seen))""",
                    (i, it.get("n"), it.get("q"), it.get("st"), None if c is None else int(bool(c)),
                     it.get("il"), it.get("s"), vendor.get(i) or vendor.get(str(i)), first, last))


def append_scans(archive_path, db):
    """Añade los escaneos del buffer de OroborosDB (dict) al archivo.

    Devuelve {"added": filas nuevas, "already": filas que ya estaban, "scans": escaneos nuevos,
    "gap": True si con el buffer lleno ningún escaneo solapa con lo archivado (se perdieron)}.
    """
    con = open_archive(archive_path)
    added = already = new_scans = 0
    gap = False
    seen = {}
    markets = db.get("markets") or {}
    for market, m in (markets.items() if isinstance(markets, dict) else []):
        scans = [s for s in _as_list((m or {}).get("scans")) if isinstance(s, dict) and s.get("t")]
        if not scans:
            continue
        mid = market_id(con, market)
        last = con.execute("SELECT MAX(t) FROM scans WHERE market_id=?", (mid,)).fetchone()[0]
        if last is not None and len(scans) >= 12 and min(s["t"] for s in scans) > last:
            gap = True
        for s in scans:
            rows = list(_rows(s.get("data")))
            if insert_scan(con, market, s["t"], rows):
                added += len(rows)
                new_scans += 1
                for r in rows:
                    f, l = seen.get(r[0], (s["t"], s["t"]))
                    seen[r[0]] = (min(f, s["t"]), max(l, s["t"]))
            else:
                already += len(rows)
    upsert_items(con, db, seen)
    con.commit()
    con.close()
    return {"added": added, "already": already, "scans": new_scans, "gap": gap}
