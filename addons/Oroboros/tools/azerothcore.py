"""
Oroboros: base de datos del mundo de AzerothCore (servidor de código abierto de WotLK, AGPL-3.0), usada solo
como **estimación inicial** de qué sueltan las criaturas (docs/farmeo.md). Se descarga a work/fuentes/azerothcore/
(no se sube al repositorio) y se lee aquí sin dependencias externas.

El botín de Forever cambió respecto al clásico: lo medido en el juego manda sobre esta estimación.
"""
import json
import os
import re
import time
import urllib.request

BASE_URL = "https://raw.githubusercontent.com/azerothcore/azerothcore-wotlk/master/data/sql/base/db_world/"
TABLES = ("creature_template", "creature", "creature_loot_template", "reference_loot_template",
          "skinning_loot_template", "item_template", "gameobject_template", "gameobject_loot_template")
CACHE = "cache.json"
CACHE_VERSION = 4

TOKEN = re.compile(r"'(?:[^'\\]|\\.|'')*'|NULL|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[(),;]")


def download(dest_dir, log=print):
    """Descarga las ocho tablas (unos 48 MB). Sobrescribe las que hubiera."""
    os.makedirs(dest_dir, exist_ok=True)
    for t in TABLES:
        url = BASE_URL + t + ".sql"
        log(f"Descargando {t}…")
        req = urllib.request.Request(url, headers={"User-Agent": "oroboros-addon"})
        with urllib.request.urlopen(req, timeout=120) as r, open(os.path.join(dest_dir, t + ".sql"), "wb") as fh:
            fh.write(r.read())
    with open(os.path.join(dest_dir, "descargado.txt"), "w", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M") + "\n" + BASE_URL + "\n")
    cache = os.path.join(dest_dir, CACHE)
    if os.path.exists(cache):
        os.remove(cache)


def available(dest_dir):
    return all(os.path.exists(os.path.join(dest_dir, t + ".sql")) for t in TABLES)


def _unquote(tok):
    s = tok[1:-1]
    return s.replace("\\'", "'").replace("''", "'").replace('\\"', '"').replace("\\\\", "\\")


def _value(tok):
    if tok == "NULL":
        return None
    if tok[0] == "'":
        return _unquote(tok)
    return float(tok) if any(c in tok for c in ".eE") else int(tok)


def read_dump(path, wanted):
    """Filas de un volcado SQL de AzerothCore, solo con las columnas `wanted` (en ese orden)."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    m = re.search(r"CREATE TABLE `\w+` \((.*?)\n\)", text, re.S)
    cols = re.findall(r"^\s+`(\w+)`", m.group(1), re.M)
    idx = [cols.index(c) for c in wanted]
    rows = []
    for ins in re.finditer(r"INSERT INTO `\w+` VALUES", text):
        row, depth = None, 0
        for tok in TOKEN.finditer(text, ins.end()):
            t = tok.group(0)
            if t == ";" and depth == 0:
                break
            if t == "(":
                depth += 1
                row = []
            elif t == ")":
                depth -= 1
                rows.append(tuple(row[i] for i in idx))
            elif t != ",":
                row.append(_value(t))
    return rows


def _loot(rows):
    out = {}
    for entry, item, ref, chance, quest, mode, group, mn, mx in rows:
        out.setdefault(entry, []).append({"item": item, "reference": ref, "chance": chance, "quest": quest,
                                          "mode": mode, "group": group, "min": mn, "max": mx})
    return out


def load(dest_dir):
    """Lee las tablas (o la caché, si es más nueva que los .sql). Devuelve un dict con
    templates, spawns, loot, refs, skin, items, nodes ({nombre del nodo: [botín]}) y goloot."""
    cache = os.path.join(dest_dir, CACHE)
    sqls = [os.path.join(dest_dir, t + ".sql") for t in TABLES]
    if os.path.exists(cache) and all(os.path.getmtime(cache) >= os.path.getmtime(s) for s in sqls):
        with open(cache, encoding="utf-8") as fh:
            c = json.load(fh)
        if c.get("v") == CACHE_VERSION:
            ints = lambda d: {int(k): v for k, v in d.items()}
            return {"templates": ints(c["templates"]), "spawns": [tuple(s) for s in c["spawns"]],
                    "loot": ints(c["loot"]), "refs": ints(c["refs"]), "skin": ints(c["skin"]), "items": ints(c["items"]),
                    "nodes": c["nodes"], "goloot": ints(c["goloot"])}
    lt = ["Entry", "Item", "Reference", "Chance", "QuestRequired", "LootMode", "GroupId", "MinCount", "MaxCount"]
    ct = ["entry", "name", "minlevel", "maxlevel", "rank", "type", "unit_flags", "npcflag", "lootid", "skinloot",
          "mingold", "maxgold"]
    templates = {r[0]: dict(zip(ct[1:], r[1:])) for r in read_dump(sqls[0], ct)}
    # zoneId/areaId vienen a 0 en AzerothCore: la posición (x, y) es lo que sirve para agrupar
    spawns = read_dump(sqls[1], ["id1", "map", "zoneId", "areaId", "spawntimesecs", "position_x", "position_y"])
    items = {r[0]: {"class": r[1], "quality": r[2], "sell": r[3], "bonding": r[4], "name": r[5]}
             for r in read_dump(sqls[5], ["entry", "class", "Quality", "SellPrice", "bonding", "name"])}
    # Nodos de recolección (tipo 3, cofre): Data1 es su botín. Varios nodos comparten nombre (p. ej. «Copper Vein»)
    nodes = {}
    for entry, typ, name, lid in read_dump(sqls[6], ["entry", "type", "name", "Data1"]):
        if typ == 3 and lid and lid not in nodes.setdefault(name, []):
            nodes[name].append(lid)
    ac = {"templates": templates, "spawns": spawns, "loot": _loot(read_dump(sqls[2], lt)),
          "refs": _loot(read_dump(sqls[3], lt)), "skin": _loot(read_dump(sqls[4], lt)), "items": items,
          "nodes": nodes, "goloot": _loot(read_dump(sqls[7], lt))}
    try:
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(dict(ac, v=CACHE_VERSION), fh)
    except OSError:
        pass
    return ac
