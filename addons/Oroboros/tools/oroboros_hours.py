#!/usr/bin/env python3
"""
Oroboros: análisis por franjas horarias del archivo de escaneos (docs/franjas-horarias.md).

Entre dos escaneos seguidos (como mucho 6 h) se cuentan dos cosas que desaparecen:
  - total:  qty anterior − qty actual
  - baratas: cheap anterior − cheap_prev actual (mismo umbral barato en los dos escaneos)
Si sube, cuenta 0 (publicaciones nuevas). Lo desaparecido se reparte entre las franjas
que cubre el intervalo, en proporción al tiempo.

Uso:
  python oroboros_hours.py work/archivo.sqlite [--item ID] [--market M]
"""
import argparse
import datetime
import sqlite3
import statistics
import sys
from collections import defaultdict

BANDS = [(0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24)]
MAX_GAP_H = 6          # intervalo máximo entre escaneos para medir
MIN_N, MIN_DAYS = 3, 2  # una franja es fiable con >= 3 mediciones en >= 2 días


def band_of(ts):
    return datetime.datetime.fromtimestamp(ts).hour // 4


def _split(t0, t1):
    """Reparte el intervalo [t0, t1) por franjas: [(franja, segundos, día)], en hora local."""
    out, cur = [], t0
    while cur < t1:
        d = datetime.datetime.fromtimestamp(cur)
        b = d.hour // 4
        start = d.replace(hour=b * 4, minute=0, second=0, microsecond=0)
        nxt = int((start + datetime.timedelta(hours=4)).timestamp())
        end = min(nxt, t1)
        out.append((b, end - cur, d.date().isoformat()))
        cur = end
    return out


def pick_market(con):
    r = con.execute("""SELECT m.key, COUNT(*) n FROM scans s JOIN markets m USING (market_id)
                       GROUP BY m.key ORDER BY n DESC LIMIT 1""").fetchone()
    return r[0] if r else None


OBS_SQL = """SELECT o.item_id, s.t, o.min, o.qty, o.cheap, o.cheap_prev
             FROM observations o JOIN scans s USING (scan_id) JOIN markets m USING (market_id)
             WHERE m.key=? ORDER BY o.item_id, s.t"""


def week_of(ts):
    y, w, _ = datetime.datetime.fromtimestamp(ts).isocalendar()
    return f"{y}-W{w:02d}"


def contributions(rows):
    """Lo que aporta cada escaneo a las franjas. rows: (item, t, min, qty, cheap, cheap_prev) ordenadas
    por objeto y hora. Produce dos tipos de tuplas:
      ("gone", item, week, band, gone_total, gone_cheap, secs, day)  por cada trozo de intervalo válido
      ("price", item, week, band, min)                               por cada escaneo con precio
    `week` es la semana ISO del escaneo inicial del intervalo (o del escaneo, para el precio)."""
    prev = {}
    for item, t, mn, qty, cheap, cheap_prev in rows:
        if mn is not None:
            yield ("price", item, week_of(t), band_of(t), mn)
        p = prev.get(item)
        prev[item] = (t, qty, cheap)
        if not p or t - p[0] > MAX_GAP_H * 3600 or t <= p[0]:
            continue
        gone_total = max(0, (p[1] or 0) - (qty or 0))
        gone_cheap = max(0, (p[2] or 0) - (cheap_prev or 0))
        span, wk = t - p[0], week_of(p[0])
        for b, secs, day in _split(p[0], t):
            f = secs / span
            yield ("gone", item, wk, b, gone_total * f, gone_cheap * f, secs, day)


