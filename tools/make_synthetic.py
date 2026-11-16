#!/usr/bin/env python3
"""
Genera un SavedVariables SINTÉTICO de Addonero (Addonero.lua) para probar el
planificador sin escanear en el juego. Los precios son INVENTADOS (economía de
WoW Forever en su segunda semana, plausible pero no real).

  python make_synthetic.py --out Addonero.lua
"""
import argparse
import random
import time

MARKET = "ForeverPvE-Horde"
MAIN, ALT, BANK = "Zartch-ForeverPvE", "Zarthrin-ForeverPvE", "Zartbank-ForeverPvE"
G, S = 10000, 100

# itemID: (nombre, calidad, venta a vendedor, pila, precio base, cantidad publicada, ventas/día, volatilidad, tendencia 14d)
ITEMS = {
    # Hierbas
    13464: ("Golden Sansam", 1, 2 * S, 20, 95 * S, 420, 140, 0.06, 0.05),
    13465: ("Mountain Silversage", 1, 2 * S, 20, 1 * G + 30 * S, 300, 90, 0.07, 0.08),
    13466: ("Plaguebloom", 1, 2 * S, 20, 1 * G + 20 * S, 180, 60, 0.08, 0.0),
    13463: ("Dreamfoil", 1, 2 * S, 20, 1 * G + 10 * S, 260, 80, 0.07, -0.05),
    13467: ("Icecap", 1, 2 * S, 20, 1 * G + 40 * S, 120, 30, 0.04, 0.12),
    13468: ("Black Lotus", 1, 5 * S, 20, 60 * G, 3, 2, 0.10, 0.10),
    8838: ("Sungrass", 1, 1 * S, 20, 45 * S, 500, 160, 0.06, 0.0),
    3358: ("Khadgar's Whisker", 1, 1 * S, 20, 35 * S, 380, 90, 0.07, 0.0),
    8839: ("Blindweed", 1, 1 * S, 20, 30 * S, 400, 80, 0.07, -0.08),
    8846: ("Gromsblood", 1, 1 * S, 20, 55 * S, 600, 150, 0.06, 0.04),
    3820: ("Stranglekelp", 1, 30, 20, 12 * S, 700, 120, 0.08, 0.0),
    6370: ("Blackmouth Oil", 1, 50, 20, 25 * S, 260, 50, 0.08, 0.0),
    13422: ("Stonescale Eel", 1, 50, 20, 70 * S, 140, 40, 0.08, 0.06),
    # Viales e hilos (de vendedor)
    8925: ("Crystal Vial", 1, 1 * S, 20, None, 0, 0, 0, 0),
    3372: ("Leaded Vial", 1, 20, 20, None, 0, 0, 0, 0),
    14341: ("Rune Thread", 1, 1 * S, 20, None, 0, 0, 0, 0),
    8343: ("Heavy Silken Thread", 1, 40, 20, None, 0, 0, 0, 0),
    # Alquimia
    13446: ("Major Healing Potion", 1, 1 * S, 5, 4 * G + 60 * S, 220, 70, 0.07, 0.04),
    13452: ("Elixir of the Mongoose", 1, 1 * S, 5, 9 * G + 80 * S, 90, 25, 0.12, 0.0),
    3928: ("Superior Healing Potion", 1, 50, 5, 1 * G + 10 * S, 160, 30, 0.08, -0.05),
    13443: ("Superior Mana Potion", 1, 50, 5, 1 * G + 60 * S, 140, 35, 0.08, 0.0),
    5634: ("Free Action Potion", 1, 80, 5, 3 * G + 20 * S, 40, 12, 0.12, 0.0),
    13423: ("Stonescale Oil", 1, 50, 20, 1 * G + 50 * S, 110, 35, 0.08, 0.0),
    13454: ("Greater Arcane Elixir", 1, 1 * S, 5, 7 * G + 50 * S, 70, 30, 0.10, 0.06),
    13444: ("Major Mana Potion", 1, 1 * S, 5, 5 * G + 80 * S, 130, 40, 0.08, 0.0),
    13510: ("Flask of the Titans", 1, 1 * G, 1, 135 * G, 6, 3, 0.12, 0.08),
    12360: ("Arcanite Bar", 2, 5 * S, 20, 52 * G, 14, 5, 0.09, 0.03),
    12363: ("Arcane Crystal", 2, 5 * S, 20, 28 * G, 25, 6, 0.09, 0.02),
    # Minería
    10620: ("Thorium Ore", 1, 2 * S, 20, 75 * S, 600, 160, 0.06, 0.0),
    12359: ("Thorium Bar", 1, 6 * S, 20, 1 * G + 90 * S, 350, 100, 0.06, 0.02),
    3858: ("Mithril Ore", 1, 2 * S, 20, 48 * S, 520, 120, 0.06, 0.0),
    3860: ("Mithril Bar", 1, 4 * S, 20, 55 * S, 400, 100, 0.06, -0.03),
    12365: ("Dense Stone", 1, 2 * S, 20, 30 * S, 300, 60, 0.07, 0.0),
    12404: ("Dense Sharpening Stone", 1, 1 * S, 20, 1 * G + 20 * S, 200, 40, 0.08, 0.0),
    # Telas y sastrería
    14047: ("Runecloth", 1, 1 * S, 20, 32 * S, 2400, 600, 0.06, -0.06),
    14048: ("Bolt of Runecloth", 1, 4 * S, 10, 1 * G + 25 * S, 300, 60, 0.06, -0.04),
    4338: ("Mageweave Cloth", 1, 25, 20, 22 * S, 1800, 400, 0.06, 0.0),
    4339: ("Bolt of Mageweave", 1, 2 * S, 10, 1 * G + 5 * S, 260, 50, 0.07, 0.0),
    10050: ("Mageweave Bag", 1, 1 * G, 1, 6 * G + 80 * S, 45, 18, 0.08, 0.05),
    14046: ("Runecloth Bag", 1, 2 * G + 50 * S, 1, 14 * G + 50 * S, 30, 12, 0.08, 0.06),
    13856: ("Runecloth Belt", 2, 1 * G + 10 * S, 1, 2 * G + 10 * S, 22, 3, 0.15, 0.0),
    14256: ("Felcloth", 1, 1 * S, 20, 2 * G + 40 * S, 90, 20, 0.08, 0.0),
    14342: ("Mooncloth", 1, 5 * S, 20, 22 * G, 8, 3, 0.10, 0.05),
    8170: ("Rugged Leather", 1, 1 * S, 20, 60 * S, 700, 150, 0.06, 0.0),
    15564: ("Rugged Armor Kit", 1, 50, 10, 4 * G + 50 * S, 80, 25, 0.08, 0.0),
    # Relleno típico del banco
    2589: ("Linen Cloth", 1, 13, 20, 1 * S + 20, 5000, 900, 0.03, -0.15),
    2592: ("Wool Cloth", 1, 33, 20, 4 * S, 3000, 500, 0.02, -0.10),
    4234: ("Heavy Leather", 1, 60, 20, 35 * S, 400, 60, 0.03, 0.0),
    17056: ("Light Feather", 1, 7, 20, 30, 900, 40, 0.20, 0.0),
    9206: ("Elixir of Giants", 1, 1 * S, 5, 3 * G, 50, 10, 0.10, 0.0),
}

