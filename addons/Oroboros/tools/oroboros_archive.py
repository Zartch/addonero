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
CREATE TABLE IF NOT EXISTS farm_mobs (          -- farmeo medido en el juego: totales por criatura y subzona
    market_id INTEGER, npc INTEGER, sub TEXT, zone TEXT, map INTEGER,
    kills INTEGER, copper INTEGER, secs INTEGER, items TEXT,      -- items: JSON {itemID: cantidad}
    PRIMARY KEY (market_id, npc, sub)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS farm_gather (
    market_id INTEGER, sub TEXT, zone TEXT, map INTEGER, nodes INTEGER, items TEXT,
    PRIMARY KEY (market_id, sub)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS farm_npcs (npc INTEGER PRIMARY KEY, name TEXT, lvl INTEGER, cls TEXT);
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


# ----------------------------------------------------------------------
# Histórico diario (para siempre)
# ----------------------------------------------------------------------
def _day(t):
    import datetime
    return datetime.datetime.fromtimestamp(t).date().isoformat()


def update_daily(con, db=None):
    """Recalcula `daily` desde las observaciones (src 'obs') y añade el histórico diario del juego
    (src 'oro') donde no haya observación. Auctionator ('atr') entra con auctionator_source.to_daily."""
    rows = con.execute("""SELECT s.market_id, o.item_id, s.t, o.min, o.mv, o.qty
                          FROM observations o JOIN scans s USING (scan_id)
                          ORDER BY s.market_id, o.item_id, s.t""")
    acc = {}
    for mid, item, t, mn, mv, qty in rows:
        k = (mid, item, _day(t))
        a = acc.get(k)
        if a is None:
            a = acc[k] = {"low": None, "high": None, "mv": None, "qty": 0, "t": t}
        if mn is not None:
            a["low"] = mn if a["low"] is None else min(a["low"], mn)
            a["high"] = mn if a["high"] is None else max(a["high"], mn)
        if mv is not None:
            a["mv"] = mv
        a["qty"] = max(a["qty"], qty or 0)
        a["t"] = t
    con.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?,'obs',?)",
                    [(m, i, d, a["low"], a["high"], a["mv"], a["qty"], a["t"]) for (m, i, d), a in acc.items()])
    for market, m in (_as_dict((db or {}).get("markets")).items()):
        mid = market_id(con, market)
        for item, days in _as_dict((m or {}).get("history")).items():
            for day, h in _as_dict(days).items():
                if not isinstance(h, dict):
                    continue
                cur = con.execute("SELECT src FROM daily WHERE market_id=? AND item_id=? AND day=?",
                                  (mid, int(item), day)).fetchone()
                if cur and cur[0] == "obs":
                    continue
                con.execute("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?,'oro',?)",
                            (mid, int(item), day, h.get("min"), h.get("min"), h.get("mv"), h.get("qty"), h.get("t")))
    con.commit()


# ----------------------------------------------------------------------
# Resumen semanal y retención de los escaneos en bruto
# ----------------------------------------------------------------------
def _week_end_ts(week):
    import datetime
    y, w = week.split("-W")
    last = datetime.date.fromisocalendar(int(y), int(w), 7)
    return int(datetime.datetime.combine(last, datetime.time(23, 59, 59)).timestamp())


def rollup(con, now, keep_days=KEEP_DAYS):
    """Resume en `weekly_band` las semanas ISO completas anteriores a now − keep_days y borra sus
    escaneos en bruto. Antes recalcula `daily` para no perder esos días. Devuelve los escaneos borrados.
    Un intervalo cuenta en la semana de su escaneo inicial; el precio, en la semana del escaneo."""
    import statistics
    from oroboros_hours import contributions, week_of, OBS_SQL
    cutoff = now - keep_days * 86400
    old = con.execute("SELECT scan_id, market_id, t FROM scans WHERE t < ?", (cutoff,)).fetchall()
    weeks = {(mid, week_of(t)) for _, mid, t in old if _week_end_ts(week_of(t)) < cutoff}
    if not weeks:
        return 0
    update_daily(con)
    for mid in {m for m, _ in weeks}:
        key = con.execute("SELECT key FROM markets WHERE market_id=?", (mid,)).fetchone()[0]
        mine = {w for m, w in weeks if m == mid}
        agg = {}
        for c in contributions(con.execute(OBS_SQL, (key,))):
            if c[2] not in mine:
                continue
            a = agg.setdefault((c[1], c[2], c[3]), {"gt": 0.0, "gc": 0.0, "secs": 0.0, "n": 0, "days": set(), "prices": []})
            if c[0] == "price":
                a["prices"].append(c[4])
            else:
                a["gt"] += c[4]; a["gc"] += c[5]; a["secs"] += c[6]; a["n"] += 1; a["days"].add(c[7])
        con.executemany("INSERT OR REPLACE INTO weekly_band VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
            (mid, item, wk, band, a["gt"], a["gc"], a["secs"] / 3600, a["n"], len(a["days"]),
             statistics.median(a["prices"]) if a["prices"] else None, sum(a["prices"]), len(a["prices"]))
            for (item, wk, band), a in agg.items()])
    ids = [sid for sid, mid, t in old if (mid, week_of(t)) in weeks]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        con.execute(f"DELETE FROM observations WHERE scan_id IN ({marks})", chunk)
        con.execute(f"DELETE FROM scans WHERE scan_id IN ({marks})", chunk)
    con.commit()
    return len(ids)


