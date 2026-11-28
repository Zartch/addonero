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


_SKILLS = None


def gather_skills():
    """Nivel de profesión de cada nodo (tools/gather_skill.json; valores del clásico, sin comprobar en Forever)."""
    global _SKILLS
    if _SKILLS is None:
        import json
        with open(os.path.join(HERE, "gather_skill.json"), encoding="utf-8") as fh:
            _SKILLS = json.load(fh)
    return _SKILLS


def gathering(gm, ac, prices, profs):
    """Mapas de recolección ordenados por oro por hora. gm: gathermate.load.
    profs: {"herb": nivel, "mine": nivel} (nivel None = sin comprobar) o un conjunto {"herb", "mine"}.
    Fuera: los nodos por encima de tu nivel y los raros (Loto negro). Nodos por hora: GATHER_NPH, menos si el mapa
    tiene pocos nodos que puedas recoger."""
    if not isinstance(profs, dict):
        profs = {k: None for k in profs}
    sk = gather_skills()
    out = []
    for kind in sorted(profs):
        skill = profs[kind]
        for mapid, all_nodes in gm.get(kind, {}).items():
            nodes, above, rare, unchecked = {}, [], [], []
            for nid, n in all_nodes.items():
                name = gm["names"].get(nid, str(nid))
                req = sk.get(kind, {}).get(name)
                if name in sk.get("rare", []):
                    rare.append(name)
                elif skill is not None and req is not None and req > skill:
                    above.append(name)
                else:
                    if req is None:
                        unchecked.append(name)
                    nodes[nid] = n
            total = sum(nodes.values())
            if not total:
                continue
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
                        "unvalued": sorted(unvalued), "saturated": saturated, "skill": skill,
                        "above_skill": sorted(above), "rare": sorted(rare), "unchecked": sorted(unchecked)})
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


# ----------------------------------------------------------------------
# Lo medido en el juego (Farm.lua → archivo) y su combinación con la estimación
# ----------------------------------------------------------------------
CONF_KILLS = 30             # con 30 muertes, lo medido sustituye a la estimación
CONF_SECS = 1200            # y con 20 minutos activos, confianza alta
MIN_SECS = 60               # menos tiempo activo que esto no da oro por hora
MID_KILLS, MID_SECS = 10, 300   # por debajo, la muestra es demasiado pequeña: confianza baja
HERB_WORDS = ("herbor", "herbal", "botán", "botan")    # en Forever en español: «Botánica»
MINE_WORDS = ("miner", "mining")


def unit_value(item, ac, prices):
    """Valor de una unidad: subasta, o vendedor para grises y lo que no tiene precio."""
    info = ac["items"].get(item) if ac else None
    if info:
        return _unit(item, info, prices)
    return (prices.get(item) or {}).get("value") or 0


