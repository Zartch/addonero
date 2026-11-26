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
KEEP_DAYS = 14                   # api_item_hour en detalle; las semanas más viejas pasan a api_band_week
MAX_GAP = 90 * 60                # más de 90 min entre fotos: no se clasifica (hueco)
RELIST_DROP = 0.20               # recolocación: la misma cantidad reaparece hasta un 20 % más barata
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
-- variante de las subastas de api_live que la tienen (bonus_lists ordenadas: «12752», «12745.12760»).
-- Tabla aparte para no cambiar api_live: un panel en marcha con el código anterior sigue escribiendo en ella.
CREATE TABLE IF NOT EXISTS api_var (
    house INTEGER, auction_id INTEGER, var TEXT,
    PRIMARY KEY (house, auction_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS api_item_hour (
    house INTEGER, t INTEGER, item_id INTEGER,
    min REAL, mv REAL, qty INTEGER, n INTEGER,          -- vacíos si el objeto ya no está
    d110 INTEGER, d125 INTEGER, d150 INTEGER, d200 INTEGER,
    new INTEGER, sold INTEGER, expired INTEGER, cancelled INTEGER, partial INTEGER, gap INTEGER,
    PRIMARY KEY (house, t, item_id)) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS api_item_hour_item ON api_item_hour (item_id, house);
CREATE TABLE IF NOT EXISTS api_band_week (       -- resumen permanente por semana ISO y franja de 4 h
    house INTEGER, item_id INTEGER, week TEXT, band INTEGER,
    new REAL, sold REAL, expired REAL, cancelled REAL, partial REAL, gap REAL,
    hours REAL, n INTEGER, days INTEGER,
    price_med REAL, price_sum REAL, price_n INTEGER,
    last_day TEXT,                                   -- último día con medición (para contar días al acumular)
    PRIMARY KEY (house, item_id, week, band)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS api_missing (item_id INTEGER PRIMARY KEY, t INTEGER);   -- la ruta de objetos dio 404
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


def _raw_fetch(url, headers, data=None):
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


def safe_fetch(fetch):
    """Envuelve un fetch: los cortes de red que no son OSError (respuesta incompleta, gzip cortado) pasan a
    ApiError, para que se registren como error de esa casa y el bucle siga. Solo el tipo: nada de cabeceras."""
    import http.client
    import zlib

    def wrapped(url, headers, data=None):
        try:
            return fetch(url, headers, data)
        except (http.client.HTTPException, EOFError, zlib.error) as e:
            raise ApiError(f"red: {type(e).__name__}") from None
    return wrapped


http_fetch = safe_fetch(_raw_fetch)


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
    _migrate(con)
    con.commit()
    return con


def _migrate(con):
    """Archivos de antes del 24/11: api_band_week sin last_day y sin las franjas acumuladas por foto."""
    cols = {r[1] for r in con.execute("PRAGMA table_info(api_band_week)")}
    if "last_day" not in cols:
        con.execute("ALTER TABLE api_band_week ADD COLUMN last_day TEXT")
    r = con.execute("SELECT value FROM meta WHERE key='api_bands'").fetchone()
    if not r or r[0] != "por-foto":
        rebuild_bands(con)
        con.execute("INSERT OR REPLACE INTO meta VALUES ('api_bands', 'por-foto')")
        con.commit()


def house_name(name):
    """Sin locale la API da el nombre en todos los idiomas ({"es_ES": …, "en_GB": …}): se usa el español."""
    if isinstance(name, dict):
        return name.get("es_ES") or name.get("es_MX") or name.get("en_GB") or name.get("en_US") or next(iter(name.values()), None)
    return name


def faction_of(name):
    n = (house_name(name) or "").lower()
    if "alianza" in n or "alliance" in n:
        return "Alliance"
    if "horda" in n or "horde" in n:
        return "Horde"
    return "Neutral"


def set_house(con, house, name, realm=DEFAULT_REALM, market=None):
    """Asocia la casa a la clave de mercado <reino>-<facción> (la misma que usa el addon), o a `market`
    si se da. Devuelve market_id."""
    name = house_name(name)
    row = con.execute("SELECT market_id FROM api_houses WHERE house=?", (house,)).fetchone()
    if row:
        if name:
            con.execute("UPDATE api_houses SET name=? WHERE house=?", (name, house))
        return row[0]
    fac = faction_of(name)
    mid = market_id(con, market or f"{realm}-{fac}")
    con.execute("INSERT INTO api_houses VALUES (?,?,?,?)", (house, name, fac, mid))
    return mid


def variant_of(item):
    """Variante de un objeto de la API: sus bonus_lists ordenadas («12745.12760»), o '' si no tiene.
    Dos piezas con el mismo número de objeto y distinta variante («del bandido», «de la ballena») son
    productos distintos, con precios distintos."""
    return ".".join(str(b) for b in sorted(item.get("bonus_lists") or []))


def as_live(auctions):
    """Lista de subastas de la API → {id: (objeto, cantidad, precio unitario o None, tl, variante)}."""
    out = {}
    for a in auctions or []:
        q = a.get("quantity") or 1
        if a.get("unit_price") is not None:
            p = a["unit_price"]
        elif a.get("buyout"):
            p = a["buyout"] / q
        else:
            p = None
        out[a["id"]] = (a["item"]["id"], q, p, TIME_LEFT.get(a.get("time_left"), 2), variant_of(a["item"]))
    return out


def classify(prev, cur, gap=False):
    """Movimientos por objeto entre dos fotos ({id: (objeto, cantidad, precio, tl, variante)}).
    Devuelve {objeto: {new, sold, expired, cancelled, partial}} (y «gap» si hay hueco), en unidades.

    Una subasta que desaparece cuenta como vendida solo si era barata (≤ mínimo × CHEAP) y no sigue
    viva ninguna más barata del mismo objeto y variante: quien compra, compra primero lo más barato,
    así que si la barata sigue ahí, la otra la retiró su dueño (cancelada).

    Recolocación: si en la misma foto aparece otra subasta del mismo objeto y variante, con la misma
    cantidad y a un precio igual o algo más bajo (hasta RELIST_DROP), es su dueño bajando el precio y
    cuenta como cancelada. Cada subasta nueva empareja con una sola desaparecida."""
    key = lambda v: (v[0], v[4] if len(v) > 4 else "")
    mins, alive = {}, {}
    for aid, v in prev.items():
        p, k = v[2], key(v)
        if p is None:
            continue
        if k not in mins or p < mins[k]:
            mins[k] = p
        if aid in cur and (k not in alive or p < alive[k]):
            alive[k] = p
    fresh = defaultdict(list)          # (objeto, variante, cantidad) → precios de las subastas nuevas
    for aid, v in cur.items():
        if aid not in prev and v[2] is not None:
            fresh[(*key(v), v[1])].append(v[2])
    for ps in fresh.values():
        ps.sort(reverse=True)
    out = defaultdict(lambda: {"new": 0, "sold": 0, "expired": 0, "cancelled": 0, "partial": 0})
    # de cara a barata: la más cara desaparecida empareja antes con su recolocación
    for aid, v in sorted(prev.items(), key=lambda kv: -(kv[1][2] or 0)):
        item, q, p, tl = v[:4]
        nxt = cur.get(aid)
        if nxt is None:
            k2 = key(v)
            if gap:
                k = "gap"
            elif tl == 0:
                k = "expired"
            elif p is None or p > mins[k2] * CHEAP or (k2 in alive and p > alive[k2]):
                k = "cancelled"
            else:
                k = "sold"
                ps = fresh.get((*k2, q))
                j = next((i for i, np_ in enumerate(ps or ()) if p * (1 - RELIST_DROP) <= np_ <= p), None)
                if j is not None:
                    ps.pop(j)
                    k = "cancelled"            # recolocada: misma cantidad, mismo precio o algo menos
            o = out[item]
            o[k] = o.get(k, 0) + q
        elif nxt[1] < q:
            o = out[item]
            if gap:
                o["gap"] = o.get("gap", 0) + q - nxt[1]
            else:
                o["partial"] += q - nxt[1]
    for aid, v in cur.items():
        if aid not in prev:
            out[v[0]]["new"] += v[1]
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
    prev = {r[0]: (r[1], r[2], r[3], r[4], r[5] or "") for r in con.execute(
        """SELECT l.auction_id, l.item_id, l.qty, l.price, l.tl, v.var FROM api_live l
           LEFT JOIN api_var v ON v.house = l.house AND v.auction_id = l.auction_id WHERE l.house=?""", (house,))}
    first_seen = {r[0]: r[1] for r in con.execute("SELECT auction_id, first_t FROM api_live WHERE house=?", (house,))}
    first = last is None
    gap = (not first) and t - last > MAX_GAP
    moves = {} if first else classify(prev, cur, gap=gap)
    # desde qué foto se clasifica con la regla de recolocaciones: las horas de antes cuentan de más
    # y no entran en las ventas por día (rule_since). Un archivo nuevo la lleva desde el principio.
    if con.execute("SELECT 1 FROM meta WHERE key='api_rule_t'").fetchone() is None:
        any_snap = con.execute("SELECT 1 FROM api_snaps LIMIT 1").fetchone()
        with con:
            con.execute("INSERT INTO meta VALUES ('api_rule_t', ?)", (str(t if any_snap else 0),))
    by_item = defaultdict(list)
    for item, q, p, tl, _var in cur.values():
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
                        [(house, aid, it, q, p, tl, first_seen.get(aid, t)) for aid, (it, q, p, tl, _v) in cur.items()])
        con.execute("DELETE FROM api_var WHERE house=?", (house,))
        con.executemany("INSERT INTO api_var VALUES (?,?,?)", [(house, aid, v[4]) for aid, v in cur.items() if v[4]])
        con.execute("INSERT INTO api_snaps VALUES (?,?,?,?,?,?)",
                    (house, t, last, len(cur), sum(v[1] for v in cur.values()), len(by_item)))
        _upsert_daily(con, mid, t, stats)
        add_bands(con, house, [(r[2], t, last, r[3], *r[11:17]) for r in rows])
        for item in by_item:
            con.execute("""INSERT INTO items (item_id, first_seen, last_seen) VALUES (?,?,?)
                           ON CONFLICT(item_id) DO UPDATE SET last_seen = MAX(COALESCE(last_seen, 0), excluded.last_seen),
                           first_seen = COALESCE(first_seen, excluded.first_seen)""", (item, t, t))
    return {"skipped": False, "first": first, "gap": gap, "auctions": len(cur), "items": len(by_item)}


# ----------------------------------------------------------------------
# Franjas desde la API, resumen semanal y retención
# ----------------------------------------------------------------------
MOVES = ("new", "sold", "expired", "cancelled", "partial", "gap")


def contributions(rows):
    """rows: (objeto, t, t_anterior, min, new, sold, expired, cancelled, partial, gap) de api_item_hour.
    Igual que oroboros_hours.contributions: los movimientos de un intervalo se reparten entre las franjas
    que cubre, en proporción al tiempo; la semana es la del inicio del intervalo.
      ("move", objeto, semana, franja, {movimiento: unidades}, segundos, día)
      ("price", objeto, semana, franja, mínimo)"""
    from oroboros_hours import _split, band_of, week_of
    for item, t, prev_t, mn, *mv in rows:
        if mn is not None:
            yield ("price", item, week_of(t), band_of(t), mn)
        # sin foto anterior, o con un hueco (lo desaparecido no se clasificó): no es una medición
        if prev_t is None or mv[0] is None or t <= prev_t or t - prev_t > MAX_GAP:
            continue
        span, wk = t - prev_t, week_of(prev_t)
        for b, secs, day in _split(prev_t, t):
            f = secs / span
            yield ("move", item, wk, b, {k: (v or 0) * f for k, v in zip(MOVES, mv)}, secs, day)


HOUR_SQL = """SELECT h.item_id, h.t, s.prev_t, h.min, h.new, h.sold, h.expired, h.cancelled, h.partial, h.gap
              FROM api_item_hour h JOIN api_snaps s ON s.house = h.house AND s.t = h.t
              WHERE h.house=? {extra} ORDER BY h.item_id, h.t"""


def _in(items):
    return f" AND {{col}} IN ({','.join('?' * len(items))})" if items else ""


BAND_UPSERT = """INSERT INTO api_band_week
    (house, item_id, week, band, new, sold, expired, cancelled, partial, gap, hours, n, days, price_med, price_sum, price_n, last_day)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT (house, item_id, week, band) DO UPDATE SET
      new = new + excluded.new, sold = sold + excluded.sold, expired = expired + excluded.expired,
      cancelled = cancelled + excluded.cancelled, partial = partial + excluded.partial, gap = gap + excluded.gap,
      hours = hours + excluded.hours, n = n + excluded.n,
      days = days + (CASE WHEN excluded.last_day IS NOT NULL AND (last_day IS NULL OR last_day != excluded.last_day)
                          THEN 1 ELSE 0 END),
      last_day = COALESCE(excluded.last_day, last_day),
      price_sum = price_sum + excluded.price_sum, price_n = price_n + excluded.price_n,
      price_med = CASE WHEN price_n + excluded.price_n > 0
                       THEN (price_sum + excluded.price_sum) / (price_n + excluded.price_n) END"""


def add_bands(con, house, rows):
    """Suma a api_band_week lo que aporta UNA foto (filas como HOUR_SQL, todas con el mismo t).
    Se hace al meter cada foto, así las franjas no recorren el detalle y la retención (borrar el detalle)
    no cambia nada. El precio de cada franja y semana es la media de los mínimos.
    Un intervalo dura como mucho 90 min: en una foto, cada (objeto, semana, franja) recibe como mucho un trozo."""
    agg = {}
    for c in contributions(rows):
        a = agg.setdefault((c[1], c[2], c[3]), {**{k: 0.0 for k in MOVES}, "secs": 0.0, "n": 0, "day": None, "psum": 0.0, "pn": 0})
        if c[0] == "price":
            a["psum"] += c[4]; a["pn"] += 1
        else:
            for k, v in c[4].items():
                a[k] += v
            a["secs"] += c[5]; a["n"] += 1; a["day"] = c[6]
    con.executemany(BAND_UPSERT, [_band_row(house, key, a) for key, a in agg.items()])


def _band_row(house, key, a):
    item, wk, band = key
    return (house, item, wk, band, *(a[k] for k in MOVES), a["secs"] / 3600, a["n"], 1 if a["day"] else 0,
            (a["psum"] / a["pn"]) if a["pn"] else None, a["psum"], a["pn"], a["day"])


def rebuild_bands(con, house=None):
    """Rehace api_band_week desde el detalle de api_item_hour (para archivos de antes de que se acumulara
    al meter cada foto). Solo las semanas que tienen detalle."""
    from oroboros_hours import week_of
    houses = [house] if house is not None else [r[0] for r in con.execute("SELECT DISTINCT house FROM api_item_hour")]
    for h in houses:
        ts = [r[0] for r in con.execute("SELECT DISTINCT t FROM api_item_hour WHERE house=? ORDER BY t", (h,))]
        weeks = {week_of(t) for t in ts}
        for w in weeks:
            con.execute("DELETE FROM api_band_week WHERE house=? AND week=?", (h, w))
        for t in ts:
            add_bands(con, h, con.execute(HOUR_SQL.format(extra="AND h.t=?"), (h, t)).fetchall())
    con.commit()


def band_stats(con, house, items=None):
    """{objeto: [6 dicts por franja]} con unidades por movimiento, horas medidas, mediciones, días y
    precio típico (mediana de las medias semanales del mínimo). Sale solo de api_band_week, que se
    acumula al meter cada foto. Valores redondeados."""
    import statistics
    items = list(items) if items else None
    acc = defaultdict(lambda: [{**{k: 0.0 for k in MOVES}, "hours": 0.0, "n": 0, "days": 0, "meds": []} for _ in range(6)])
    q = ("SELECT item_id, band, new, sold, expired, cancelled, partial, gap, hours, n, days, price_med "
         "FROM api_band_week WHERE house=?" + _in(items).format(col="item_id"))
    for r in con.execute(q, [house] + (items or [])):
        a = acc[r[0]][r[1]]
        for k, v in zip(MOVES, r[2:8]):
            a[k] += v or 0
        a["hours"] += r[8] or 0; a["n"] += r[9] or 0; a["days"] += r[10] or 0
        if r[11] is not None:
            a["meds"].append(r[11])
    out = {}
    for item, bands in acc.items():
        out[item] = [{**{k: round(x[k], 6) for k in MOVES}, "hours": round(x["hours"], 6), "n": x["n"], "days": x["days"],
                      "price_med": statistics.median(x["meds"]) if x["meds"] else None} for x in bands]
    return out


def rollup_api(con, now, keep_days=KEEP_DAYS):
    """Borra el detalle por hora (api_item_hour) de más de `keep_days` días. Las franjas no cambian: ya están
    en api_band_week, que se acumula al meter cada foto. Devuelve las filas borradas."""
    with con:
        return con.execute("DELETE FROM api_item_hour WHERE t < ?", (now - keep_days * 86400,)).rowcount


def house_for_market(con, market_key):
    """Casa de la API asociada a una clave de mercado, o None (también si el archivo no tiene tablas de la API)."""
    try:
        r = con.execute("""SELECT h.house FROM api_houses h JOIN markets m USING (market_id)
                           WHERE m.key=? ORDER BY h.house LIMIT 1""", (market_key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if r:
        con.executescript(SCHEMA)       # completa las tablas que añadió una versión posterior
        _migrate(con)
    return r[0] if r else None


def rule_since(con):
    """Primera foto clasificada con la regla de recolocaciones (0 si todas, None si ninguna todavía)."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key='api_rule_t'").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(r[0]) if r else None


def move_rates(con, house, now=None, days=7, items=None):
    """Movimientos por día y objeto con las fotos de los últimos `days` días: {objeto: {sold (incluidas
    las compras parciales), expired, cancelled, new}}, y los días medidos: el tiempo que cubren los
    intervalos con medición, en días (28 fotos seguidas son poco más de un día, aunque caigan en tres
    fechas). Solo cuentan los intervalos medidos (con foto anterior y sin hueco) y clasificados ya con
    la regla de recolocaciones (rule_since)."""
    now = now or time.time()
    rule = rule_since(con)
    if rule is None:
        return {}, 0                   # todo lo guardado es de antes de la regla: contaba recolocaciones
    since = max(now - days * 86400, rule)
    snaps = con.execute("""SELECT t, prev_t FROM api_snaps WHERE house=? AND t >= ? AND prev_t IS NOT NULL
                           AND t - prev_t <= ?""", (house, since, MAX_GAP)).fetchall()
    secs = sum(t - p for t, p in snaps)
    if not secs:
        return {}, 0
    cov = round(secs / 86400, 2)
    extra = f" AND h.item_id IN ({','.join('?' * len(items))})" if items else ""
    rates = {}
    for item, sold, exp, can, new in con.execute(
            f"""SELECT h.item_id, SUM(COALESCE(h.sold, 0) + COALESCE(h.partial, 0)), SUM(COALESCE(h.expired, 0)),
                       SUM(COALESCE(h.cancelled, 0)), SUM(COALESCE(h.new, 0))
                FROM api_item_hour h JOIN api_snaps s ON s.house = h.house AND s.t = h.t
                WHERE h.house=? AND h.t >= ? AND s.prev_t IS NOT NULL AND h.t - s.prev_t <= ? AND h.sold IS NOT NULL{extra}
                GROUP BY h.item_id""", (house, since, MAX_GAP, *(items or []))):
        k = 86400 / secs
        rates[item] = {"sold": sold * k, "expired": exp * k, "cancelled": can * k, "new": new * k}
    return rates, cov


def sold_rates(con, house, now=None, days=7, items=None):
    """Vendidas por día (incluidas las compras parciales): ({objeto: vendidas/día}, días con mediciones)."""
    rates, cov = move_rates(con, house, now, days, items)
    return {i: r["sold"] for i, r in rates.items()}, cov


CALIB_MIN_COVER = 0.8            # cobertura mínima de tus ventas reales para fiarse de las vendidas estimadas
CALIB_MIN_SALES = 5              # y con al menos tantas ventas tuyas comprobadas
CALIB_MAX_TURNOVER = 1.0         # y que la casa entera no salga vendida más de una vez al día


def turnover(con, house, now=None, days=7):
    """Rotación de la casa: unidades «vendidas» al día entre las que hay a la venta en la última foto.
    Una casa no se vende entera varias veces al día: si sale muy por encima de 1, lo que se cuenta
    como venta son sobre todo recolocaciones. None si no hay mediciones."""
    rates, _ = move_rates(con, house, now, days)
    live = con.execute("SELECT SUM(qty) FROM api_live WHERE house=?", (house,)).fetchone()[0]
    if not rates or not live:
        return None
    return sum(r["sold"] for r in rates.values()) / live


def is_calibrated(con, house):
    """¿Nos fiamos de las vendidas estimadas de esta casa? Hacen falta las dos cosas de la última
    calibración (calibrate): que tus ventas reales aparezcan entre las vendidas (cobertura: no se le
    escapan ventas) y que la rotación de la casa sea creíble (no cuenta de más). La cobertura sola no
    basta: un clasificador que lo diera todo por vendido tendría cobertura del 100 %."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (f"api_calibration_{house}",)).fetchone()
    except sqlite3.OperationalError:
        return False
    if not r:
        return False
    try:
        d = json.loads(r[0])
    except ValueError:
        return False
    return ((d.get("sales") or 0) >= CALIB_MIN_SALES and (d.get("coverage") or 0) >= CALIB_MIN_COVER
            and d.get("turnover") is not None and d["turnover"] <= CALIB_MAX_TURNOVER)


CALIB_MARGIN = 3600              # la hora del correo no es exacta: ±1 h alrededor de la venta


def calibrate(archive, plan_db, house=DEFAULT_HOUSES[0], margin=CALIB_MARGIN, save=True):
    """Compara tus ventas reales (libro del correo, ledger con op SELL en el SQLite del plan) con lo que la
    estimación dio por vendido en esa casa, en los intervalos entre fotos alrededor de cada venta.
      sales/units: tus ventas (y unidades) con fotos de la API alrededor
      covered:     de esas unidades, las que la estimación ve como vendidas (lo más que puede ver)
      coverage:    covered / units — debería acercarse a 1
      share:       covered / vendidas estimadas en esos intervalos (qué parte fuiste tú)
      outside:     ventas tuyas sin fotos de la API (no se pueden comprobar)
      turnover:    vendidas estimadas al día entre lo que hay a la venta en la casa (ver turnover)
      detail:      por venta, lo que la estimación vio de ese objeto (vendidas, canceladas, caducadas)
    Guarda el resultado en meta (api_calibration_<casa>), que usa is_calibrated."""
    con = open_api(archive)
    mk = con.execute("""SELECT m.key FROM api_houses h JOIN markets m USING (market_id) WHERE h.house=?""",
                     (house,)).fetchone()
    plan = sqlite3.connect(plan_db)
    try:
        chars = {r[0] for r in plan.execute("SELECT char FROM characters WHERE market=?", (mk[0] if mk else None,))}
        sales = [r for r in plan.execute("SELECT t, char, item_id, qty FROM ledger WHERE op='SELL' ORDER BY t")
                 if r[1] in chars and r[0] and r[2]]
    finally:
        plan.close()
    res = {"house": house, "sales": 0, "units": 0, "covered": 0, "est_sold": 0.0, "outside": 0, "detail": []}
    seen_est = set()
    for t, _, item, qty in sales:
        snaps = con.execute("""SELECT t FROM api_snaps WHERE house=? AND prev_t IS NOT NULL AND t - prev_t <= ?
                               AND t >= ? AND prev_t <= ?""", (house, MAX_GAP, t - margin, t + margin)).fetchall()
        if not snaps:
            res["outside"] += 1
            continue
        ts = [s[0] for s in snaps]
        marks = ",".join("?" * len(ts))
        sold, partial, cancelled, expired = con.execute(
            f"""SELECT COALESCE(SUM(sold), 0), COALESCE(SUM(partial), 0), COALESCE(SUM(cancelled), 0),
                       COALESCE(SUM(expired), 0) FROM api_item_hour WHERE house=? AND item_id=? AND t IN ({marks})""",
            [house, item, *ts]).fetchone()
        est = sold + partial
        cov = min(qty, est)
        res["sales"] += 1
        res["units"] += qty
        res["covered"] += cov
        for snap_t in ts:                 # lo estimado de cada intervalo y objeto, una sola vez
            if (snap_t, item) not in seen_est:
                seen_est.add((snap_t, item))
                r = con.execute("SELECT COALESCE(sold, 0) + COALESCE(partial, 0) FROM api_item_hour WHERE house=? AND t=? AND item_id=?",
                                (house, snap_t, item)).fetchone()
                res["est_sold"] += r[0] if r else 0
        res["detail"].append({"t": t, "item": item, "qty": qty, "sold": est, "cancelled": cancelled,
                              "expired": expired, "covered": cov})
    res["coverage"] = res["covered"] / res["units"] if res["units"] else None
    res["share"] = res["covered"] / res["est_sold"] if res["est_sold"] else None
    res["turnover"] = turnover(con, house)
    if save:
        con.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"api_calibration_{house}", json.dumps(
            {"sales": res["sales"], "coverage": res["coverage"], "share": res["share"],
             "turnover": res["turnover"], "t": int(time.time())})))
        con.commit()
    con.close()
    return res


def has_variants(con, house):
    """¿La última foto guardó variantes de equipo? Un archivo de antes de la fase 5 (o un panel sin
    reiniciar) no las tiene, y entonces no se sabe qué equipo mezcla productos distintos."""
    return con.execute("SELECT 1 FROM api_var WHERE house=? LIMIT 1", (house,)).fetchone() is not None


def variant_items(con, house):
    """Objetos de la última foto con más de una variante a la venta: su precio por número de objeto
    mezcla productos distintos y no sirve para revender."""
    return {r[0] for r in con.execute(
        """SELECT l.item_id FROM api_live l LEFT JOIN api_var v ON v.house = l.house AND v.auction_id = l.auction_id
           WHERE l.house=? GROUP BY l.item_id HAVING COUNT(DISTINCT COALESCE(v.var, '')) > 1""", (house,))}


def ladders(con, house):
    """Lista de precios de la última foto: {objeto: [(precio por unidad, unidades), …]} de barato a caro,
    juntando las subastas al mismo precio. Sin las que solo tienen puja."""
    out = defaultdict(list)
    for item, price, qty in con.execute(
            """SELECT item_id, price, SUM(qty) FROM api_live WHERE house=? AND price IS NOT NULL
               GROUP BY item_id, price ORDER BY item_id, price""", (house,)):
        out[item].append((price, qty))
    return dict(out)


def neutral_house(con, house):
    """Casa neutral (Aguasnegras) del mismo reino que `house`: (casa, nombre, hora de su última foto), o None."""
    r = con.execute("SELECT m.key FROM api_houses h JOIN markets m USING (market_id) WHERE h.house=?", (house,)).fetchone()
    if not r or "-" not in r[0]:
        return None
    n = con.execute("""SELECT h.house, h.name FROM api_houses h JOIN markets m USING (market_id)
                       WHERE m.key=? AND h.house<>?""", (r[0].rsplit("-", 1)[0] + "-Neutral", house)).fetchone()
    if not n:
        return None
    return n[0], n[1], con.execute("SELECT MAX(t) FROM api_snaps WHERE house=?", (n[0],)).fetchone()[0]


BARGAIN_DISCOUNT = 0.30          # ganga: al menos un 30 % por debajo de su precio habitual…
BARGAIN_MIN_SAVING = 5000        # …y 50 platas de diferencia en total, ya sin la comisión
BARGAIN_MIN_DAYS = 3             # días de precio para saber cuál es el habitual
BARGAIN_CUT = 0.05
BARGAIN_SHARE = 0.5              # de lo que se vende al día, lo que cuento que te llevas tú


def bargains(con, house, now=None, top=10):
    """Gangas de la última foto: subastas que han aparecido en ella (first_t = la foto) muy por debajo del
    precio habitual del objeto (mediana de lo más barato de cada uno de los 7 días anteriores). No cuenta si ya
    había subastas viejas a ese precio (entonces es el precio nuevo, no una ganga), ni el equipo con
    variantes (mientras no haya variantes guardadas, ningún objeto que no se apile), ni lo que no tiene
    ventas estimadas. La cantidad no pasa de la mitad de lo que se vende al día. Devuelve {"t", "items": [{id, name, quality, price, max, qty,
    usual, discount, saving}]}, de más a menos diferencia. `saving` es lo que quedaría al revender todo
    al precio habitual, quitando la comisión: un tope, no una promesa."""
    t = con.execute("SELECT MAX(t) FROM api_snaps WHERE house=?", (house,)).fetchone()[0]
    out = {"t": t, "items": []}
    mk = con.execute("SELECT market_id FROM api_houses WHERE house=?", (house,)).fetchone()
    if t is None or not mk:
        return out
    fresh = defaultdict(list)
    for item, price, qty in con.execute(
            """SELECT item_id, price, SUM(qty) FROM api_live WHERE house=? AND first_t=? AND price IS NOT NULL
               GROUP BY item_id, price ORDER BY item_id, price""", (house, t)):
        fresh[item].append((price, qty))
    if not fresh:
        return out
    hist = defaultdict(list)
    # lo habitual es lo más barato de cada día (a ese precio se vende), no el valor de mercado
    for item, mv in con.execute("""SELECT item_id, COALESCE(min_low, mv) FROM daily WHERE market_id=? AND day>=? AND day<?
                                   AND COALESCE(min_low, mv) IS NOT NULL""", (mk[0], _day(t - 7 * 86400), _day(t))):
        hist[item].append(mv)
    variants = variant_items(con, house)
    has_var = has_variants(con, house)
    single = set() if has_var else {r[0] for r in con.execute(
        f"SELECT item_id FROM items WHERE COALESCE(stack, 1) <= 1 AND item_id IN ({','.join('?' * len(fresh))})",
        list(fresh))}
    old_min = dict(con.execute(
        "SELECT item_id, MIN(price) FROM api_live WHERE house=? AND first_t<? AND price IS NOT NULL GROUP BY item_id",
        (house, t)))
    sold, _ = sold_rates(con, house, now or t)
    # sin comprobar, las vendidas cuentan recolocaciones: se rebajan hasta que la casa no salga vendida
    # más de una vez al día (sirve para no proponer cantidades disparatadas, no para saber cuánto se vende)
    turn = None if is_calibrated(con, house) else turnover(con, house, now or t)
    k_sold = 1 / turn if turn and turn > CALIB_MAX_TURNOVER else 1
    rows = []
    for item, lad in fresh.items():
        h = sorted(hist.get(item, ()))
        if len(h) < BARGAIN_MIN_DAYS or item in variants or item in single or sold.get(item, 0) <= 0:
            continue
        usual = h[len(h) // 2] if len(h) % 2 else (h[len(h) // 2 - 1] + h[len(h) // 2]) / 2
        limit = usual * (1 - BARGAIN_DISCOUNT)
        if item in old_min and old_min[item] <= limit:
            continue                                   # ya estaba así de barato antes de esta foto
        cap = max(1, int(sold[item] * k_sold * BARGAIN_SHARE))
        cheap = []
        for p, q in lad:
            if p > limit or cap <= 0:
                break
            cheap.append((p, min(q, cap)))
            cap -= q
        qty = sum(q for _, q in cheap)
        if not qty:
            continue
        cost = sum(p * q for p, q in cheap)
        saving = usual * (1 - BARGAIN_CUT) * qty - cost
        if saving < BARGAIN_MIN_SAVING:
            continue
        rows.append({"id": item, "price": cost / qty, "max": cheap[-1][0], "qty": qty, "usual": usual,
                     "discount": 1 - cost / qty / usual, "saving": saving, "sold": sold.get(item)})
    rows.sort(key=lambda r: -r["saving"])
    rows = rows[:top]
    if rows:
        names = {i: (n, q) for i, n, q in con.execute(
            f"SELECT item_id, name, quality FROM items WHERE item_id IN ({','.join('?' * len(rows))})",
            [r["id"] for r in rows])}
        for r in rows:
            n, q = names.get(r["id"], (None, None))
            r["name"], r["quality"] = n or f"objeto {r['id']}", q
    out["items"] = rows
    return out


def latest_prices(con, house):
    """Precio de la última foto: (t, {objeto: (min, mv, qty, n, d110, d125, d150, d200)})."""
    t = con.execute("SELECT MAX(t) FROM api_snaps WHERE house=?", (house,)).fetchone()[0]
    if t is None:
        return None, {}
    return t, {r[0]: r[1:] for r in con.execute(
        """SELECT item_id, min, mv, qty, n, d110, d125, d150, d200 FROM api_item_hour
           WHERE house=? AND t=? AND min IS NOT NULL""", (house, t))}


QUALITY = {"POOR": 0, "COMMON": 1, "UNCOMMON": 2, "RARE": 3, "EPIC": 4, "LEGENDARY": 5, "ARTIFACT": 6, "HEIRLOOM": 7}


def fill_names(con, client, limit=2000, clock=time.time):
    """Pide a la ruta de objetos (static-forever-eu) los que no tienen nombre. Lo que da 404 se apunta en
    api_missing y no se vuelve a pedir. Devuelve {"asked", "named"}."""
    ids = [r[0] for r in con.execute(
        """SELECT item_id FROM items WHERE name IS NULL AND item_id NOT IN (SELECT item_id FROM api_missing)
           ORDER BY item_id LIMIT ?""", (limit,))]
    named = 0
    for i in ids:
        st, _, d = client.get(f"/data/wow/item/{i}", namespace=STATIC_NAMESPACE, locale="es_ES")
        if st == 200 and d and d.get("name"):
            con.execute("UPDATE items SET name=?, quality=COALESCE(?, quality), vendor_sell=COALESCE(?, vendor_sell) WHERE item_id=?",
                        (house_name(d["name"]), QUALITY.get((d.get("quality") or {}).get("type")), d.get("sell_price"), i))
            named += 1
        elif st == 404:
            con.execute("INSERT OR REPLACE INTO api_missing VALUES (?,?)", (i, int(clock())))
        else:
            break                       # otro error: se reintenta otro día
        con.commit()                    # no dejar la escritura abierta mientras se pregunta a la red
    con.commit()
    return {"asked": len(ids), "named": named}


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
            except (ApiError, OSError, ValueError, sqlite3.Error) as e:
                msg = str(e) if isinstance(e, (ApiError, sqlite3.Error)) else type(e).__name__
                log(f"casa {h}: error: {msg}")
                out.append({"house": h, "status": "error", "error": msg})
    finally:
        con.close()
    return out


def maintenance(archive, client, now=None, log=_log, names_limit=2000, plan_db=None):
    """Una vez al día: resume en api_band_week lo que tiene más de 14 días, pide nombres que falten y,
    con el SQLite del plan (plan_db), calibra las ventas estimadas con tu libro.
    Devuelve lo hecho, o None si hoy ya se hizo."""
    now = now or time.time()
    day = _day(now)
    con = open_api(archive)
    try:
        row = con.execute("SELECT value FROM meta WHERE key='api_maintenance'").fetchone()
        if row and row[0] == day:
            return None
        n = rollup_api(con, now)
        try:
            names = fill_names(con, client, names_limit) if client else {"asked": 0, "named": 0}
        except (ApiError, OSError, ValueError) as e:
            names = {"asked": 0, "named": 0, "error": str(e) if isinstance(e, ApiError) else type(e).__name__}
        con.execute("INSERT OR REPLACE INTO meta VALUES ('api_maintenance', ?)", (day,))
        con.commit()
        houses = [r[0] for r in con.execute("SELECT house FROM api_houses")]
    finally:
        con.close()
    if plan_db and os.path.exists(plan_db):
        for h in houses:
            try:
                calibrate(archive, plan_db, h)
            except sqlite3.Error as e:
                log(f"calibración casa {h}: {e}")
    if n or names.get("named"):
        log(f"mantenimiento: {n} filas por hora resumidas; {names.get('named', 0)} nombres nuevos")
    return {"rolled": n, **names}


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
    ap.add_argument("--calibrar", action="store_true",
                    help="comparar las ventas estimadas con tus ventas reales del libro (work/oroboros.sqlite) y salir")
    a = ap.parse_args()
    archive = a.archive or os.path.join(a.work, "archivo.sqlite")
    houses = [int(x) for x in a.casas.split(",") if x.strip()]
    if a.importar:
        n = import_dir(archive, a.importar, a.reino, log=_log)
        _log(f"{n} fotos importadas en {archive}")
        return
    plan_db = os.path.join(a.work, "oroboros.sqlite")
    if a.calibrar:
        for h in houses:
            r = calibrate(archive, plan_db, h)
            cov = "—" if r["coverage"] is None else f"{r['coverage'] * 100:.0f} %"
            share = "—" if r["share"] is None else f"{r['share'] * 100:.0f} %"
            print(f"Casa {h}: {r['sales']} ventas tuyas con fotos ({r['units']:.0f} u.), la estimación ve {r['covered']:.0f} "
                  f"como vendidas → cobertura {cov}; tu parte de lo vendido estimado {share}; "
                  f"{r['outside']} ventas sin fotos.")
            if r["turnover"] is not None:
                print(f"  Rotación: la casa saldría vendida {r['turnover']:.1f} veces al día"
                      + (" — demasiado: se cuentan recolocaciones como ventas, y el plan no usa estas cifras."
                         if r["turnover"] > CALIB_MAX_TURNOVER else "."))
            for d in r["detail"]:
                if d["covered"] < d["qty"]:
                    print(f"   {time.strftime('%d/%m %H:%M', time.localtime(d['t']))} objeto {d['item']}: vendiste {d['qty']:.0f}, "
                          f"vendidas {d['sold']:.0f}, canceladas {d['cancelled']:.0f}, caducadas {d['expired']:.0f}")
        return
    creds = load_creds(a.work)
    if not creds:
        sys.exit("Faltan las credenciales: BNET_CLIENT_ID / BNET_CLIENT_SECRET o work/bnet.env")
    client = Client(creds, cache_dir=os.path.join(a.work, "api"))
    if a.una_vez:
        res = run_once(archive, client, houses, a.reino)
        maintenance(archive, client, plan_db=plan_db)
        sys.exit(1 if any(r["status"] == "error" for r in res) else 0)
    _log(f"Descargando las casas {houses} cada hora (minuto 25). Ctrl+C para parar.")
    try:
        while True:
            try:
                res = run_once(archive, client, houses, a.reino)
                maintenance(archive, client, plan_db=plan_db)
                wait = wait_after(res, time.time())
            except Exception as e:          # que nada pare la descarga de cada hora
                _log(f"error: {type(e).__name__}; reintento en 5 min")
                wait = 300
            time.sleep(wait)
    except KeyboardInterrupt:
        _log("Parado.")


if __name__ == "__main__":
    main()