def analyze(archive_path, market=None):
    """{item_id: [6 dicts por franja]} con gone_total_h, gone_cheap_h, price_med, n, days, ok.
    Junta los escaneos en bruto (8 semanas) con los resúmenes semanales (`weekly_band`)."""
    con = sqlite3.connect(archive_path)
    market = market or pick_market(con)
    if market is None:
        return {}
    acc = defaultdict(lambda: [{"total": 0.0, "cheap": 0.0, "secs": 0.0, "n": 0, "days": set(), "days_old": 0,
                                "week_prices": defaultdict(list), "week_meds": []} for _ in BANDS])
    for c in contributions(con.execute(OBS_SQL, (market,))):
        a = acc[c[1]][c[3]]
        if c[0] == "price":
            a["week_prices"][c[2]].append(c[4])
        else:
            a["total"] += c[4]; a["cheap"] += c[5]; a["secs"] += c[6]; a["n"] += 1; a["days"].add(c[7])
    for item, band, gt, gc, hours, n, days, pmed in con.execute(
            """SELECT w.item_id, w.band, w.gone_total, w.gone_cheap, w.hours, w.n, w.days, w.price_med
               FROM weekly_band w JOIN markets m USING (market_id) WHERE m.key=?""", (market,)):
        a = acc[item][band]
        a["total"] += gt or 0; a["cheap"] += gc or 0; a["secs"] += (hours or 0) * 3600
        a["n"] += n or 0; a["days_old"] += days or 0
        if pmed is not None:
            a["week_meds"].append(pmed)
    api = _api_bands(con, market)
    con.close()
    out = {}
    for item, bands in acc.items():
        res = []
        for i, x in enumerate(bands):
            hours = x["secs"] / 3600
            meds = x["week_meds"] + [statistics.median(v) for v in x["week_prices"].values()]
            days = len(x["days"]) + x["days_old"]
            res.append({
                "band": i,
                "gone_total_h": round(x["total"] / hours, 2) if hours else None,
                "gone_cheap_h": round(x["cheap"] / hours, 2) if hours else None,
                "price_med": statistics.median(meds) if meds else None,
                "n": x["n"], "days": days,
                "ok": x["n"] >= MIN_N and days >= MIN_DAYS, "src": "obs",
            })
        out[item] = res
    # la API (tools/oroboros_api.py) gana en cada franja donde tiene mediciones suficientes:
    # total = todo lo que desaparece; «baratas» = vendidas (incluidas las compras parciales)
    for item, bands in api.items():
        res = out.setdefault(item, [{"band": i, "gone_total_h": None, "gone_cheap_h": None, "price_med": None,
                                     "n": 0, "days": 0, "ok": False, "src": "obs"} for i in range(len(BANDS))])
        for i, b in enumerate(bands):
            if b["n"] >= MIN_N and b["days"] >= MIN_DAYS and b["hours"] > 0:
                gone = b["sold"] + b["partial"] + b["expired"] + b["cancelled"]
                res[i] = {"band": i, "gone_total_h": round(gone / b["hours"], 2),
                          "gone_cheap_h": round((b["sold"] + b["partial"]) / b["hours"], 2),
                          "price_med": b["price_med"], "n": b["n"], "days": b["days"], "ok": True, "src": "api"}
    return out


def _api_bands(con, market):
    """Franjas de la casa de la API asociada al mercado ({} si no hay)."""
    try:
        import oroboros_api
    except ImportError:
        return {}
    house = oroboros_api.house_for_market(con, market)
    return oroboros_api.band_stats(con, house) if house is not None else {}


def summary(bands):
    """Mejor franja para vender (más baratas desaparecidas por hora) y la más barata, solo con franjas fiables."""
    ok = [b for b in bands if b["ok"] and b["gone_cheap_h"] is not None]
    if not ok:
        return None
    sell = max(ok, key=lambda b: b["gone_cheap_h"])
    avg = statistics.mean(b["gone_cheap_h"] for b in ok)
    priced = [b for b in ok if b["price_med"]]
    cheap_band = min(priced, key=lambda b: b["price_med"]) if priced else None
    mean_price = statistics.mean(b["price_med"] for b in priced) if priced else None
    tot = sum(b["gone_total_h"] or 0 for b in ok)
    return {
        "sell_band": sell["band"], "sell_rate": sell["gone_cheap_h"], "avg_rate": avg,
        "cheap_band": cheap_band["band"] if cheap_band else None,
        "cheap_pct": (1 - cheap_band["price_med"] / mean_price) if cheap_band and mean_price else None,
        "cheap_share": (sum(b["gone_cheap_h"] for b in ok) / tot) if tot else None,
    }


def band_label(i):
    a, b = BANDS[i]
    return f"{a}–{b} h"


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--market")
    ap.add_argument("--item", type=int)
    ap.add_argument("--top", type=int, default=15, help="objetos a mostrar (por baratas desaparecidas)")
    a = ap.parse_args()
    data = analyze(a.archive, a.market)
    con = sqlite3.connect(a.archive)
    n_scans = con.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    print(f"{n_scans} escaneos archivados, {len(data)} objetos.")
    items = [a.item] if a.item else sorted(
        data, key=lambda i: -sum(b["gone_cheap_h"] or 0 for b in data[i]))[:a.top]
    print("objeto     " + "".join(f"{band_label(i):>18}" for i in range(len(BANDS))))
    for i in items:
        bands = data.get(i)
        if not bands:
            continue
        cell = lambda b: (f"{b['gone_total_h']:.0f}/{b['gone_cheap_h']:.0f}{'' if b['ok'] else '?'}"
                          if b["gone_total_h"] is not None else "—")
        print(f"{i:<10} " + "".join(f"{cell(b):>18}" for b in bands))
    print("celdas: desaparecidas por hora total/baratas; «?» = menos de 3 mediciones en 2 días.")


if __name__ == "__main__":
    main()
