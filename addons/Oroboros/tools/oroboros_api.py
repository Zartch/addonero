#!/usr/bin/env python3
"""
Oroboros: subasta de WoW Forever leída con la API oficial de Blizzard (solo lectura).

Diseño y lo comprobado: docs/api-subasta-blizzard.md (apartado 0) y docs/planes/2026-11-23-api-blizzard.md.

Cada hora (la foto cambia hacia el minuto 23) baja las subastas normales y de materiales de las casas
elegidas, con If-Modified-Since para no bajar nada si no han cambiado, y las guarda en work/archivo.sqlite:
  api_houses     casa → nombre, facción y mercado del archivo
  api_snaps      una fila por foto
  api_live       solo la última foto de cada casa, por subasta (para compararla con la siguiente)
  api_item_hour  por casa, foto y objeto: precio y movimientos desde la foto anterior (14 días)
  daily          el histórico diario de siempre, con origen 'api'
Movimientos por id de subasta: desaparece con SHORT → caducada; desaparece y era cara (> mínimo × 1,25)
→ cancelada; desaparece y era barata → vendida; baja la cantidad del mismo id → compra parcial.

Credenciales: BNET_CLIENT_ID / BNET_CLIENT_SECRET, o work/bnet.env (KEY=VALOR). Nunca se muestran.

Uso:
  python oroboros_api.py --una-vez                 # una descarga y sale
  python oroboros_api.py                           # cada hora, hasta Ctrl+C
  python oroboros_api.py --importar work/api       # mete en el archivo fotos guardadas (grp_<UTC>_<casa>_<norm|mat>.json.gz)
"""
import argparse
import base64
import calendar
import datetime
import glob
import gzip
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from oroboros_archive import open_archive, market_id  # noqa: E402