def read_measured(archive, market):
    """{"mobs": [{npc, sub, zone, map, kills, secs, copper, items}], "npcs": {npc: {name, lvl, cls}}} del archivo."""
    import json
    import sqlite3
    out = {"mobs": [], "npcs": {}, "places": {}, "maps": {}, "gather": []}
    if not archive or not os.path.exists(archive):
        return out
    con = sqlite3.connect(archive)
    try:
        for key, field in (("farm_places", "places"), ("farm_maps", "maps")):
            row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            if row:
                out[field] = json.loads(row[0])
        cols = [r[1] for r in con.execute("PRAGMA table_info(farm_mobs)")]
        span = "f.span" if "span" in cols else "0"
        rows = con.execute(f"SELECT f.npc, f.sub, f.zone, f.map, f.kills, f.secs, f.copper, f.items, {span} FROM farm_mobs f "
                           "JOIN markets m ON m.market_id = f.market_id WHERE m.key = ?", (market,)).fetchall()
        npcs = con.execute("SELECT npc, name, lvl, cls FROM farm_npcs").fetchall()
        try:
            gcols = [r[1] for r in con.execute("PRAGMA table_info(farm_gather)")]
            gspan = "g.span" if "span" in gcols else "0"
            gat = con.execute(f"SELECT g.sub, g.zone, g.map, g.nodes, g.secs, g.items, {gspan} FROM farm_gather g "
                              "JOIN markets m ON m.market_id = g.market_id WHERE m.key = ?", (market,)).fetchall()
        except sqlite3.OperationalError:    # archivo sin el tiempo de recolección
            gat = []
    except sqlite3.OperationalError:        # archivo anterior al farmeo
        return out
    finally:
        con.close()
    for npc, sub, zone, mapid, kills, secs, copper, items, sp in rows:
        out["mobs"].append({"npc": npc, "sub": sub, "zone": zone, "map": mapid, "kills": kills or 0, "secs": secs or 0,
                            "copper": copper or 0, "items": {int(k): v for k, v in json.loads(items or "{}").items()},
                            "span": sp or 0})
    out["npcs"] = {n: {"name": name, "lvl": lvl, "cls": cls} for n, name, lvl, cls in npcs}
    for sub, zone, mapid, nodes, secs, items, sp in gat:
        out["gather"].append({"sub": sub, "zone": zone, "map": mapid, "nodes": nodes or 0, "secs": secs or 0,
                              "items": {int(k): v for k, v in json.loads(items or "{}").items()}, "span": sp or 0})
    return out


RATE_MIN_SECS = 60              # con menos de un minuto medido no hay ritmo
RATE_LOW_SECS = 30 * 60         # menos de media hora: confianza baja
RATE_HIGH_SECS = 2 * 3600       # dos horas o más: confianza alta
# Farmear no es solo matar y recoger: descansar, moverse entre grupos y volver a vender también es tiempo.
DOWN_ACTIVE = 0.6               # supuesto: el 60 % de la sesión es matar y recoger (40 % descansos y movimientos)
DOWN_PRIOR_SECS = 3600          # peso del supuesto: con una hora de sesión medida, mitad medido y mitad supuesto
TOWN_MIN_PER_H = 10             # viajes a vender, reparar y vaciar bolsas: minutos por cada hora de sesión


def unit_secs(rows, count):
    """Segundos activos por muerte (o por nodo) en lo que sí tiene tiempo; None si nada lo tiene."""
    timed = [r for r in rows if r.get("secs")]
    n = sum(r.get(count) or 0 for r in timed)
    return sum(r["secs"] for r in timed) / n if n else None


def eff_secs(r, count, spu):
    """Tiempo de una fila: el medido o, si no tiene (la primera muerte de cada sesión, nodos de antes del 28/11),
    lo que suele costar cada muerte o nodo. Así su botín no sube el ritmo de balde."""
    if r.get("secs"):
        return r["secs"]
    return (r.get(count) or 0) * spu if spu else 0


