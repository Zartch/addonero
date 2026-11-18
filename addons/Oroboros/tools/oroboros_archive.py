"""
Oroboros: archivo permanente de escaneos completos (docs/franjas-horarias.md).

El addon guarda los últimos 12 escaneos en `OroborosDB.markets[mk].scans` como
`{t = epoch, data = "id,min,mv,qty,b,bp;..."}`. Aquí se añaden a un SQLite que
nunca se borra (por defecto `work/archivo.sqlite`). Exportar dos veces no duplica.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    market TEXT, t INTEGER, item_id INTEGER,
    min REAL, mv REAL,          -- vacíos si el objeto se agotó
    qty INTEGER,                -- total publicado
    cheap INTEGER,              -- unidades a <= mínimo de este escaneo x 1,25
    cheap_prev INTEGER,         -- unidades a <= umbral barato del escaneo anterior
    PRIMARY KEY (market, t, item_id));
"""


def _rows(market, t, data):
    for entry in (data or "").split(";"):
        if not entry:
            continue
        f = entry.split(",")
        if len(f) != 6:
            continue
        num = lambda x: float(x) if x else None
        yield (market, int(t), int(f[0]), num(f[1]), num(f[2]), int(f[3]), int(f[4]), int(f[5]))


def _as_list(x):
    if isinstance(x, dict):
        return [x[k] for k in sorted(x)]
    return list(x or [])


def append_scans(archive_path, db):
    """Añade los escaneos del buffer de OroborosDB (dict) al archivo.

    Devuelve {"added": filas nuevas, "already": filas que ya estaban, "scans": escaneos nuevos,
    "gap": True si con el buffer lleno ningún escaneo solapa con lo archivado (se perdieron)}.
    """
    con = sqlite3.connect(archive_path)
    con.executescript(SCHEMA)
    added = already = new_scans = 0
    gap = False
    markets = db.get("markets") or {}
    for market, m in (markets.items() if isinstance(markets, dict) else []):
        scans = [s for s in _as_list((m or {}).get("scans")) if isinstance(s, dict) and s.get("t")]
        if not scans:
            continue
        last = con.execute("SELECT MAX(t) FROM scans WHERE market=?", (market,)).fetchone()[0]
        if last is not None and len(scans) >= 12 and min(s["t"] for s in scans) > last:
            gap = True
        for s in scans:
            known = con.execute("SELECT 1 FROM scans WHERE market=? AND t=? LIMIT 1", (market, int(s["t"]))).fetchone()
            rows = list(_rows(market, s["t"], s.get("data")))
            if known:
                already += len(rows)
                continue
            con.executemany("INSERT OR IGNORE INTO scans VALUES (?,?,?,?,?,?,?,?)", rows)
            added += len(rows)
            new_scans += 1
    con.commit()
    con.close()
    return {"added": added, "already": already, "scans": new_scans, "gap": gap}
