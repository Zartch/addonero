#!/usr/bin/env python3
"""
Oroboros: dónde farmear (docs/farmeo.md). Estimación inicial con AzerothCore, solo de materiales.
Lo medido en el juego manda sobre esta estimación (se combina en el plan).

Uso:
  python oroboros_farm.py --descargar              # baja AzerothCore a work/fuentes/azerothcore (≈45 MB)
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AC_DIR = os.path.normpath(os.path.join(HERE, "..", "work", "fuentes", "azerothcore"))

# Suposiciones de partida (docs/farmeo.md); lo medido las sustituye
KPH_BASE = 40               # muertes por hora a tu mismo nivel
KPH_PER_LEVEL = 0.10        # +10 % por cada nivel por debajo
KPH_MAX_FACTOR = 2.0
SPAWN_FACTOR = 0.5          # no te encuentras todas las apariciones
ELITE_SHARE = 0.30          # subzona con ≥ 30 % de élites: «zona de élites», fuera
LEVEL_ABOVE, LEVEL_BELOW = 1, 12
GPH_SPREAD = 0.30           # rango ±30 % de la estimación
CAPITALS = {1519, 1537, 1657, 1637, 1638, 1497}
CELL = 400                  # cuadrícula de agrupación, en metros del continente (AzerothCore no trae subzonas)
CITY_SHARE = 0.20           # cuadrícula con ≥ 20 % de PNJ con servicios: ciudad o campamento, fuera
GATHER_NPH = 30             # nodos por hora en un mapa con nodos densos
DENSE_NODES = 200           # nodos conocidos de una profesión a partir de los que un mapa es «denso»
MATERIAL_CLASSES = {0, 5, 7}    # consumibles, componentes, artículos de comercio
NOT_ATTACKABLE = 0x2 | 0x100 | 0x02000000


def _allowed(it):
    if not it:
        return False
    if it["class"] == 12:           # objetos de misión
        return False
    return it["quality"] == 0 or it["class"] in MATERIAL_CLASSES


def _unit(item, it, prices):
    if it["quality"] == 0:
        return it["sell"] or 0
    p = prices.get(item)
    if p and p.get("value"):
        return p["value"]
    return it["sell"] or 0


def loot_qty(ac, table, entry, depth=0, _memo=None):
    """{itemID: cantidad esperada} por tirada de esa tabla de botín (con grupos y referencias)."""
    _memo = {} if _memo is None else _memo
    key = (id(table), entry)
    if key in _memo:
        return _memo[key]
    out = {}
    rows = [r for r in table.get(entry, []) if r["mode"] & 1 and not r["quest"] and r["chance"] >= 0]
    groups = {}
    for r in rows:
        groups.setdefault(r["group"], []).append(r)
    for g, rs in groups.items():
        if g == 0:
            probs = [(r, r["chance"] / 100) for r in rs]
        else:
            explicit = [r for r in rs if r["chance"] > 0]
            zeros = [r for r in rs if r["chance"] == 0]
            rest = max(0.0, 100 - sum(r["chance"] for r in explicit))
            probs = [(r, r["chance"] / 100) for r in explicit] + [(r, rest / 100 / len(zeros)) for r in zeros]
        for r, p in probs:
            if p <= 0:
                continue
            if r["reference"] and depth < 5:
                sub = loot_qty(ac, ac["refs"], r["reference"], depth + 1, _memo)
                for it, q in sub.items():
                    out[it] = out.get(it, 0) + p * r["max"] * q
            elif not r["reference"]:
                out[r["item"]] = out.get(r["item"], 0) + p * (r["min"] + r["max"]) / 2
    _memo[key] = out
    return out


def mob_value(ac, entry, prices, skinning=False):
    """Valor por muerte: oro medio + materiales (el equipo no se estima). {copper, gold, qty}."""
    t = ac["templates"][entry]
    qty = {}
    for table, lid in ((ac["loot"], t["lootid"]), (ac["skin"], t["skinloot"] if skinning else 0)):
        if lid:
            for it, q in loot_qty(ac, table, lid).items():
                if _allowed(ac["items"].get(it)):
                    qty[it] = qty.get(it, 0) + q
    gold = ((t["mingold"] or 0) + (t["maxgold"] or 0)) / 2
    copper = gold + sum(q * _unit(it, ac["items"][it], prices) for it, q in qty.items())
    return {"copper": copper, "gold": gold, "qty": qty}


def _sell(ac, qty_h, prices):
    """Valor por hora de cada objeto: lo que pasa del volumen diario de la subasta se vende al vendedor.
    Devuelve ([(itemID, cantidad, valor)] de más a menos valor, saturado)."""
    saturated, items_h = False, []
    for it, q in qty_h.items():
        info = ac["items"].get(it)
        if not info:
            continue
        unit = _unit(it, info, prices)
        vol = (prices.get(it) or {}).get("vol")
        if vol is not None and info["quality"] > 0 and q > vol:
            value = vol * unit + (q - vol) * (info["sell"] or 0)
            saturated = True
        else:
            value = q * unit
        items_h.append((it, q, value))
    items_h.sort(key=lambda x: -x[2])
    return items_h, saturated


def node_qty(ac, name):
    """{itemID: cantidad esperada} por nodo con ese nombre, o None si AzerothCore no lo conoce."""
    lids = ac["nodes"].get(name)
    if not lids:
        return None
    qty = {}
    for lid in lids:            # varios botines con el mismo nombre: la media
        for it, q in loot_qty(ac, ac["goloot"], lid).items():
            qty[it] = qty.get(it, 0) + q / len(lids)
    return qty


def gathering(gm, ac, prices, profs):
    """Mapas de recolección ordenados por oro por hora. gm: gathermate.load; profs: {"herb", "mine"}.
    Nodos por hora: GATHER_NPH, menos si el mapa tiene pocos nodos conocidos. El nivel de profesión no se comprueba."""
    out = []
    for kind in sorted(profs):
        for mapid, nodes in gm.get(kind, {}).items():
            total = sum(nodes.values())
            nph = GATHER_NPH * min(1.0, total / DENSE_NODES)
            qty_h, unvalued = {}, []
            for nid, n in nodes.items():
                name = gm["names"].get(nid, str(nid))
                q = node_qty(ac, name)
                if q is None:
                    unvalued.append(name)
                    continue
                for it, x in q.items():
                    qty_h[it] = qty_h.get(it, 0) + nph * n / total * x
            items_h, saturated = _sell(ac, qty_h, prices)
            out.append({"map": mapid, "kind": kind, "nodes": total, "nph": nph,
                        "gph": sum(v for _, _, v in items_h), "top_items": items_h[:3],
                        "unvalued": sorted(unvalued), "saturated": saturated})
    out.sort(key=lambda r: -r["gph"])
    return out


def _in_pool(t, zone, mapid):
    return (t and t["npcflag"] == 0 and (t["lootid"] or t["maxgold"]) and zone not in CAPITALS
            and mapid in (0, 1) and t["type"] != 8 and not (t["unit_flags"] or 0) & NOT_ATTACKABLE)


def estimate(ac, prices, level, skinning=False):
    """Subzonas ordenadas por oro por hora estimado para un personaje de ese nivel."""
    areas = {}
    for entry, mapid, zone, area, respawn, x, y in ac["spawns"]:
        t = ac["templates"].get(entry)
        if not t or mapid not in (0, 1):
            continue
        key = (mapid, int(x // CELL), int(y // CELL))
        a = areas.setdefault(key, {"pool": 0, "elite": 0, "mobs": {}, "all": 0, "service": 0, "xs": [], "ys": []})
        a["all"] += 1
        if t["npcflag"]:
            a["service"] += 1
        if not _in_pool(t, zone, mapid):
            continue
        a["pool"] += 1
        if t["rank"] in (1, 2):
            a["elite"] += 1
        if t["rank"] == 0 and t["maxlevel"] <= level + LEVEL_ABOVE and t["minlevel"] >= level - LEVEL_BELOW:
            m = a["mobs"].setdefault(entry, {"n": 0, "respawn": 0})
            m["n"] += 1
            m["respawn"] += respawn or 300
            a["xs"].append(x)
            a["ys"].append(y)
    out, memo = [], {}
    for (mapid, cx, cy), a in areas.items():
        if not a["mobs"] or a["elite"] / a["pool"] >= ELITE_SHARE or a["service"] / a["all"] >= CITY_SHARE:
            continue
        total = sum(m["n"] for m in a["mobs"].values())
        kph = cap = gold_h = 0.0
        qty_h, mobs = {}, []
        for entry, m in a["mobs"].items():
            t = ac["templates"][entry]
            w = m["n"] / total
            if entry not in memo:
                memo[entry] = mob_value(ac, entry, prices, skinning)
            v = memo[entry]
            below = max(0, level - (t["minlevel"] + t["maxlevel"]) / 2)
            kph += w * KPH_BASE * min(KPH_MAX_FACTOR, 1 + KPH_PER_LEVEL * below)
            cap += m["n"] * 3600 / max(1, m["respawn"] / m["n"]) * SPAWN_FACTOR
            mobs.append({"entry": entry, "name": t["name"], "share": w, "per_kill": v["copper"],
                         "levels": (t["minlevel"], t["maxlevel"])})
        kph = min(kph, cap)
        for entry, m in a["mobs"].items():
            w = m["n"] / total
            v = memo[entry]
            gold_h += kph * w * v["gold"]
            for it, q in v["qty"].items():
                qty_h[it] = qty_h.get(it, 0) + kph * w * q
        items_h, saturated = _sell(ac, qty_h, prices)
        gph = gold_h + sum(v for _, _, v in items_h)
        levels = (min(x["levels"][0] for x in mobs), max(x["levels"][1] for x in mobs))
        out.append({"map": mapid, "cell": (cx, cy), "x": sum(a["xs"]) / len(a["xs"]), "y": sum(a["ys"]) / len(a["ys"]),
                    "levels": levels, "kph": kph, "gph": gph,
                    "gph_range": (gph * (1 - GPH_SPREAD), gph * (1 + GPH_SPREAD)), "spawns": total,
                    "mobs": sorted(mobs, key=lambda x: -x["share"]), "top_items": items_h[:3], "saturated": saturated})
    out.sort(key=lambda r: -r["gph"])
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--descargar", action="store_true", help="descargar (o actualizar) AzerothCore")
    ap.add_argument("--dir", default=AC_DIR)
    a = ap.parse_args()
    if a.descargar:
        import azerothcore
        azerothcore.download(a.dir)
        print(f"AzerothCore → {a.dir}")


if __name__ == "__main__":
    main()