# ----------------------------------------------------------------------
# Del archivo al SQLite del plan
# ----------------------------------------------------------------------
def plan_from_archive(con, plan_path):
    """El histórico del plan sale de `daily`; los precios, de Oroboros.lua (traen profundidad), y los
    objetos sin precio en el juego se completan con su último día del archivo. Devuelve los recuentos."""
    import datetime
    plan = sqlite3.connect(plan_path)
    n_hist = n_price = 0
    have = {(r[0], r[1]) for r in plan.execute("SELECT market, item_id FROM prices")}
    for mid, key in con.execute("SELECT market_id, key FROM markets").fetchall():
        rows = con.execute("""SELECT item_id, day, min_low, mv, qty_max, src, t FROM daily
                              WHERE market_id=? ORDER BY item_id, day""", (mid,)).fetchall()
        plan.execute("DELETE FROM history WHERE market=?", (key,))
        plan.executemany("INSERT INTO history VALUES (?,?,?,?,?,?,?,?)",
                         [(key, i, d, mn, mv, q, "atr" if src == "atr" else "oro", t) for i, d, mn, mv, q, src, t in rows])
        n_hist += len(rows)
        last = {}
        for i, d, mn, mv, q, src, t in rows:
            last[i] = (d, mn, mv, q, src, t)
        for i, (d, mn, mv, q, src, t) in last.items():
            if (key, i) in have or mn is None:
                continue
            if t is None:
                day = datetime.date.fromisoformat(d)
                t = int(datetime.datetime(day.year, day.month, day.day, 12).timestamp())
            plan.execute("INSERT INTO prices VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (key, i, mn, mv or mn, q, None, t, None, None, None, None, "atr" if src == "atr" else "oro"))
            plan.execute("INSERT OR IGNORE INTO items (item_id) VALUES (?)", (i,))
            n_price += 1
    names = {r[0]: r[1:] for r in con.execute("SELECT item_id, name, quality FROM items WHERE name IS NOT NULL")}
    for i, (name, q) in names.items():
        plan.execute("UPDATE items SET name = COALESCE(name, ?), quality = COALESCE(quality, ?) WHERE item_id=?", (name, q, i))
    plan.commit()
    plan.close()
    return {"history": n_hist, "prices_added": n_price}


# ----------------------------------------------------------------------
# Farmeo medido (docs/farmeo.md, sección 5): el juego guarda totales acumulados → se sustituyen
# ----------------------------------------------------------------------
def append_farm(con, db, market):
    """Copia OroborosDB.farm al archivo, en el mercado `market`. Devuelve (criaturas, subzonas de recolección)."""
    import json
    farm = (db or {}).get("farm") or {}
    if not (farm or (db or {}).get("farmPlaces") or (db or {}).get("farmMaps")) or not market:
        return 0, 0
    mid = market_id(con, market)
    items = lambda t: json.dumps({str(k): v for k, v in _as_dict(t).items()})
    n_m = n_g = 0
    for m in _as_dict(farm.get("mobs")).values():
        if not isinstance(m, dict) or not m.get("npc"):
            continue
        con.execute("INSERT OR REPLACE INTO farm_mobs VALUES (?,?,?,?,?,?,?,?,?)",
                    (mid, int(m["npc"]), m.get("sub") or "", m.get("zone"), m.get("map"), m.get("kills") or 0,
                     m.get("copper") or 0, m.get("secs") or 0, items(m.get("items"))))
        n_m += 1
    for g in _as_dict(farm.get("gather")).values():
        if not isinstance(g, dict):
            continue
        con.execute("INSERT OR REPLACE INTO farm_gather VALUES (?,?,?,?,?,?)",
                    (mid, g.get("sub") or "", g.get("zone"), g.get("map"), g.get("nodes") or 0, items(g.get("items"))))
        n_g += 1
    for npc, n in _as_dict(farm.get("npcs")).items():
        if isinstance(n, dict):
            con.execute("INSERT OR REPLACE INTO farm_npcs VALUES (?,?,?,?)", (int(npc), n.get("name"), n.get("lvl"), n.get("cls")))
    # nombres que el juego resolvió para los sitios de Farmeo.lua (FarmPanel.lua): para la página
    for key, field in (("farm_places", "farmPlaces"), ("farm_maps", "farmMaps")):
        val = _as_dict((db or {}).get(field))
        if val:
            con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps({str(k): v for k, v in val.items()},
                                                                                     ensure_ascii=False)))
    con.commit()
    return n_m, n_g