def farm_rate(meas, ac, prices, overhead=None):
    """Oro por hora farmeando, con todo lo medido: criaturas (oro + botín) y plantas/minerales (botín). Es el mínimo
    que el plan pide a cualquier propuesta. None con menos de un minuto medido.
    El tiempo no es solo el activo: se amortizan los descansos y movimientos (la parte activa de la sesión, medida con
    `span` y mezclada con el supuesto DOWN_ACTIVE según cuánto hay medido) y los viajes a vender (TOWN_MIN_PER_H).
    overhead: catalog.json["farm_overhead"] ({"active", "prior_secs", "town_min_per_h"}) para cambiar los supuestos."""
    ov = overhead or {}
    a0 = ov.get("active", DOWN_ACTIVE)
    w0 = ov.get("prior_secs", DOWN_PRIOR_SECS)
    town = ov.get("town_min_per_h", TOWN_MIN_PER_H)
    def part(rows, count):
        spu = unit_secs(rows, count)
        val = lambda r: (r.get("copper") or 0) + sum(q * unit_value(it, ac, prices) for it, q in r["items"].items())
        timed = [r for r in rows if eff_secs(r, count, spu)]          # sin ningún tiempo medido, no cuenta
        value = sum(val(r) for r in timed)
        secs = sum(eff_secs(r, count, spu) for r in timed)
        return {"value": value, "secs": secs, "measured_secs": sum(r.get("secs") or 0 for r in rows),
                "n": sum(r.get(count) or 0 for r in rows), "untimed": sum(val(r) for r in rows) - value,
                "gph": value / secs * 3600 if secs >= RATE_MIN_SECS else None}
    mobs, gather = part(meas.get("mobs") or [], "kills"), part(meas.get("gather") or [], "nodes")
    secs = mobs["secs"] + gather["secs"]
    if secs < RATE_MIN_SECS:
        return None
    measured = mobs["measured_secs"] + gather["measured_secs"]      # la confianza, con lo medido de verdad
    conf = "baja" if measured < RATE_LOW_SECS else "media" if measured < RATE_HIGH_SECS else "alta"
    value = mobs["value"] + gather["value"]
    # parte activa de la sesión: lo medido (solo filas con sesión) mezclado con el supuesto; con poco medido, el supuesto
    rows = [r for r in (meas.get("mobs") or []) + (meas.get("gather") or []) if r.get("span")]
    act_m, span_m = sum(r["secs"] or 0 for r in rows), sum(r["span"] for r in rows)
    active = min(1.0, (act_m + a0 * w0) / (span_m + w0)) if span_m + w0 > 0 else a0
    session = secs / active
    total = session * (1 + town / 60)
    return {"gph": value / total * 3600, "gph_active": value / secs * 3600, "secs": secs, "conf": conf,
            "active_share": active, "active_measured": act_m / span_m if span_m else None, "span_secs": span_m,
            "town_min_per_h": town, "mobs": mobs, "gather": gather}


def amortized_gph(value, secs, rate):
    """Oro por hora de `value` ganado en `secs` activos, con los descansos, movimientos y viajes a vender del ritmo
    general (farm_rate). None con menos de un minuto."""
    if not secs or secs < RATE_MIN_SECS:
        return None
    share = (rate or {}).get("active_share") or DOWN_ACTIVE
    town = (rate or {}).get("town_min_per_h", TOWN_MIN_PER_H)
    return value / (secs / share * (1 + town / 60)) * 3600