# nivel de objeto (lo que no esté aquí: 55)
ILVL = {2589: 5, 2592: 15, 17056: 15, 3820: 18, 4234: 28, 6370: 30, 3372: 25, 8343: 30, 4338: 40, 4339: 38,
        3858: 40, 3860: 40, 3358: 37, 10050: 40, 5634: 35, 8838: 46, 8839: 47, 8846: 50, 3928: 43, 9206: 45,
        14047: 50, 14048: 50, 10620: 50, 12359: 50, 8170: 50, 12365: 50, 12404: 50}
# consumibles de banda: caros hacia el reinicio semanal (miércoles), baratos el fin de semana
WEEKLY = {13444, 13454, 9206}
WEEKDAY_FACTOR = {0: 0.95, 1: 1.10, 2: 1.14, 3: 1.04, 4: 0.98, 5: 0.94, 6: 0.92}   # 0 = lunes

# oferta: cuánto ha cambiado lo publicado en dos semanas (los mats de nivel bajo se secan, los de alto crecen)
SUPPLY = {2592: -0.38, 4234: -0.22, 3820: -0.08, 2589: 0.25, 17056: 0.1,
          13464: 0.3, 13465: 0.25, 13463: 0.3, 8846: 0.35, 10620: 0.3, 14047: 0.4, 8170: 0.25, 12365: 0.2}

