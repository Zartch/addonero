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
    out = {"mobs": [], "npcs": {}}
    if not archive or not os.path.exists(archive):
        return out
    con = sqlite3.connect(archive)
    try:
        rows = con.execute("SELECT f.npc, f.sub, f.zone, f.map, f.kills, f.secs, f.copper, f.items FROM farm_mobs f "
                           "JOIN markets m ON m.market_id = f.market_id WHERE m.key = ?", (market,)).fetchall()
        npcs = con.execute("SELECT npc, name, lvl, cls FROM farm_npcs").fetchall()
    except sqlite3.OperationalError:        # archivo anterior al farmeo
        return out
    finally:
        con.close()
    for npc, sub, zone, mapid, kills, secs, copper, items in rows:
        out["mobs"].append({"npc": npc, "sub": sub, "zone": zone, "map": mapid, "kills": kills or 0, "secs": secs or 0,
                            "copper": copper or 0, "items": {int(k): v for k, v in json.loads(items or "{}").items()}})
    out["npcs"] = {n: {"name": name, "lvl": lvl, "cls": cls} for n, name, lvl, cls in npcs}
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
    return "alta" if kills >= CONF_KILLS and secs >= CONF_SECS else "media"


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
    out.sort(key=lambda x: -(x["gph"] if x["gph"] is not None else -1))
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


def item_ids(farm):
    """Objetos que aparecen en el bloque del plan (para ponerles nombre)."""
    ids = set()
    rows = list(farm["measured"])
    for c in farm["chars"].values():
        rows += c["explore"] + c["gather"]
    for r in rows:
        ids.update(it for it, _, _ in r["top_items"])
    return ids


def for_plan(data, archive, ac_dir=None, wow_path=None):
    """plan["farm"] desde el Data del planificador. Sin AzerothCore solo sale lo medido."""
    import azerothcore
    import gathermate
    ac = azerothcore.load(ac_dir) if ac_dir and azerothcore.available(ac_dir) else None
    base = gathermate.find(wow_path) if wow_path else None
    gm = gathermate.load(base) if base else None
    prices = {}
    for i in data.prices:
        st = data.stats(i)
        prices[i] = {"value": st["mv"], "vol": st["vol"]}
    farm = farm_plan(ac, gm, prices, {k: {"level": c["level"], "professions": data.professions.get(k, {})}
                                      for k, c in data.chars.items()}, read_measured(archive, data.market))
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