def measured_zones(meas, ac, prices, rate):
    """«Cuando pasaste por aquí ganaste…»: lo medido agrupado por zona y, dentro, cada criatura (todas sus subzonas
    juntas) y lo recogido. El oro por hora cuenta descansos y viajes a vender, como el ritmo del plan."""
    zones = {}
    zone = lambda name: zones.setdefault(name or "?", {"zone": name or "?", "value": 0.0, "secs": 0, "span": 0,
                                                       "kills": 0, "nodes": 0, "mobs": {}, "gather": {}})
    npcs = meas.get("npcs") or {}
    spk = unit_secs(meas.get("mobs") or [], "kills")
    spn = unit_secs(meas.get("gather") or [], "nodes")
    for m in meas.get("mobs") or []:
        z = zone(m["zone"])
        secs = eff_secs(m, "kills", spk)
        v = (m["copper"] or 0) + sum(q * unit_value(it, ac, prices) for it, q in m["items"].items())
        c = z["mobs"].setdefault(m["npc"], {"npc": m["npc"], "kills": 0, "secs": 0, "value": 0.0, "copper": 0,
                                            "qty": {}, "subs": []})
        c["kills"] += m["kills"]; c["secs"] += secs; c["value"] += v; c["copper"] += m["copper"] or 0
        c["measured"] = c.get("measured", 0) + (m["secs"] or 0)
        if m["sub"] and m["sub"] not in c["subs"]:
            c["subs"].append(m["sub"])
        for it, q in m["items"].items():
            c["qty"][it] = c["qty"].get(it, 0) + q
        z["value"] += v; z["secs"] += secs; z["span"] += m.get("span") or 0; z["kills"] += m["kills"]
        z["measured"] = z.get("measured", 0) + (m["secs"] or 0)
    for g in meas.get("gather") or []:
        z = zone(g["zone"])
        v = sum(q * unit_value(it, ac, prices) for it, q in g["items"].items())
        h = z["gather"].setdefault("all", {"nodes": 0, "secs": 0, "value": 0.0, "qty": {}, "subs": []})
        secs = eff_secs(g, "nodes", spn)
        h["nodes"] += g["nodes"]; h["secs"] += secs; h["value"] += v
        if g["sub"] and g["sub"] not in h["subs"]:
            h["subs"].append(g["sub"])
        for it, q in g["items"].items():
            h["qty"][it] = h["qty"].get(it, 0) + q
        z["nodes"] += g["nodes"]; z["span"] += g.get("span") or 0
        z["measured"] = z.get("measured", 0) + (g["secs"] or 0)
        if secs:                            # sin ningún nodo con tiempo, lo recogido no entra en el oro por hora
            z["value"] += v; z["secs"] += secs
    top = lambda qty: sorted(((it, q, q * unit_value(it, ac, prices)) for it, q in qty.items()), key=lambda x: -x[2])[:3]
    out = []
    for z in zones.values():
        mobs = []
        for c in z["mobs"].values():
            t = (ac or {}).get("templates", {}).get(c["npc"]) if ac else None
            n = npcs.get(c["npc"]) or {}
            mobs.append({"npc": c["npc"], "name": n.get("name") or (t and t["name"]) or f"npc:{c['npc']}",
                         "level": n.get("lvl") or (t and t["maxlevel"]), "cls": n.get("cls"), "kills": c["kills"],
                         "secs": c["secs"], "value": c["value"], "per_kill": c["value"] / c["kills"] if c["kills"] else None,
                         "gph": amortized_gph(c["value"], c["secs"], rate), "subs": c["subs"], "top_items": top(c["qty"]),
                         "confidence": _confidence(c["kills"], c.get("measured", 0))})
        mobs.sort(key=lambda x: -x["value"])
        gather = [{"nodes": h["nodes"], "secs": h["secs"], "value": h["value"], "subs": h["subs"],
                   "gph": amortized_gph(h["value"], h["secs"], rate), "top_items": top(h["qty"])}
                  for h in z["gather"].values()]
        out.append({"zone": z["zone"], "value": z["value"], "secs": z["secs"], "span": z["span"], "kills": z["kills"],
                    "nodes": z["nodes"], "gph": amortized_gph(z["value"], z["secs"], rate),
                    "confidence": _confidence(z["kills"], z.get("measured", 0)), "mobs": mobs, "gather": gather})
    out.sort(key=lambda x: -x["value"])
    return out


def per_npc(mobs):
    """Suma lo medido de cada criatura en todas las subzonas: {npc: {kills, secs, copper, items}}."""
    out = {}
    for m in mobs:
        o = out.setdefault(m["npc"], {"kills": 0, "secs": 0, "copper": 0, "items": {}})
        for k in ("kills", "secs", "copper"):
            o[k] += m[k]
        for it, q in m["items"].items():
            o["items"][it] = o["items"].get(it, 0) + q
    return out


def _confidence(kills, secs):
    """Alta con 30 muertes y 20 minutos; media con 10 muertes y 5 minutos; con menos, un botín con suerte
    lo decide todo (5 muertes en un minuto y un objeto verde daban 48 oro a la hora)."""
    if kills >= CONF_KILLS and secs >= CONF_SECS:
        return "alta"
    return "media" if kills >= MID_KILLS and secs >= MID_SECS else "baja"


