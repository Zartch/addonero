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
    r = con.execute("SELECT market, COUNT(*) n FROM scans GROUP BY market ORDER BY n DESC LIMIT 1").fetchone()
    return r[0] if r else None


def analyze(archive_path, market=None):
    """{item_id: [6 dicts por franja]} con gone_total_h, gone_cheap_h, price_med, n, days, ok."""
    con = sqlite3.connect(archive_path)
    market = market or pick_market(con)
    if market is None:
        return {}
    acc = defaultdict(lambda: [{"total": 0.0, "cheap": 0.0, "secs": 0, "n": 0, "days": set(), "prices": []}
                               for _ in BANDS])
    prev = {}
    for item, t, mn, qty, cheap, cheap_prev in con.execute(
            "SELECT item_id, t, min, qty, cheap, cheap_prev FROM scans WHERE market=? ORDER BY item_id, t", (market,)):
        a = acc[item]
        if mn is not None:
            a[band_of(t)]["prices"].append(mn)
        p = prev.get(item)
        prev[item] = (t, qty, cheap)
        if not p or t - p[0] > MAX_GAP_H * 3600 or t <= p[0]:
            continue
        gone_total = max(0, (p[1] or 0) - (qty or 0))
        gone_cheap = max(0, (p[2] or 0) - (cheap_prev or 0))
        span = t - p[0]
        for b, secs, day in _split(p[0], t):
            f = secs / span
            a[b]["total"] += gone_total * f
            a[b]["cheap"] += gone_cheap * f
            a[b]["secs"] += secs
            a[b]["n"] += 1
            a[b]["days"].add(day)
    con.close()
    out = {}
    for item, bands in acc.items():
        res = []
        for i, x in enumerate(bands):
            hours = x["secs"] / 3600
            res.append({
                "band": i,
                "gone_total_h": round(x["total"] / hours, 2) if hours else None,
                "gone_cheap_h": round(x["cheap"] / hours, 2) if hours else None,
                "price_med": statistics.median(x["prices"]) if x["prices"] else None,
                "n": x["n"], "days": len(x["days"]),
                "ok": x["n"] >= MIN_N and len(x["days"]) >= MIN_DAYS,
            })
        out[item] = res
    return out


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
    n_scans = con.execute("SELECT COUNT(DISTINCT t) FROM scans").fetchone()[0]
    print(f"{n_scans} escaneos archivados, {len(data)} objetos.")
    items = [a.item] if a.item else sorted(
        data, key=lambda i: -sum(b["gone_cheap_h"] or 0 for b in data[i]))[:a.top]
    print("objeto     " + "".join(f"{band_label(i):>12}" for i in range(len(BANDS))))
    for i in items:
        bands = data.get(i)
        if not bands:
            continue
        cell = lambda b: (f"{b['gone_total_h']:.1f}/{b['gone_cheap_h']:.1f}{'' if b['ok'] else '?'}"
                          if b["gone_total_h"] is not None else "—")
        print(f"{i:<10} " + "".join(f"{cell(b):>12}" for b in bands))
    print("celdas: desaparecidas por hora total/baratas; «?» = menos de 3 mediciones en 2 días.")


if __name__ == "__main__":
    main()