VENDOR = {8925: 4 * S, 3372: 80, 14341: 50 * S, 8343: 16 * S}

# recipeID: (nombre, salida, (qmin, qmax), [(reactivo, cantidad)], dificultad, aprendida, fuente)
ALCHEMY = {
    17556: ("Major Healing Potion", 13446, (1, 1), [(13464, 2), (13465, 1), (8925, 1)], 1, True, None),
    17571: ("Elixir of the Mongoose", 13452, (1, 1), [(13465, 2), (13466, 2), (8925, 1)], 0, True, None),
    11457: ("Superior Healing Potion", 3928, (1, 1), [(8838, 1), (3358, 1), (8925, 1)], 3, True, None),
    17553: ("Superior Mana Potion", 13443, (1, 1), [(8838, 2), (8839, 2), (8925, 1)], 2, True, None),
    6624: ("Free Action Potion", 5634, (1, 1), [(6370, 2), (3820, 1), (3372, 1)], 3, True, None),
    17551: ("Stonescale Oil", 13423, (1, 1), [(13422, 1), (3372, 1)], 2, True, None),
    17187: ("Transmute: Arcanite", 12360, (1, 1), [(12359, 1), (12363, 1)], 1, True, None),
    17573: ("Greater Arcane Elixir", 13454, (1, 1), [(13463, 3), (13465, 1), (8925, 1)], 0, False,
            "Vendedor: Alchemist Pestlezugg (Gadgetzan) — Coste: 3g"),
    17580: ("Major Mana Potion", 13444, (1, 1), [(13463, 3), (13467, 2), (8925, 1)], 0, False,
            "Botín de mundo (poco común)"),
    17635: ("Flask of the Titans", 13510, (1, 1), [(8846, 30), (13423, 10), (13468, 1)], 0, False,
            "Botín: mazmorra de nivel 60 (receta rara)"),
}
TAILORING = {
    18401: ("Bolt of Runecloth", 14048, (1, 1), [(14047, 4)], 1, True, None),
    3865: ("Bolt of Mageweave", 4339, (1, 1), [(4338, 4)], 3, True, None),
    12065: ("Mageweave Bag", 10050, (1, 1), [(4339, 4), (8343, 2)], 2, True, None),
    18402: ("Runecloth Belt", 13856, (1, 1), [(14048, 3), (14341, 1)], 0, True, None),
    18405: ("Runecloth Bag", 14046, (1, 1), [(14048, 5), (8170, 2), (14341, 1)], 0, False,
            "Vendedor: Qia (Everlook) — Coste: 4g 50s"),
    18560: ("Mooncloth", 14342, (1, 1), [(14256, 2)], 0, False,
            "Vendedor: Qia (Everlook) — Coste: 4g"),
}
MINING = {
    16153: ("Smelt Thorium", 12359, (1, 1), [(10620, 1)], 1, True, None),
    10097: ("Smelt Mithril", 3860, (1, 1), [(3858, 1)], 3, True, None),
}

INVENTORY = {
    MAIN: {
        "money": 72 * G + 37 * S,
        "bags": {13464: 14, 13465: 6, 8925: 20, 13446: 18, 12363: 1},
        "bagSlots": (76, 12),
        "bank": {14047: 140, 13464: 40, 13466: 12, 12363: 2, 13422: 20, 13468: 1, 17056: 30, 2592: 60,
                 2589: 80, 4234: 18, 9206: 3, 14256: 6},
        "bankSlots": (98, 4),
    },
    ALT: {
        "money": 36 * G + 4 * S,
        "bags": {10620: 40, 3858: 60, 14047: 30, 4339: 4},
        "bagSlots": (64, 22),
        "bank": {12359: 20, 4338: 80, 8170: 10},
        "bankSlots": (56, 20),
    },
}
# el banquero: nivel bajo, parado en la subasta, sin profesiones y con casi todo el oro
INVENTORY[BANK] = {"money": 400 * G, "bags": {8925: 20}, "bagSlots": (40, 31), "bank": {}, "bankSlots": (28, 28)}
WARBAND = {"items": {13463: 15, 12360: 1}, "slots": (98, 61)}