def combine(est_rows, by_npc, ac, prices):
    """Estimación de cada cuadrícula corregida con lo medido de sus criaturas.
    Peso de lo medido W = Σ(peso de la criatura × min(1, muertes/30)); oro/h = W × medido + (1 − W) × estimado,
    donde «medido» usa el oro y los objetos que de verdad soltaron (al mismo ritmo de muertes)."""
    out = []
    for r in est_rows:
        W, kills, secs, gold_h, qty_h, mobs = 0.0, 0, 0, 0.0, {}, []
        all_measured = True
        for mob in r["mobs"]:
            m = by_npc.get(mob["entry"])
            share, mob = mob["share"], dict(mob)
            if m and m["kills"]:
                w = min(1.0, m["kills"] / CONF_KILLS)
                W += share * w
                kills, secs = kills + m["kills"], secs + m["secs"]
                gold_h += r["kph"] * share * m["copper"] / m["kills"]
                for it, q in m["items"].items():
                    qty_h[it] = qty_h.get(it, 0) + r["kph"] * share * q / m["kills"]
                mob["measured"] = {"kills": m["kills"], "per_kill": (m["copper"] + sum(
                    q * unit_value(it, ac, prices) for it, q in m["items"].items())) / m["kills"]}
                all_measured = all_measured and m["kills"] >= CONF_KILLS
            else:
                all_measured = False
                v = mob_value(ac, mob["entry"], prices)
                gold_h += r["kph"] * share * v["gold"]
                for it, q in v["qty"].items():
                    qty_h[it] = qty_h.get(it, 0) + r["kph"] * share * q
            mobs.append(mob)
        c = dict(r, mobs=mobs)
        if W > 0:
            items_h, _ = _sell(ac, qty_h, prices)
            measured_gph = gold_h + sum(v for _, _, v in items_h)
            c["gph"] = W * measured_gph + (1 - W) * r["gph"]
            spread = GPH_SPREAD * (1 - min(1.0, W)) + 0.10 * min(1.0, W)
            c["gph_range"] = (c["gph"] * (1 - spread), c["gph"] * (1 + spread))
            if W >= 1 - 1e-9:
                c["top_items"] = items_h[:3]
        full = W >= 1 - 1e-9
        c["source"] = "medido" if full else "mixto" if W > 0 else "estimado"
        c["confidence"] = ("alta" if full and all_measured and secs >= CONF_SECS else "media") if W > 0 else "baja"
        c["measured_weight"] = min(1.0, W)
        out.append(c)
    out.sort(key=lambda x: -x["gph"])
    return out


def measured_places(mobs, npcs, ac, prices):
    """«Donde ya has farmeado»: lo medido por subzona, con su oro por hora real."""
    places = {}
    for m in mobs:
        p = places.setdefault((m["zone"], m["sub"]), {"zone": m["zone"], "sub": m["sub"], "map": m["map"], "kills": 0,
                                                      "secs": 0, "value": 0.0, "qty": {}, "mobs": []})
        p["kills"] += m["kills"]
        p["secs"] += m["secs"]
        p["value"] += m["copper"]
        for it, q in m["items"].items():
            p["qty"][it] = p["qty"].get(it, 0) + q
            p["value"] += q * unit_value(it, ac, prices)
        t = (ac or {}).get("templates", {}).get(m["npc"]) if ac else None
        n = npcs.get(m["npc"]) or {}
        p["mobs"].append({"npc": m["npc"], "name": n.get("name") or (t and t["name"]) or f"npc:{m['npc']}",
                          "kills": m["kills"], "level": n.get("lvl") or (t and t["maxlevel"]), "cls": n.get("cls")})
    out = []
    for p in places.values():
        enough = p["secs"] >= MIN_SECS
        top = sorted(((it, q, q * unit_value(it, ac, prices)) for it, q in p["qty"].items()), key=lambda x: -x[2])[:3]
        out.append({"zone": p["zone"], "sub": p["sub"], "map": p["map"], "kills": p["kills"], "secs": p["secs"],
                    "kph": p["kills"] / p["secs"] * 3600 if enough else None,
                    "gph": p["value"] / p["secs"] * 3600 if enough else None,
                    "per_kill": p["value"] / p["kills"] if p["kills"] else None, "top_items": top,
                    "mobs": sorted(p["mobs"], key=lambda x: -x["kills"]), "source": "medido",
                    "confidence": _confidence(p["kills"], p["secs"])})
    # primero lo que tiene muestra: una cifra alta con cinco muertes no va delante de una medida de verdad
    out.sort(key=lambda x: (x["confidence"] == "baja", -(x["gph"] if x["gph"] is not None else -1)))
    return out


