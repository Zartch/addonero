#!/usr/bin/env python3
"""
Oroboros: resumen de precios por objeto al estilo CamelCamelCamel (fase 2, docs/hoja-de-ruta.md).

Calcula desde el archivo (`daily` y las franjas) unas pocas cifras por objeto y las escribe en
`Oroboros/Resumen.lua`, que el addon carga al entrar o con /reload (solo lectura: no engorda Oroboros.lua).

Cadena por objeto, campos separados por «;» (vacío = sin dato), cobre entero, días AAAAMMDD:
  hoy;med7;med30;med90;min;diaMin;max;diaMax;franjaVenta;franjaBarata;semanas;dias;ultimoDia
  semanas = 13 medias semanales (ISO) y dias = 14 valores diarios, del más antiguo al más reciente,
  separados por comas. El precio seguido es el valor de mercado diario (daily.mv).

Uso:
  python oroboros_summary.py work/archivo.sqlite [--out Oroboros/Resumen.lua]
"""
import argparse
import datetime
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "Oroboros", "Resumen.lua")
ACTIVE_DAYS = 90
HOUR_MIN_DIFF = 0.10       # mismas condiciones que el plan para mencionar una franja


def _r(x):
    return "" if x is None else str(int(x + 0.5))


def _mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


def _ymd(day):
    return day.replace("-", "")


def item_summary(rows, bands, today):
    """rows: [(día 'AAAA-MM-DD', mv, min_low, min_high)] ordenadas por día. Devuelve la cadena o None
    si no hay datos en los últimos 90 días."""
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return None
    days = {datetime.date.fromisoformat(r[0]): r[1] for r in rows}
    if max(days) < today - datetime.timedelta(days=ACTIVE_DAYS - 1):
        return None
    last = max(days)
    since = lambda n: [v for d, v in days.items() if today - datetime.timedelta(days=n - 1) <= d <= today]
    lo_d = min(days, key=lambda d: (days[d], d))
    hi_d = max(days, key=lambda d: (days[d], -d.toordinal()))
    sell = cheap = None
    if bands:
        import oroboros_hours
        s = oroboros_hours.summary(bands)
        if s:
            if s["avg_rate"] and s["sell_rate"] >= s["avg_rate"] * (1 + HOUR_MIN_DIFF):
                sell = s["sell_band"]
            if s["cheap_band"] is not None and (s["cheap_pct"] or 0) >= HOUR_MIN_DIFF:
                cheap = s["cheap_band"]
    weeks = []
    for k in range(12, -1, -1):
        y, w, _ = (today - datetime.timedelta(weeks=k)).isocalendar()
        weeks.append(_r(_mean([v for d, v in days.items() if d.isocalendar()[:2] == (y, w)])))
    daily = [_r(days.get(today - datetime.timedelta(days=k))) for k in range(13, -1, -1)]
    fields = [_r(days[last]), _r(_mean(since(7))), _r(_mean(since(30))), _r(_mean(since(90))),
              _r(days[lo_d]), lo_d.strftime("%Y%m%d"), _r(days[hi_d]), hi_d.strftime("%Y%m%d"),
              "" if sell is None else str(sell), "" if cheap is None else str(cheap),
              ",".join(weeks), ",".join(daily), last.strftime("%Y%m%d")]
    return ";".join(fields)


def lua_str(s):
    out = []
    for ch in str(s):
        o = ord(ch)
        if ch in '"\\':
            out.append("\\" + ch)
        elif 32 <= o < 127:
            out.append(ch)
        else:
            out.extend(f"\\{b:03d}" for b in ch.encode("utf-8"))
    return '"' + "".join(out) + '"'


def write_resumen(archive_path, out_path, today=None):
    """Escribe Resumen.lua con un apartado por mercado. Devuelve {"items": n, "bytes": tamaño}."""
    import oroboros_hours
    today = today or datetime.date.today()
    con = sqlite3.connect(archive_path)
    since = (today - datetime.timedelta(days=ACTIVE_DAYS - 1)).isoformat()
    lines = [f"-- Generado por tools/oroboros_summary.py el {datetime.datetime.now():%d/%m/%Y %H:%M}. No editar.",
             f"OroborosResumen = {{ v = 1, t = {int(time.time())}, markets = {{"]
    n = 0
    for mid, key in con.execute("SELECT market_id, key FROM markets ORDER BY key").fetchall():
        hours = oroboros_hours.analyze(archive_path, key)
        active = [r[0] for r in con.execute(
            "SELECT DISTINCT item_id FROM daily WHERE market_id=? AND day >= ? ORDER BY item_id", (mid, since))]
        lines.append(f"[{lua_str(key)}] = {{")
        for item in active:
            rows = con.execute("SELECT day, mv, min_low, min_high FROM daily WHERE market_id=? AND item_id=? ORDER BY day",
                               (mid, item)).fetchall()
            s = item_summary(rows, hours.get(item), today)
            if s:
                lines.append(f"[{int(item)}] = {lua_str(s)},")
                n += 1
        lines.append("},")
    lines.append("} }")
    con.close()
    text = "\n".join(lines) + "\n"
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return {"items": n, "bytes": len(text.encode("utf-8"))}


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive")
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()
    r = write_resumen(a.archive, a.out)
    print(f"Resumen → {os.path.abspath(a.out)}: {r['items']} objetos, {r['bytes'] / 1024:.0f} KB.")


if __name__ == "__main__":
    main()