def day_str(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def build(seed=7):
    rnd = random.Random(seed)
    now = int(time.time())
    db = {"schema": 1, "config": {"banker": BANK}, "items": {}, "vendor": dict(VENDOR), "chars": {}, "route": {},
          "markets": {MARKET: {"lastFull": now - 40 * 60, "prices": {}, "history": {}}}}
    m = db["markets"][MARKET]
    for item_id, (name, q, sell, stack, base, qty, vol, sd, trend) in ITEMS.items():
        db["items"][item_id] = {"n": name, "q": q, "s": sell, "st": stack, "c": stack > 1,
                                "il": ILVL.get(item_id, 55)}
        if base is None:
            continue
        hist, q_prev = {}, qty
        for d in range(13, -1, -1):
            ts = now - d * 86400
            drift = 1 + trend * (13 - d) / 13
            if item_id == 2592:      # Wool: cayó hasta hace 5 días y desde entonces ha tocado suelo
                drift = 1.12 - 0.17 * (13 - d) / 8 if d >= 5 else 0.95 + 0.04 * (5 - d) / 5
            noise = rnd.gauss(0, sd)
            if item_id in WEEKLY:
                noise = noise * 0.3 + WEEKDAY_FACTOR[time.localtime(ts).tm_wday] - 1
            mv = int(base * drift * (1 + noise))
            # día de ventas (baja la cantidad) o de reposición (sube)
            if d % 2 == 0:
                q_day = max(1, q_prev - int(vol * 2 * rnd.uniform(0.8, 1.2)))
            else:
                q_day = int(qty * rnd.uniform(0.95, 1.1))
            q_show = max(1, int(q_day * (1 - SUPPLY.get(item_id, 0) * d / 13)))
            hist[day_str(ts)] = {"min": int(mv * 0.93), "mv": mv, "qty": q_show}
            q_prev = q_day
        today = day_str(now)
        cur = hist[today]
        cur["qty"] = qty
        # escenarios a propósito
        if item_id == 13452:   # Mongoose: pico de hoy, por encima de la mediana
            cur["mv"] = int(base * 1.17)
            cur["min"] = int(cur["mv"] * 0.96)
        if item_id == 6370:    # Blackmouth Oil: bajón de hoy (reactivo que usas)
            cur["mv"] = int(base * 0.84)
            cur["min"] = int(cur["mv"] * 0.96)
        if item_id == 13467:   # Icecap: la oferta se va secando y el precio sube
            days = sorted(hist)
            for k, dname in enumerate(days):
                hist[dname]["qty"] = int(270 - (270 - qty) * k / (len(days) - 1))
        if item_id == 13468:   # Black Lotus: alguien vende muy barato hoy
            cur["min"] = 41 * G
            cur["mv"] = 41 * G
        mv, mn = cur["mv"], cur["min"]
        depth = [max(1, int(qty * f)) for f in (0.2, 0.45, 0.75, 0.95)] if qty > 3 else [1, 1, 2, qty]
        m["prices"][item_id] = {"min": mn, "mv": mv, "qty": qty, "n": max(1, qty // 15), "t": now - 40 * 60,
                                "d": depth}
        m["history"][item_id] = hist

    def prof_block(recipes, name, pid, skill, mx):
        out = {"id": pid, "skill": skill, "max": mx, "t": now - 3600, "recipes": {}}
        nl = 0
        for rid, (rname, outid, (qmin, qmax), regs, diff, learned, src) in recipes.items():
            rec = {"n": rname, "l": 1 if learned else 0, "out": outid, "qmin": qmin, "qmax": qmax,
                   "r": [[i, n] for i, n in regs], "diff": diff, "ups": 1 if diff < 2 else 0}
            if src:
                rec["src"] = src
            if rid == 17187:
                rec["cdUntil"] = now + 5 * 3600
            out["recipes"][rid] = rec
            nl += 1 if learned else 0
        out["nLearned"], out["nTotal"] = nl, len(recipes)
        return name, out

    profs = {
        MAIN: [prof_block(ALCHEMY, "Alquimia", 171, 290, 300)],
        ALT: [prof_block(TAILORING, "Sastrería", 197, 262, 300), prof_block(MINING, "Minería", 186, 255, 300)],
    }
    for ck, inv in INVENTORY.items():
        c = {"market": MARKET, "money": inv["money"], "level": 7 if ck == BANK else 60, "class": {MAIN: "MAGE", ALT: "WARLOCK"}.get(ck, "ROGUE"),
             "t": now - 1800, "bags": inv["bags"], "bank": inv["bank"], "bankT": now - 7200,
             "bagSlots": {"total": inv["bagSlots"][0], "free": inv["bagSlots"][1]},
             "bankSlots": {"total": inv["bankSlots"][0], "free": inv["bankSlots"][1]},
             "professions": dict(profs.get(ck, []))}
        db["chars"][ck] = c
    # apuestas abiertas de hace unos días y el libro de compras
    def buy(days, item, qty, unit):
        return {"t": now - days * 86400, "char": MAIN, "op": "BUY", "item": item, "qty": qty, "unit": unit,
                "total": qty * unit, "src": "subasta"}
    db["ledger"] = [buy(6, 4234, 18, 30 * S), buy(5, 14256, 10, 2 * G + 55 * S), buy(4, 9206, 5, 2 * G + 20 * S),
                    {"t": now - 2 * 86400, "char": MAIN, "op": "SELL", "item": 14256, "qty": 4, "unit": 2 * G + 70 * S,
                     "total": int(4 * (2 * G + 70 * S) * 0.95), "src": "correo"},
                    {"t": now - 1 * 86400, "char": MAIN, "op": "SELL", "item": 9206, "qty": 2, "unit": 2 * G + 90 * S,
                     "total": int(2 * (2 * G + 90 * S) * 0.95), "src": "correo"}]
    due = lambda d: day_str(now + d * 86400)
    db["positions"] = {
        4234: {"qty": 18, "entry": 30 * S, "target": 56 * S, "stop": 24 * S, "due": due(12), "t": now - 6 * 86400, "char": MAIN},
        14256: {"qty": 10, "entry": 2 * G + 55 * S, "target": 3 * G + 10 * S, "stop": 2 * G + 4 * S, "due": due(3),
                "t": now - 5 * 86400, "char": MAIN},
        9206: {"qty": 5, "entry": 2 * G + 20 * S, "target": 2 * G + 75 * S, "stop": 1 * G + 76 * S, "due": due(1),
               "t": now - 4 * 86400, "char": MAIN},
    }
    db["warband"] = {"items": WARBAND["items"], "t": now - 7200,
                     "slots": {"total": WARBAND["slots"][0], "free": WARBAND["slots"][1]}}
    return db


def to_lua(v, ind=""):
    if isinstance(v, dict):
        if not v:
            return "{\n" + ind + "}"
        out = ["{"]
        for k in sorted(v, key=lambda x: (isinstance(x, str), str(x))):
            key = f"[{k}]" if isinstance(k, int) else f'["{k}"]'
            out.append(f"{ind}\t{key} = {to_lua(v[k], ind + chr(9))},")
        out.append(ind + "}")
        return "\n".join(out)
    if isinstance(v, (list, tuple)):
        out = ["{"]
        for i, x in enumerate(v, 1):
            out.append(f"{ind}\t{to_lua(x, ind + chr(9))}, -- [{i}]")
        out.append(ind + "}")
        return "\n".join(out)
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'
    return str(v)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="Addonero.lua")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\nAddoneroDB = " + to_lua(build(a.seed)) + "\n")
    print("SavedVariables sintético →", a.out)