def gather_kinds(professions):
    """Profesiones de recolección del personaje ({nombre: {skill, …}}, en español o inglés) → {"herb": nivel, "mine": nivel}."""
    out = {}
    for name, p in (professions or {}).items():
        low = name.lower()
        skill = (p or {}).get("skill") if isinstance(p, dict) else None
        if any(w in low for w in HERB_WORDS):
            out["herb"] = skill
        if any(w in low for w in MINE_WORDS):
            out["mine"] = skill
    return out


def farm_plan(ac, gm, prices, chars, meas, explore_n=10, gather_n=5):
    """Bloque «farm» del plan: lo medido (común) y, por personaje, «por explorar» y «recolección»."""
    by = per_npc(meas["mobs"])
    out = {"measured": measured_places(meas["mobs"], meas["npcs"], ac, prices),
           "has_ac": ac is not None, "has_gm": gm is not None, "chars": {}}
    for ck, c in chars.items():
        level = c.get("level")
        explore = combine(estimate(ac, prices, level), by, ac, prices)[:explore_n] if ac and level else []
        kinds = gather_kinds(c.get("professions"))
        gather = gathering(gm, ac, prices, kinds)[:gather_n] if ac and gm and kinds else []
        out["chars"][ck] = {"level": level, "kinds": sorted(kinds), "skills": kinds, "explore": explore, "gather": gather}
    return out


# ----------------------------------------------------------------------
# Farmeo.lua: lo que lee el juego (panel /oro farmear y aviso al entrar en un sitio)
# ----------------------------------------------------------------------
BAND = 5                    # tramos de 5 niveles
MAX_LEVEL = 60
FARMEO_ROWS = 15            # sitios por tramo
SKILL_BAND = 25             # tramos de nivel de profesión para la recolección
MAX_SKILL = 300
GATHER_ROWS = 5
MEASURED_ROWS = 15