API_HOST = "https://eu.api.blizzard.com"
TOKEN_URL = "https://oauth.battle.net/token"
NAMESPACE = "dynamic-forever-eu"
STATIC_NAMESPACE = "static-forever-eu"
RULESET = 2                      # la regla no importa: todas devuelven la misma foto (comprobado)
DEFAULT_HOUSES = [111, 114, 117]  # nuestro grupo: Alianza, Horda, Aguasnegras
DEFAULT_REALM = "CAMWOWEU5Realm5PvE"
DEFAULT_WORK = os.path.join(HERE, "..", "work")
CHEAP = 1.25                     # «barata»: ≤ mínimo del objeto × 1,25 (el mismo umbral que oroboros_hours)
MV_PERCENT = 0.15                # valor de mercado: media del 15 % más barato (como DB.Aggregate del addon)
MAX_GAP = 90 * 60                # más de 90 min entre fotos: no se clasifica (hueco)
TIME_LEFT = {"SHORT": 0, "MEDIUM": 1, "LONG": 2, "VERY_LONG": 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_houses (house INTEGER PRIMARY KEY, name TEXT, faction TEXT, market_id INTEGER);
CREATE TABLE IF NOT EXISTS api_snaps (
    house INTEGER, t INTEGER, prev_t INTEGER, auctions INTEGER, units INTEGER, items INTEGER,
    PRIMARY KEY (house, t)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS api_live (
    house INTEGER, auction_id INTEGER, item_id INTEGER, qty INTEGER,
    price REAL,                 -- cobre por unidad; vacío si solo tiene puja
    tl INTEGER,                 -- time_left: 0 SHORT, 1 MEDIUM, 2 LONG, 3 VERY_LONG
    first_t INTEGER,
    PRIMARY KEY (house, auction_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS api_item_hour (
    house INTEGER, t INTEGER, item_id INTEGER,
    min REAL, mv REAL, qty INTEGER, n INTEGER,          -- vacíos si el objeto ya no está
    d110 INTEGER, d125 INTEGER, d150 INTEGER, d200 INTEGER,
    new INTEGER, sold INTEGER, expired INTEGER, cancelled INTEGER, partial INTEGER, gap INTEGER,
    PRIMARY KEY (house, t, item_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS api_item_hour_item ON api_item_hour (item_id, house);
"""


def _log(*a):
    print(" ".join([time.strftime("[%d/%m %H:%M:%S]")] + [str(x) for x in a]), flush=True)


# ----------------------------------------------------------------------
# Credenciales y cliente HTTP
# ----------------------------------------------------------------------
def load_creds(work_dir=DEFAULT_WORK):
    """(id, secreto) de las variables de entorno o de work/bnet.env. None si faltan."""
    cid, sec = os.environ.get("BNET_CLIENT_ID"), os.environ.get("BNET_CLIENT_SECRET")
    p = os.path.join(work_dir, "bnet.env")
    if (not cid or not sec) and os.path.exists(p):
        with open(p, encoding="utf-8-sig") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                if k.strip() == "BNET_CLIENT_ID":
                    cid = cid or v.strip()
                elif k.strip() == "BNET_CLIENT_SECRET":
                    sec = sec or v.strip()
    if not cid or not sec or cid.startswith("PON_AQUI") or sec.startswith("PON_AQUI"):
        return None
    return cid, sec


def http_fetch(url, headers, data=None):
    """GET/POST con urllib. Devuelve (estado, cabeceras en minúsculas, cuerpo descomprimido)."""
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=120)
        st, hd, raw = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        st, hd, raw = e.code, e.headers, b""
    hd = {k.lower(): v for k, v in (hd or {}).items()}
    if raw and hd.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    return st, hd, raw


class ApiError(RuntimeError):
    pass


class Client:
    """Cliente de la API. El secreto solo se usa para pedir el token; no sale en mensajes ni en repr."""

    def __init__(self, creds, fetch=http_fetch, cache_dir=None, clock=time.time):
        self.__creds = creds
        self.fetch, self.clock = fetch, clock
        self.cache = os.path.join(cache_dir, "token.json") if cache_dir else None
        self._tok, self._exp = None, 0

    def __repr__(self):
        return "<Client API Blizzard>"

    def token(self):
        if self._tok and self._exp > self.clock() + 300:
            return self._tok
        if self.cache and os.path.exists(self.cache):
            try:
                with open(self.cache, encoding="utf-8") as fh:
                    d = json.load(fh)
                if d.get("exp", 0) > self.clock() + 300:
                    self._tok, self._exp = d["tok"], d["exp"]
                    return self._tok
            except (OSError, ValueError, KeyError):
                pass
        if not self.__creds:
            raise ApiError("faltan las credenciales (BNET_CLIENT_ID / BNET_CLIENT_SECRET o work/bnet.env)")
        cid, sec = self.__creds
        basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        st, _, body = self.fetch(TOKEN_URL, {"Authorization": "Basic " + basic,
                                             "Content-Type": "application/x-www-form-urlencoded"},
                                 b"grant_type=client_credentials")
        if st != 200:
            raise ApiError(f"token: HTTP {st} (¿credenciales correctas?)")
        try:
            d = json.loads(body)
            self._tok, self._exp = d["access_token"], self.clock() + int(d.get("expires_in", 86400))
        except (ValueError, KeyError):
            raise ApiError("token: respuesta inesperada") from None
        if self.cache:
            os.makedirs(os.path.dirname(self.cache), exist_ok=True)
            with open(self.cache, "w", encoding="utf-8") as fh:
                json.dump({"tok": self._tok, "exp": self._exp}, fh)
        return self._tok

    def get(self, path, ims=None, namespace=NAMESPACE, locale=None):
        """(estado, last-modified, dict o None). 304 → (304, lm, None)."""
        q = {"namespace": namespace}
        if locale:
            q["locale"] = locale
        hdr = {"Authorization": "Bearer " + self.token(), "Accept-Encoding": "gzip"}
        if ims:
            hdr["If-Modified-Since"] = ims
        st, hd, body = self.fetch(API_HOST + path + "?" + urllib.parse.urlencode(q), hdr)
        lm = hd.get("last-modified")
        if st == 401:                 # token caducado antes de tiempo: uno nuevo y otra vez
            self._tok, self._exp = None, 0
            if self.cache and os.path.exists(self.cache):
                os.remove(self.cache)
            hdr["Authorization"] = "Bearer " + self.token()
            st, hd, body = self.fetch(API_HOST + path + "?" + urllib.parse.urlencode(q), hdr)
            lm = hd.get("last-modified")
        if st == 200:
            try:
                return st, lm, json.loads(body)
            except ValueError:
                raise ApiError(f"{path}: JSON no válido") from None
        return st, lm, None


def lm_to_t(lm):
    return int(parsedate_to_datetime(lm).timestamp())


def t_to_lm(t):
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(t))


# ----------------------------------------------------------------------
# Tablas, casas y clasificación
# ----------------------------------------------------------------------
def open_api(path_or_con):
    """Abre el archivo (o usa la conexión) y crea las tablas de la API."""
    con = open_archive(path_or_con) if isinstance(path_or_con, str) else path_or_con
    con.executescript(SCHEMA)
    con.commit()
    return con


def faction_of(name):
    n = (name or "").lower()
    if "alianza" in n or "alliance" in n:
        return "Alliance"
    if "horda" in n or "horde" in n:
        return "Horde"
    return "Neutral"


def set_house(con, house, name, realm=DEFAULT_REALM):
    """Asocia la casa a la clave de mercado <reino>-<facción> (la misma que usa el addon). Devuelve market_id."""
    row = con.execute("SELECT market_id FROM api_houses WHERE house=?", (house,)).fetchone()
    if row:
        if name:
            con.execute("UPDATE api_houses SET name=? WHERE house=?", (name, house))
        return row[0]
    fac = faction_of(name)
    mid = market_id(con, f"{realm}-{fac}")
    con.execute("INSERT INTO api_houses VALUES (?,?,?,?)", (house, name, fac, mid))
    return mid


def as_live(auctions):
    """Lista de subastas de la API → {id: (objeto, cantidad, precio unitario o None, tl)}."""
    out = {}
    for a in auctions or []:
        q = a.get("quantity") or 1
        if a.get("unit_price") is not None:
            p = a["unit_price"]
        elif a.get("buyout"):
            p = a["buyout"] / q
        else:
            p = None
        out[a["id"]] = (a["item"]["id"], q, p, TIME_LEFT.get(a.get("time_left"), 2))
    return out


def classify(prev, cur, gap=False):
    """Movimientos por objeto entre dos fotos ({id: (objeto, cantidad, precio, tl)}).
    Devuelve {objeto: {new, sold, expired, cancelled, partial}} (y «gap» si hay hueco), en unidades."""
    mins = {}
    for item, q, p, tl in prev.values():
        if p is not None and (item not in mins or p < mins[item]):
            mins[item] = p
    out = defaultdict(lambda: {"new": 0, "sold": 0, "expired": 0, "cancelled": 0, "partial": 0})
    for aid, (item, q, p, tl) in prev.items():
        nxt = cur.get(aid)
        if nxt is None:
            if gap:
                k = "gap"
            elif tl == 0:
                k = "expired"
            elif p is None or p > mins[item] * CHEAP:
                k = "cancelled"
            else:
                k = "sold"
            o = out[item]
            o[k] = o.get(k, 0) + q
        elif nxt[1] < q:
            o = out[item]
            if gap:
                o["gap"] = o.get("gap", 0) + q - nxt[1]
            else:
                o["partial"] += q - nxt[1]
    for aid, (item, q, p, tl) in cur.items():
        if aid not in prev:
            out[item]["new"] += q
    return dict(out)


def aggregate(listings):
    """[(precio, cantidad)] → (min, mv, total, n, [d110, d125, d150, d200]), como DB.Aggregate del addon."""
    ls = sorted((p, q) for p, q in listings if p is not None)
    if not ls:
        return None
    total = sum(q for _, q in ls)
    target = max(1, -(-int(total * MV_PERCENT * 1000) // 1000))   # ceil sin errores de coma flotante
    acc = s = 0
    for p, q in ls:
        take = min(q, target - acc)
        s += p * take
        acc += take
        if acc >= target:
            break
    mn = ls[0][0]
    depth = [sum(q for p, q in ls if p <= mn * k) for k in (1.10, 1.25, 1.5, 2.0)]
    return mn, int(s / acc + 0.5), total, len(ls), depth


def _day(t):
    return datetime.datetime.fromtimestamp(t).date().isoformat()


def _upsert_daily(con, mid, t, stats):
    """daily con origen 'api': mínimo y más alto del día, último valor de mercado, cantidad máxima.
    La API gana sobre el juego (docs/planes/2026-11-23-api-blizzard.md, «Quién gana»)."""
    day = _day(t)
    cur = {r[0]: r[1:] for r in con.execute(
        "SELECT item_id, min_low, min_high, qty_max, src FROM daily WHERE market_id=? AND day=?", (mid, day))}
    rows = []
    for item, (mn, mv, qty) in stats.items():
        c = cur.get(item)
        if c and c[3] == "api":
            lo = mn if c[0] is None else min(c[0], mn)
            hi = mn if c[1] is None else max(c[1], mn)
            q = max(c[2] or 0, qty)
        else:
            lo = hi = mn
            q = qty
        rows.append((mid, item, day, lo, hi, mv, q, "api", t))
    con.executemany("INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?,?,?)", rows)


def ingest(con, house, t, auctions):
    """Mete una foto (normales y materiales juntos) en el archivo. t = last-modified en segundos.
    Devuelve {"skipped", "first", "gap", "auctions", "items"}."""
    house, t = int(house), int(t)
    last = con.execute("SELECT MAX(t) FROM api_snaps WHERE house=?", (house,)).fetchone()[0]
    if last is not None and t <= last:
        return {"skipped": True, "first": False, "gap": False, "auctions": 0, "items": 0}
    row = con.execute("SELECT market_id FROM api_houses WHERE house=?", (house,)).fetchone()
    mid = row[0] if row else set_house(con, house, None)
    cur = as_live(auctions)
    prev = {r[0]: r[1:5] for r in con.execute(
        "SELECT auction_id, item_id, qty, price, tl FROM api_live WHERE house=?", (house,))}
    first_seen = {r[0]: r[1] for r in con.execute("SELECT auction_id, first_t FROM api_live WHERE house=?", (house,))}
    first = last is None
    gap = (not first) and t - last > MAX_GAP
    moves = {} if first else classify(prev, cur, gap=gap)
    by_item = defaultdict(list)
    for item, q, p, tl in cur.values():
        by_item[item].append((p, q))
    stats, rows = {}, []
    for item in set(by_item) | set(moves):
        ag = aggregate(by_item.get(item, []))
        mv = moves.get(item)
        if ag:
            mn, mvv, qty, n, d = ag
            stats[item] = (mn, mvv, qty)
        else:
            mn = mvv = qty = n = None
            d = [None] * 4
        ev = (None,) * 6 if first else (mv["new"], mv["sold"], mv["expired"], mv["cancelled"], mv["partial"], mv.get("gap", 0)) \
            if mv else (0, 0, 0, 0, 0, 0)
        rows.append((house, t, item, mn, mvv, qty, n, *d, *ev))
    with con:
        con.executemany("INSERT OR REPLACE INTO api_item_hour VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("DELETE FROM api_live WHERE house=?", (house,))
        con.executemany("INSERT INTO api_live VALUES (?,?,?,?,?,?,?)",
                        [(house, aid, it, q, p, tl, first_seen.get(aid, t)) for aid, (it, q, p, tl) in cur.items()])
        con.execute("INSERT INTO api_snaps VALUES (?,?,?,?,?,?)",
                    (house, t, last, len(cur), sum(v[1] for v in cur.values()), len(by_item)))
        _upsert_daily(con, mid, t, stats)
        for item in by_item:
            con.execute("""INSERT INTO items (item_id, first_seen, last_seen) VALUES (?,?,?)
                           ON CONFLICT(item_id) DO UPDATE SET last_seen = MAX(COALESCE(last_seen, 0), excluded.last_seen),
                           first_seen = COALESCE(first_seen, excluded.first_seen)""", (item, t, t))
    return {"skipped": False, "first": first, "gap": gap, "auctions": len(cur), "items": len(by_item)}


# ----------------------------------------------------------------------
# Descarga
# ----------------------------------------------------------------------
def fetch_house(client, house, ims=None):
    """(estado, t, nombre, subastas). estado: 'nueva' o 'sin cambios'. Lanza ApiError si algo falla."""
    base = f"/data/wow/ruleset/{RULESET}/auctions/{house}"
    st, lm, norm = client.get(base, ims=ims)
    if st == 304:
        return "sin cambios", None, None, None
    if st != 200 or not lm:
        raise ApiError(f"casa {house}: HTTP {st}")
    st2, _, mat = client.get(base + "/commodities")
    if st2 != 200:
        raise ApiError(f"casa {house} (materiales): HTTP {st2}")
    return "nueva", lm_to_t(lm), norm.get("name"), (norm.get("auctions") or []) + (mat.get("auctions") or [])


def run_once(archive, client, houses=DEFAULT_HOUSES, realm=DEFAULT_REALM, log=_log):
    """Una vuelta: por cada casa, baja si ha cambiado y la mete en el archivo. Nunca lanza: los errores
    se registran y se devuelven. [{"house", "status": 'nueva'|'sin cambios'|'error', ...}]"""
    con = open_api(archive)
    out = []
    try:
        for h in houses:
            last = con.execute("SELECT MAX(t) FROM api_snaps WHERE house=?", (h,)).fetchone()[0]
            try:
                st, t, name, auctions = fetch_house(client, h, ims=t_to_lm(last) if last else None)
                if st == "nueva":
                    set_house(con, h, name, realm)
                    r = ingest(con, h, t, auctions)
                    if r["skipped"]:
                        st = "sin cambios"
                    else:
                        log(f"casa {h}: foto de las {time.strftime('%H:%M', time.localtime(t))}, "
                            f"{r['auctions']} subastas, {r['items']} objetos" + (" (hueco: sin clasificar)" if r["gap"] else ""))
                    out.append({"house": h, "status": st, "t": t, **r})
                else:
                    out.append({"house": h, "status": st, "t": last})
            except (ApiError, OSError, ValueError) as e:
                msg = str(e) if isinstance(e, ApiError) else type(e).__name__
                log(f"casa {h}: error: {msg}")
                out.append({"house": h, "status": "error", "error": msg})
    finally:
        con.close()
    return out


def import_dir(archive, folder, realm=DEFAULT_REALM, log=lambda *a: None):
    """Mete en el archivo las fotos guardadas grp_<AAAAMMDD-HHMMSS UTC>_<casa>_<norm|mat>.json.gz, en orden.
    Devuelve las fotos nuevas."""
    pat = re.compile(r"grp_(\d{8}-\d{6})_(\d+)_(norm|mat)\.json\.gz$")
    photos = defaultdict(dict)
    for f in glob.glob(os.path.join(folder, "grp_*.json.gz")):
        m = pat.search(os.path.basename(f))
        if m:
            t = calendar.timegm(time.strptime(m.group(1), "%Y%m%d-%H%M%S"))
            photos[(t, int(m.group(2)))][m.group(3)] = f
    con = open_api(archive)
    n = 0
    try:
        for (t, h), parts in sorted(photos.items()):
            if "norm" not in parts or "mat" not in parts:
                continue
            with gzip.open(parts["norm"], "rt", encoding="utf-8") as fh:
                norm = json.load(fh)
            with gzip.open(parts["mat"], "rt", encoding="utf-8") as fh:
                mat = json.load(fh)
            set_house(con, h, norm.get("name"), realm)
            r = ingest(con, h, t, (norm.get("auctions") or []) + (mat.get("auctions") or []))
            if not r["skipped"]:
                n += 1
                log(f"casa {h}: importada la foto de las {time.strftime('%d/%m %H:%M', time.localtime(t))}")
    finally:
        con.close()
    return n


def next_check(now, minute=25):
    """Segundos hasta el próximo minuto `minute` de una hora."""
    lt = time.localtime(now)
    wait = (minute - lt.tm_min) * 60 - lt.tm_sec
    return wait if wait > 0 else wait + 3600


def wait_after(results, now, retry=300, fresh=50 * 60):
    """Cuánto esperar tras una vuelta: si alguna casa no tiene aún la foto de esta hora, reintentar
    en `retry` s (hasta el minuto 55); si todas la tienen, hasta el próximo minuto 25."""
    stale = [r for r in results if not r.get("t") or now - r["t"] > fresh]
    if stale and time.localtime(now).tm_min < 55:
        return retry
    return next_check(now)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=DEFAULT_WORK, help="carpeta de trabajo (por defecto work/)")
    ap.add_argument("--archive", help="archivo SQLite (por defecto <work>/archivo.sqlite)")
    ap.add_argument("--casas", default=",".join(map(str, DEFAULT_HOUSES)), help="casas separadas por comas")
    ap.add_argument("--reino", default=DEFAULT_REALM, help="reino interno para la clave de mercado")
    ap.add_argument("--una-vez", action="store_true", help="descargar una vez y salir")
    ap.add_argument("--importar", metavar="CARPETA", help="importar fotos guardadas y salir")
    a = ap.parse_args()
    archive = a.archive or os.path.join(a.work, "archivo.sqlite")
    houses = [int(x) for x in a.casas.split(",") if x.strip()]
    if a.importar:
        n = import_dir(archive, a.importar, a.reino, log=_log)
        _log(f"{n} fotos importadas en {archive}")
        return
    creds = load_creds(a.work)
    if not creds:
        sys.exit("Faltan las credenciales: BNET_CLIENT_ID / BNET_CLIENT_SECRET o work/bnet.env")
    client = Client(creds, cache_dir=os.path.join(a.work, "api"))
    if a.una_vez:
        res = run_once(archive, client, houses, a.reino)
        sys.exit(1 if any(r["status"] == "error" for r in res) else 0)
    _log(f"Descargando las casas {houses} cada hora (minuto 25). Ctrl+C para parar.")
    try:
        while True:
            res = run_once(archive, client, houses, a.reino)
            time.sleep(wait_after(res, time.time()))
    except KeyboardInterrupt:
        _log("Parado.")


if __name__ == "__main__":
    main()