def farmeo_data(ac, gm, prices, meas):
    """Lo que va a Farmeo.lua: {"bands": {nivel: filas}, "gather": {kind: {skill: filas}}, "measured": filas}."""
    by = per_npc(meas["mobs"])
    bands, gather = {}, {}
    if ac:
        for b in range(0, MAX_LEVEL + 1, BAND):
            level = max(1, min(MAX_LEVEL, b + BAND // 2))
            bands[b] = combine(estimate(ac, prices, level), by, ac, prices)[:FARMEO_ROWS]
        if gm:
            for kind in ("herb", "mine"):
                gather[kind] = {s: gathering(gm, ac, prices, {kind: s})[:GATHER_ROWS]
                                for s in range(0, MAX_SKILL + 1, SKILL_BAND)}
    measured = measured_places(meas["mobs"], meas["npcs"], ac, prices)[:MEASURED_ROWS]
    return {"bands": bands, "gather": gather, "measured": measured}


def write_farmeo(path, fd, now=None):
    """Escribe Oroboros/Farmeo.lua (ignorado en git). Devuelve su tamaño en bytes."""
    import time
    from oroboros_summary import lua_str
    n = lambda x: "nil" if x is None else str(int(round(x)))
    ids = lambda items: "{" + ",".join(str(it) for it, _, _ in items) + "}"
    lines = ["-- Generado por tools/oroboros_farm.py (docs/farmeo.md). No editar.",
             f"OroborosFarmeo = {{ v = 1, t = {int(now or time.time())}, cell = {CELL},", "bands = {"]
    for b, rows in sorted(fd["bands"].items()):
        lines.append(f"[{b}] = {{")
        for r in rows:
            mobs = ", ".join(m["name"] for m in r["mobs"][:3])
            lines.append(f'{{m={r["map"]},cx={r["cell"][0]},cy={r["cell"][1]},x={n(r["x"])},y={n(r["y"])},'
                         f'lv="{r["levels"][0]}-{r["levels"][1]}",'
                         f'g={n(r["gph"])},lo={n(r["gph_range"][0])},hi={n(r["gph_range"][1])},src="{r["source"]}",'
                         f'conf="{r["confidence"]}",sat={"true" if r["saturated"] else "false"},'
                         f'mobs={lua_str(mobs)},it={ids(r["top_items"])}}},')
        lines.append("},")
    lines.append("},")
    lines.append("gather = {")
    for kind, by_skill in sorted(fd["gather"].items()):
        lines.append(f"{kind} = {{")
        for s, rows in sorted(by_skill.items()):
            lines.append(f"[{s}] = {{" + "".join(f"{{map={g['map']},g={n(g['gph'])},nph={n(g['nph'])},it={ids(g['top_items'])}}},"
                                                   for g in rows) + "},")
        lines.append("},")
    lines.append("},")
    lines.append("measured = {")
    for r in fd["measured"]:
        lines.append(f'{{sub={lua_str(r["sub"])},zone={lua_str(r["zone"])},g={n(r["gph"])},kills={r["kills"]},'
                     f'secs={r["secs"]},conf="{r["confidence"]}",it={ids(r["top_items"])}}},')
    lines.append("},")
    lines.append("}")
    text = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return len(text.encode("utf-8"))


def item_ids(farm):
    """Objetos que aparecen en el bloque del plan (para ponerles nombre)."""
    ids = set()
    rows = list(farm["measured"])
    for z in farm.get("zones") or []:
        rows += z["mobs"] + z["gather"]
    for c in farm["chars"].values():
        rows += c["explore"] + c["gather"]
    for r in rows:
        ids.update(it for it, _, _ in r["top_items"])
    return ids


def for_plan(data, archive, ac_dir=None, wow_path=None, farmeo_path=None):
    """plan["farm"] desde el Data del planificador. Sin AzerothCore solo sale lo medido.
    Con farmeo_path (y AzerothCore), escribe también Farmeo.lua para el juego."""
    import azerothcore
    import gathermate
    ac = azerothcore.load(ac_dir) if ac_dir and azerothcore.available(ac_dir) else None
    base = gathermate.find(wow_path) if wow_path else None
    gm = gathermate.load(base) if base else None
    prices = {}
    for i in data.prices:
        st = data.stats(i)
        prices[i] = {"value": st["mv"], "vol": st["vol"]}
    meas = read_measured(archive, data.market)
    farm = farm_plan(ac, gm, prices, {k: {"level": c["level"], "professions": data.professions.get(k, {})}
                                      for k, c in data.chars.items()}, meas)
    farm["places"], farm["maps"] = meas["places"], meas["maps"]
    farm["rate"] = farm_rate(meas, ac, prices, (getattr(data, "catalog", None) or {}).get("farm_overhead"))
    farm["zones"] = measured_zones(meas, ac, prices, farm["rate"])
    if farmeo_path and ac:
        farm["farmeo_bytes"] = write_farmeo(farmeo_path, farmeo_data(ac, gm, prices, meas))
    names = {}
    for i in item_ids(farm):
        n = data.name(i)
        if n.startswith("item:") and ac and ac["items"].get(i):
            n = ac["items"][i].get("name") or n
        names[i] = n
    farm["names"] = names
    return farm


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
