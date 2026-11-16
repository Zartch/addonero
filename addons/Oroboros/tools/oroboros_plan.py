#!/usr/bin/env python3
"""
Oroboros — planificador (pasos 2, 3 y 4).

Lee el SQLite del exportador y calcula:
  * qué recetas aprendidas dan dinero hoy y cuántas hacer sin hundir el precio (paso 2)
  * transformaciones: cuándo fabricar un material intermedio sale más barato que comprarlo (paso 3)
  * qué recetas/profesiones aprender y en cuántos días se pagan (paso 4)
  * qué tienes (bolsas, banco, banco de banda), cuánto vale y qué hacer con ello
  * una ruta por personaje en el formato que entiende el addon

  python oroboros_plan.py --db oroboros.sqlite --html plan.html --json plan.json
"""
import argparse
import copy
import json
import math
import os
import re
import sqlite3
import statistics
import time
from collections import defaultdict

import oroboros_ideas

AH_CUT = 0.05
TIERS = (1.10, 1.25, 1.5, 2.0)
CONF_FACTOR = {"alta": 1.0, "media": 0.75, "baja": 0.5}
MIN_MARGIN = 0.08
HERE = os.path.dirname(os.path.abspath(__file__))


def money(c, signed=False):
    if c is None:
        return "?"
    neg = c < 0
    c = int(round(abs(c)))
    g, s, cu = c // 10000, (c % 10000) // 100, c % 100
    if g:
        txt = f"{g:,}".replace(",", ".") + f"g {s:02d}s"
    elif s:
        txt = f"{s}s {cu:02d}c"
    else:
        txt = f"{cu}c"
    return ("−" if neg else ("+" if signed else "")) + txt


def num(x):
    """1.0 → 1 (los SQLite REAL vuelven como float)."""
    return int(x) if isinstance(x, float) and x.is_integer() else x


def short_char(ck):
    return ck.split("-")[0]


# ----------------------------------------------------------------------
# Carga de datos
# ----------------------------------------------------------------------
class Data:
    def __init__(self, db_path, catalog_path, now=None):
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        q = lambda sql, *a: con.execute(sql, a).fetchall()
        self.now = now or int(time.time())
        self.items = {r["item_id"]: dict(r) for r in q("SELECT * FROM items")}
        self.vendor_buy = {i: r["vendor_buy"] for i, r in self.items.items() if r["vendor_buy"]}
        self.chars = {r["char"]: dict(r) for r in q("SELECT * FROM characters")}
        markets = [c["market"] for c in self.chars.values() if c["market"]]
        self.market = max(set(markets), key=markets.count) if markets else None
        self.other_markets = sorted(set(markets) - {self.market})
        self.prices = {r["item_id"]: dict(r) for r in q("SELECT * FROM prices WHERE market=?", self.market)}
        self.history = defaultdict(list)
        for r in q("SELECT * FROM history WHERE market=? ORDER BY day", self.market):
            self.history[r["item_id"]].append(dict(r))
        self.inventory = defaultdict(dict)
        for r in q("SELECT * FROM inventory"):
            self.inventory[(r["char"], r["location"])][r["item_id"]] = r["count"]
        self.slots = {(r["char"], r["location"]): dict(r) for r in q("SELECT * FROM slots")}
        try:
            self.ledger = [dict(r) for r in q("SELECT * FROM ledger ORDER BY t")]
            self.positions = [dict(r) for r in q("SELECT * FROM positions")]
        except sqlite3.OperationalError:      # SQLite de una versión anterior
            self.ledger, self.positions = [], []
        try:
            self.config = {r["key"]: r["value"] for r in q("SELECT * FROM config")}
        except sqlite3.OperationalError:
            self.config = {}
        self.professions = defaultdict(dict)
        for r in q("SELECT * FROM professions"):
            self.professions[r["char"]][r["profession"]] = dict(r)
        reagents = defaultdict(list)
        for r in q("SELECT * FROM reagents"):
            reagents[r["recipe_id"]].append((r["item_id"], num(r["qty"])))
        with open(catalog_path, encoding="utf-8") as fh:
            self.catalog = json.load(fh)
        cat = self.catalog.get("recipes", {})
        self.recipes = []
        for r in q("SELECT * FROM recipes"):
            extra = cat.get(str(r["recipe_id"]), {})
            self.recipes.append({
                "id": r["recipe_id"], "char": r["char"], "prof": r["profession"], "name": r["name"],
                "learned": bool(r["learned"]), "out": r["output_item"],
                "yield": num(((r["qmin"] or 1) + (r["qmax"] or r["qmin"] or 1)) / 2),
                "reagents": reagents.get(r["recipe_id"], []), "source": r["source"],
                "cd_until": r["cd_until"], "enchant": bool(r["enchant"]),
                "cooldown_h": extra.get("cooldown_h") or (24 if r["cd_until"] else None),
                "skill_req": extra.get("skill"), "learn_cost": extra.get("learn_cost"),
                "learn_note": extra.get("learn_note"),
            })
        # recetas aprendidas sin enfriamiento → fuentes para fabricar intermedios
        self.craft_sources = defaultdict(list)
        for r in self.recipes:
            if r["learned"] and r["out"] and not r["cooldown_h"] and not r["enchant"]:
                self.craft_sources[r["out"]].append(r)
        self.today = time.strftime("%Y-%m-%d", time.localtime(self.now))
        self._stats = {}
        self._src = {}

    def name(self, item_id):
        it = self.items.get(item_id)
        return (it and it["name"]) or f"item:{item_id}"

    def stack(self, item_id):
        it = self.items.get(item_id)
        return (it and it["stack"]) or 1

    # ------------------------------------------------------------------
    # Estadísticas de mercado
    # ------------------------------------------------------------------
    def stats(self, item_id):
        if item_id in self._stats:
            return self._stats[item_id]
        p = self.prices.get(item_id)
        h = self.history.get(item_id, [])
        past = [x for x in h if x["day"] < self.today]
        last7 = [x["mv"] for x in past[-7:] if x["mv"]]
        med7 = statistics.median(last7) if len(last7) >= 3 else None
        mvs = [x["mv"] for x in h[-14:] if x["mv"]]
        cv = statistics.pstdev(mvs) / statistics.mean(mvs) if len(mvs) >= 4 else None
        qtys = [x["qty"] for x in h if x["qty"] is not None]
        drops = [max(0, a - b) for a, b in zip(qtys, qtys[1:])]
        vol = statistics.mean(drops) if len(drops) >= 3 else None
        qty = p["qty"] if p else 0
        if vol is None and qty:
            vol = qty * 0.1
        cur = p["mv"] if p and qty else None
        note = None
        if cur and med7:
            sell = min(cur, med7 * 1.15)
            if cur > med7 * 1.15:
                note = (f"Hoy está a {money(cur)}, muy por encima de su mediana de 7 días ({money(med7)}): "
                        f"cuento con {money(sell)} para no fiarme de un pico.")
        elif cur:
            sell = cur
        elif med7:
            sell = med7
            note = f"Ahora no hay nadie vendiendo: uso la mediana de 7 días ({money(med7)})."
        else:
            sell = None
        trend = None
        if len(mvs) >= 6:
            trend = statistics.mean(mvs[-3:]) / statistics.mean(mvs[:-3]) - 1
        days = len(h)
        if days < 4 or vol is None or (cv or 0) > 0.2 or vol < 3:
            conf = "baja"
        elif (cv or 0) > 0.12 or vol < 10 or days < 7:
            conf = "media"
        else:
            conf = "alta"
        depth = self._depth(p)
        depth_est = bool(depth) and not self._depth_real(p)
        if depth_est and conf == "alta":
            conf = "media"          # sin profundidad real (precio de Auctionator) no damos confianza alta
        age_h = (self.now - p["t"]) / 3600 if p and p["t"] else None
        st = {"min": p["min"] if p else None, "mv": cur, "qty": qty, "med7": med7, "cv": cv, "vol": vol,
              "sell": sell, "sell_note": note, "trend": trend, "days": days, "conf": conf, "age_h": age_h,
              "depth": depth, "depth_est": depth_est, "src": (p or {}).get("src")}
        self._stats[item_id] = st
        return st

    @staticmethod
    def _depth_real(p):
        return bool(p) and all(p.get(k) is not None for k in ("d110", "d125", "d150", "d200"))

    @staticmethod
    def _depth(p):
        if not p or not p["qty"]:
            return None
        d = [p.get("d110"), p.get("d125"), p.get("d150"), p.get("d200")]
        if any(x is None for x in d):
            d = [max(1, int(p["qty"] * f)) for f in (0.2, 0.45, 0.75, 0.95)]
        return d

    def buy_unit(self, item_id, n):
        """Coste medio y precio máximo para comprar n unidades en subasta (o None si no hay tantas)."""
        p = self.prices.get(item_id)
        st = self.stats(item_id)
        if not p or not p["qty"] or not st["depth"]:
            return None
        mn, mv = p["min"], p["mv"] or p["min"]
        for mult, d in zip(TIERS, st["depth"]):
            if n <= d:
                marginal = mn * mult
                avg = mv if mult == TIERS[0] else (mv + marginal) / 2
                return max(avg, mn), marginal
        return None

    # ------------------------------------------------------------------
    # Paso 3: de dónde sale cada material (vendedor, subasta o fabricarlo)
    # ------------------------------------------------------------------
    def best_source(self, item_id, n, stack=()):
        key = (item_id, max(1, int(math.ceil(n))), stack)
        if key in self._src:
            return self._src[key]
        opts = []
        if item_id in self.vendor_buy:
            opts.append({"method": "vendedor", "unit": self.vendor_buy[item_id]})
        ah = self.buy_unit(item_id, n)
        if ah:
            opts.append({"method": "subasta", "unit": ah[0], "max": ah[1]})
        if len(stack) < 4 and item_id not in stack:
            for r in self.craft_sources.get(item_id, []):
                crafts = math.ceil(n / r["yield"])
                children, total = [], 0
                for rid, rq in r["reagents"]:
                    c = self.best_source(rid, rq * crafts, stack + (item_id,))
                    if c is None:
                        break
                    children.append({"item": rid, "name": self.name(rid), "per_craft": rq, **c})
                    total += c["unit"] * rq
                else:
                    opts.append({"method": "fabricar", "unit": total / r["yield"], "recipe": r["id"],
                                 "recipe_name": r["name"], "char": r["char"], "yield": r["yield"],
                                 "children": children})
        if not opts:
            self._src[key] = None
            return None
        best = dict(min(opts, key=lambda o: o["unit"]))
        best["alts"] = {o["method"]: o["unit"] for o in opts}
        self._src[key] = best
        return best


# ----------------------------------------------------------------------
# Paso 2: evaluar una receta
# ----------------------------------------------------------------------
def evaluate(data, r, horizon_h, crafts_override=None):
    out = {"recipe": r["id"], "name": r["name"], "char": r["char"], "prof": r["prof"],
           "out_item": r["out"], "learned": r["learned"]}
    if r["enchant"] or not r["out"]:
        out["reason"] = "Encantamiento sobre equipo: no produce un objeto que se pueda vender en subasta."
        return out
    st = data.stats(r["out"])
    if not st["sell"]:
        out["reason"] = "No hay precio de venta (nunca se ha visto en subasta)."
        return out
    y = r["yield"]
    vol = st["vol"] or 0
    cap_units = vol * horizon_h / 24
    if st["qty"]:
        cap_units = min(cap_units, max(2, st["qty"] * 0.3))
    crafts = max(1, int(cap_units / y))
    cd_note = None
    if r["cooldown_h"]:
        crafts = min(crafts, max(1, int(horizon_h // r["cooldown_h"])))
        cd_note = f"Tiene enfriamiento de {r['cooldown_h']:.0f} h: como mucho {crafts} en {horizon_h} h."
        if r["cd_until"] and r["cd_until"] > data.now:
            cd_note += f" Disponible dentro de {(r['cd_until'] - data.now) / 3600:.0f} h."

    if crafts_override:
        crafts = crafts_override
    nodes = None
    while crafts >= 1:
        nodes = []
        for rid, rq in r["reagents"]:
            src = data.best_source(rid, rq * crafts)
            if src is None:
                nodes = None
                break
            nodes.append({"item": rid, "name": data.name(rid), "per_craft": rq, **src})
        if nodes is not None:
            break
        crafts //= 2
    if not nodes:
        missing = [data.name(rid) for rid, rq in r["reagents"] if data.best_source(rid, rq) is None]
        out["reason"] = ("No se pueden conseguir los materiales: " + ", ".join(missing)
                         if missing else "No hay suficientes materiales en subasta.")
        return out

    cost = sum(n["unit"] * n["per_craft"] for n in nodes)
    deposit = 100 if data.stack(r["out"]) == 1 else 100 / max(1, crafts)
    net = st["sell"] * (1 - AH_CUT)
    profit = net * y - cost - deposit
    margin = profit / cost if cost else 0
    breakeven = (cost + deposit) / y / (1 - AH_CUT)
    units = num(crafts * y)
    out.update({
        "crafts": crafts, "units": units, "yield": y, "cost": cost, "sell": st["sell"], "net": net,
        "profit": profit, "profit_total": profit * crafts, "margin": margin, "breakeven": breakeven,
        "min_sell": int(math.ceil(breakeven * 1.05)), "conf": st["conf"], "vol": st["vol"], "qty": st["qty"],
        "cv": st["cv"], "trend": st["trend"], "tree": nodes, "cooldown_h": r["cooldown_h"],
        "investment": None,
    })

    # Explicación en lenguaje llano
    parts = []
    for n in nodes:
        how = {"vendedor": "vendedor", "subasta": "subasta", "fabricar": "lo fabricas"}[n["method"]]
        parts.append(f"{n['per_craft']:g}× {n['name']} ({money(n['unit'] * n['per_craft'])}, {how})")
    why = [
        f"Materiales por unidad: {money(cost)} = " + " + ".join(parts) + ".",
        f"Se vende a {money(st['sell'])}; quitando el 5 % de la subasta te quedan {money(net)}.",
        f"{'Ganas' if profit > 0 else 'Pierdes'} {money(abs(profit))} por unidad ({margin * 100:.0f} % sobre el coste).",
    ]
    if st["vol"] is not None:
        why.append(f"Hay {st['qty']} publicadas y se venden unas {st['vol']:.0f} al día (estimación). "
                   f"Propongo {units:g} en {horizon_h} h para no hundir el precio.")
    if st["sell_note"]:
        why.append(st["sell_note"])
    for n in nodes:
        if n["method"] == "fabricar" and "subasta" in n["alts"]:
            why.append(f"{n['name']}: fabricarlo tú ({money(n['unit'])}) sale más barato que comprarlo "
                       f"({money(n['alts']['subasta'])}).")
        elif n["method"] == "subasta" and "fabricar" in n["alts"]:
            why.append(f"{n['name']}: comprarlo ({money(n['unit'])}) sale más barato que fabricarlo "
                       f"({money(n['alts']['fabricar'])}).")
    if cd_note:
        why.append(cd_note)
    if st["cv"] is not None and st["cv"] > 0.12:
        why.append(f"Ojo: el precio se mueve mucho (±{st['cv'] * 100:.0f} % en 14 días).")
    if st["trend"] is not None and abs(st["trend"]) > 0.05:
        why.append(f"Tendencia de los últimos días: {'sube' if st['trend'] > 0 else 'baja'} "
                   f"{abs(st['trend']) * 100:.0f} %.")
    out["why"] = why
    if profit <= 0:
        out["reason"] = (f"Pierdes {money(-profit)} por unidad: los materiales ({money(cost)}) cuestan más "
                         f"que lo que cobras al venderlo ({money(net * y)}).")
    elif margin < MIN_MARGIN:
        out["reason"] = f"Margen demasiado pequeño ({margin * 100:.1f} %): no compensa el riesgo ni el tiempo."
    return out


# ----------------------------------------------------------------------
# Rutas: reparto de stock, compras, fabricación y ventas por personaje
# ----------------------------------------------------------------------
class RoutePlan:
    def __init__(self, data, banker=None):
        self.data = data
        self.banker = banker        # personaje que hace todas las compras y ventas en subasta (o None)
        self.pool = {}
        for (ch, loc), items in data.inventory.items():
            for it, n in items.items():
                self.pool[(ch, loc, it)] = n
        self.chars = {ck: {"withdraw": defaultdict(int), "mail_in": defaultdict(int), "mail_out": [],
                           "buy": {}, "vendor": defaultdict(int), "craft": [], "sell": [], "stock_sell": [],
                           "flip_buy": [], "flip_sell": [], "spend": 0.0} for ck in data.chars}
        self.used = defaultdict(int)          # (char, loc, item) → usado por la ruta

    def clone(self):
        c = RoutePlan.__new__(RoutePlan)
        c.data = self.data
        c.banker = self.banker
        c.pool = dict(self.pool)
        c.chars = copy.deepcopy(self.chars)
        c.used = defaultdict(int, self.used)
        return c

    def take(self, item, qty, char):
        order = [(char, "bags"), (char, "bank"), ("Banda", "warband")]
        others = sorted((o for o in self.data.chars if o != char), key=lambda o: o != self.banker)
        order += [(o, l) for o in others for l in ("bags", "bank")]
        got = []
        for owner, loc in order:
            have = self.pool.get((owner, loc, item), 0)
            if have <= 0 or qty <= 0:
                continue
            n = min(have, qty)
            self.pool[(owner, loc, item)] = have - n
            self.used[(owner, loc, item)] += n
            qty -= n
            got.append((owner, loc, n))
            c = self.chars[char]
            if owner == char and loc == "bank":
                c["withdraw"][item] += n
            elif loc == "warband":
                c["withdraw"][("warband", item)] += n
            elif owner != char:
                c["mail_in"][(owner, item)] += n
                oc = self.chars[owner]
                if loc == "bank":
                    oc["withdraw"][item] += n
                oc["mail_out"].append((char, item, n))
        return got, qty

    def ship(self, frm, to, item, qty):
        """Correo entre personajes."""
        if frm == to or qty <= 0:
            return
        self.chars[frm]["mail_out"].append((to, item, qty))
        self.chars[to]["mail_in"][(frm, item)] += qty

    def expand(self, item, qty, char, node):
        got, rem = self.take(item, qty, char)
        owned = sum(n for _, _, n in got)
        if rem <= 0:
            return owned
        if node["method"] == "fabricar":
            crafter = node["char"]
            crafts = math.ceil(rem / node["yield"])
            for ch in node["children"]:
                owned += self.expand(ch["item"], ch["per_craft"] * crafts, crafter, ch)
            self.chars[crafter]["craft"].append((node["recipe"], crafts, node["recipe_name"]))
            if crafter != char:
                self.chars[crafter]["mail_out"].append((char, item, rem))
                self.chars[char]["mail_in"][(crafter, item)] += rem
        elif node["method"] == "vendedor":
            self.chars[char]["vendor"][item] += rem
            self.chars[char]["spend"] += rem * node["unit"]
        else:
            buyer = self.banker or char      # con banquero, él compra y lo envía a quien lo necesita
            b = self.chars[buyer]["buy"].setdefault(item, {"qty": 0, "max": 0, "spend": 0})
            b["qty"] += rem
            b["max"] = max(b["max"], node.get("max") or node["unit"])
            b["spend"] += rem * node["unit"]
            self.chars[buyer]["spend"] += rem * node["unit"]
            self.ship(buyer, char, item, rem)
        return owned

    def spend(self):
        return sum(c["spend"] for c in self.chars.values())


def apply_opportunity(plan, opp):
    owned = 0
    for n in opp["tree"]:
        owned += plan.expand(n["item"], n["per_craft"] * opp["crafts"], opp["char"], n)
    plan.chars[opp["char"]]["craft"].append((opp["recipe"], opp["crafts"], opp["name"]))
    seller = plan.banker or opp["char"]      # con banquero, el artesano le envía lo fabricado
    plan.ship(opp["char"], seller, opp["out_item"], opp["units"])
    plan.chars[seller]["sell"].append((opp["out_item"], opp["units"], opp["min_sell"]))
    return owned


def select(data, plan, opps, budget, horizon_h):
    chosen = []
    # inversión que necesitaría cada oportunidad por separado (lo que ya tienes no cuenta)
    for o in opps:
        t = plan.clone()
        (apply_opportunity if o["kind"] == "craft" else apply_flip)(t, o)
        o["solo_investment"] = t.spend()
    # primero lo que más rinde por cada oro invertido, ponderado por confianza
    key = lambda o: o["profit_total"] * CONF_FACTOR[o["conf"]] / (o["solo_investment"] + 50000)
    for o in sorted(opps, key=key, reverse=True):
        for attempt in range(3):
            trial = plan.clone()
            before = trial.spend()
            if o["kind"] == "craft":
                owned = apply_opportunity(trial, o)
            else:
                owned = apply_flip(trial, o)
            inv = trial.spend() - before
            if before + inv <= budget:
                plan.__dict__.update(trial.__dict__)
                o["investment"], o["included"] = inv, True
                o["owned_used"] = owned
                chosen.append(o)
                break
            room = budget - before
            if room <= 0 or o["crafts"] <= 1:
                break
            scale = max(0.0, room / inv) * 0.95
            new = int(o["crafts"] * scale)
            if new < 1:
                break
            if o["profit"] * new < 10000:
                break
            if o["kind"] == "craft":
                r = next(x for x in data.recipes if x["id"] == o["recipe"] and x["char"] == o["char"])
                o.update(evaluate(data, r, horizon_h, crafts_override=new))   # recalcula precios para la nueva cantidad
            else:
                o["profit_total"] = o["profit"] * new
                o["crafts"], o["units"] = new, num(new * o.get("yield", 1))
            o.setdefault("why", []).append(f"Reducido a {new} para que quepa en el presupuesto.")
        else:
            pass
        if not o.get("included"):
            o["included"] = False
            o["skip"] = "No cabe en el presupuesto." if o.get("reason") is None else o["reason"]
    return chosen


# ----------------------------------------------------------------------
# Reventa (comprar barato lo que alguien ha tirado de precio)
# ----------------------------------------------------------------------
def find_flips(data, horizon_h, char):
    flips = []
    for item_id, p in data.prices.items():
        st = data.stats(item_id)
        if not p["qty"] or not st["med7"] or not st["vol"] or not st["depth"]:
            continue
        if p["min"] >= st["med7"] * 0.75 or st["vol"] < 0.5:
            continue
        qty = max(1, min(st["depth"][0], int(st["vol"] * horizon_h / 24)))
        buy = data.buy_unit(item_id, qty)
        if not buy:
            continue
        sell = st["med7"] * 0.97
        profit = sell * (1 - AH_CUT) - buy[0]
        if profit <= 0 or profit * qty < 10000:     # menos de 1g no merece los clics
            continue
        conf = "media" if st["vol"] >= 5 and (st["cv"] or 0) < 0.15 else "baja"
        flips.append({
            "kind": "flip", "char": char, "name": f"Reventa: {data.name(item_id)}", "out_item": item_id,
            "crafts": qty, "units": qty, "yield": 1, "cost": buy[0], "sell": sell, "net": sell * (1 - AH_CUT),
            "profit": profit, "profit_total": profit * qty, "margin": profit / buy[0], "conf": conf,
            "max_buy": int(math.ceil(buy[1])), "min_sell": int(math.ceil(buy[0] * 1.1 / (1 - AH_CUT))),
            "vol": st["vol"], "qty": st["qty"],
            "why": [
                f"Ahora se vende a {money(p['min'])} y su mediana de 7 días es {money(st['med7'])} "
                f"({(1 - p['min'] / st['med7']) * 100:.0f} % más barato).",
                f"Compras {qty} y las vuelves a poner a ~{money(sell)}: ganas {money(profit)} cada una.",
                f"Solo hay {st['depth'][0]}{' (estimado: sin búsqueda propia)' if st['depth_est'] else ''} a ese precio y se venden unas {st['vol']:.0f} al día: "
                "es una oportunidad puntual y con riesgo (puede que el precio no vuelva).",
            ],
        })
    return flips


def apply_flip(plan, f):
    c = plan.chars[f["char"]]
    c["flip_buy"].append((f["out_item"], f["units"], f["max_buy"]))
    c["flip_sell"].append((f["out_item"], f["units"], f["min_sell"]))
    c["spend"] += f["cost"] * f["units"]
    return 0


# ----------------------------------------------------------------------
# Paso 4: qué aprender
# ----------------------------------------------------------------------
def learn_suggestions(data, horizon_h):
    out = []
    cands = [r for r in data.recipes if not r["learned"]]
    for prof, info in data.catalog.get("professions", {}).items():
        if any(prof in p for p in data.professions.values()):
            continue
        for rid, cr in info.get("recipes", {}).items():
            cands.append({"id": int(rid), "char": None, "prof": prof, "name": cr["n"], "learned": False,
                          "out": cr["out"], "yield": cr.get("yield", 1), "reagents": [tuple(x) for x in cr["r"]],
                          "source": cr.get("src"), "cd_until": None, "enchant": False,
                          "cooldown_h": cr.get("cooldown_h"), "skill_req": cr.get("skill"),
                          "learn_cost": cr.get("learn_cost"), "learn_note": info.get("level_note"),
                          "new_profession": True})
    for r in cands:
        e = evaluate(data, r, 24)
        if "profit" not in e:
            e.update({"daily_profit": None})
        else:
            per_day = (e["vol"] or 0) / r["yield"]
            if r["cooldown_h"]:
                per_day = min(per_day, 24 / r["cooldown_h"])
            e["per_day"] = per_day
            e["daily_profit"] = e["profit"] * per_day if e["profit"] > 0 else e["profit"] * per_day
        cost = r.get("learn_cost")
        if cost is None and r.get("source"):
            m = re.search(r"(\d+)g(?:\s*(\d+)s)?", r["source"])
            if m:
                cost = int(m.group(1)) * 10000 + int(m.group(2) or 0) * 100
        e["learn_cost"] = cost
        e["source"] = r.get("source")
        e["learn_note"] = r.get("learn_note")
        e["new_profession"] = r.get("new_profession", False)
        skill = None
        if r["char"]:
            skill = (data.professions.get(r["char"], {}).get(r["prof"]) or {}).get("skill")
        e["skill"], e["skill_req"] = skill, r.get("skill_req")
        e["skill_gap"] = max(0, (r.get("skill_req") or 0) - (skill or 0)) if skill is not None and r.get("skill_req") else None
        dp = e.get("daily_profit")
        e["payback_days"] = (cost / dp) if (cost and dp and dp > 0) else (0 if dp and dp > 0 and not cost else None)
        verdict = []
        if dp is None:
            verdict.append(e.get("reason", "Sin datos suficientes."))
        elif dp <= 0:
            verdict.append(f"Hoy no compensa: {e.get('reason', 'pierde dinero')}")
        else:
            verdict.append(f"≈{money(dp)} al día (vendiendo ~{e['per_day']:.1f}/día con el mercado de hoy).")
            if cost:
                pb = e["payback_days"]
                verdict.append(f"Aprenderla cuesta {money(cost)}: se paga en "
                               + ("menos de un día." if pb < 1 else f"{pb:.1f} días."))
            if e["skill_gap"]:
                verdict.append(f"Te faltan {e['skill_gap']} puntos de {r['prof']} ({skill}/{r['skill_req']}).")
            elif skill is not None and r.get("skill_req"):
                verdict.append(f"Ya tienes el nivel ({skill}/{r['skill_req']}).")
            if r.get("learn_note"):
                verdict.append(r["learn_note"])
            if r.get("source"):
                verdict.append(f"Dónde: {r['source']}.")
        e["verdict"] = verdict
        out.append(e)
    out.sort(key=lambda e: (e.get("daily_profit") is None, -(e.get("daily_profit") or -1e12)))
    return out


# ----------------------------------------------------------------------
# Paso 3 (tabla): transformaciones
# ----------------------------------------------------------------------
def transformations(data):
    rows = []
    for item_id, recipes in data.craft_sources.items():
        src = data.best_source(item_id, 1)
        if not src or "fabricar" not in src["alts"]:
            continue
        craft = src["alts"]["fabricar"]
        buy = src["alts"].get("subasta") or src["alts"].get("vendedor")
        st = data.stats(item_id)
        net = st["sell"] * (1 - AH_CUT) if st["sell"] else None
        r = recipes[0]
        chain = " + ".join(f"{q:g}× {data.name(i)}" for i, q in r["reagents"]) + f" → {data.name(item_id)}"
        rows.append({
            "item": item_id, "name": data.name(item_id), "recipe": r["name"], "char": short_char(r["char"]),
            "chain": chain, "craft": craft, "buy": buy, "net": net,
            "saving": (buy - craft) if buy else None,
            "value_added": (net - craft) if net else None,
            "depth": _chain_depth(src),
            "advice": (
                "Fabrícalo: sale más barato que comprarlo." if buy and craft < buy * 0.97 else
                "Cómpralo: fabricarlo no ahorra." if buy and craft >= buy else
                "Casi igual: compra si tienes prisa."),
        })
    rows.sort(key=lambda r: -(r["value_added"] or -1e12))
    return rows


def _chain_depth(node):
    if node.get("method") != "fabricar":
        return 0
    return 1 + max((_chain_depth(c) for c in node["children"]), default=0)


# ----------------------------------------------------------------------
# Qué tienes
# ----------------------------------------------------------------------
def inventory_view(data, plan, learn, horizon_h, positions=None, bets=None):
    positions, bets = positions or {}, bets or {}
    reserve = {}

    def walk(nodes, why):
        for n in nodes or []:
            reserve.setdefault(n["item"], why)
            walk(n.get("children"), why)

    for r in data.recipes:     # materiales de recetas con enfriamiento: se usan cada día
        if r["learned"] and r["cooldown_h"]:
            for it, _ in r["reagents"]:
                reserve.setdefault(it, f"{r['name']} (enfriamiento: lo usarás en la próxima)")
    for e in learn[:6]:
        if e.get("daily_profit") and e["daily_profit"] > 0 and (e.get("payback_days") or 0) <= 7 \
                and not e.get("new_profession"):
            walk(e.get("tree"), f"{e['name']}, que te conviene aprender")
    owners = list(data.chars) + ["Banda"]
    views = []
    for ow in owners:
        locs = ("bags", "bank") if ow != "Banda" else ("warband",)
        entries = []
        for loc in locs:
            for item, count in sorted(data.inventory.get((ow, loc), {}).items()):
                st = data.stats(item)
                ah = st["sell"] * (1 - AH_CUT) if st["sell"] else None
                vend = (data.items.get(item) or {}).get("vendor_sell") or 0
                used = plan.used.get((ow, loc, item), 0)
                free = count - used
                unit = max(ah or 0, vend)
                stack = data.stack(item)
                slots = math.ceil(count / stack)
                if used and free <= 0:
                    action, why = "ruta", f"La ruta usa las {used}."
                elif item in positions:
                    action, why = "cartera", "Apuesta abierta. " + positions[item]["advice"]
                elif item in bets and ah:
                    action, why = "guardar", (f"Guárdalo: hoy hay señal de compra ({bets[item]}); "
                                              "mira la pestaña Ideas antes de venderlo.")
                elif item in reserve:
                    action, why = "guardar", f"Guárdalo: es material de {reserve[item]}."
                elif ah and ah >= vend * 1.2 and (st["vol"] or 0) >= 1:
                    action = "subasta"
                    why = f"Véndelo en subasta (~{money(ah)} neto cada uno)."
                    if used:
                        why = f"La ruta usa {used}; el resto ({free}) véndelo en subasta."
                elif vend:
                    action = "vendedor"
                    why = (f"Al vendedor: {money(vend)} cada uno"
                           + (f" (en subasta solo sacas {money(ah)})." if ah else " (no se vende en subasta)."))
                else:
                    action, why = "nada", "Sin valor de venta conocido."
                if used and action in ("guardar", "vendedor", "nada"):
                    why = f"La ruta usa {used}; con el resto ({free}): " + why[0].lower() + why[1:]
                entries.append({"item": item, "name": data.name(item), "loc": loc, "count": count, "used": used,
                                "free": free, "unit": unit, "ah": ah, "vendor": vend, "total": unit * count,
                                "slots": slots, "per_slot": unit * count / slots if slots else 0,
                                "action": action, "why": why})
        slot_info = {loc: data.slots.get((ow, loc)) for loc in locs}
        views.append({"owner": ow, "short": short_char(ow) if ow != "Banda" else "Banco de banda",
                      "money": (data.chars.get(ow) or {}).get("money"), "slots": slot_info, "items": entries,
                      "value": sum(e["total"] for e in entries)})
    return views, reserve


def add_stock_sales(data, plan, views, horizon_h):
    def selling(item):
        tot = 0
        for c in plan.chars.values():
            tot += sum(q for i, q, _ in c["sell"] + c["stock_sell"] + c["flip_sell"] if i == item)
        return tot

    richest = plan.banker or max(data.chars, key=lambda k: data.chars[k]["money"] or 0)
    for v in views:
        banda = v["owner"] == "Banda"
        holder = richest if banda else v["owner"]
        seller = plan.banker or holder
        c, cs = plan.chars[holder], plan.chars[seller]
        for e in v["items"]:
            if e["action"] == "subasta" and e["free"] > 0:
                st = data.stats(e["item"])
                cap = st["vol"] * horizon_h / 24 if st["vol"] else e["free"]
                if st["qty"]:
                    cap = min(cap, max(2, st["qty"] * 0.3))
                already = selling(e["item"])
                q = min(e["free"], int(cap - already))
                if q <= 0:
                    e["action"] = "esperar"
                    e["why"] = (f"La ruta ya vende {num(already)}; guarda estas y véndelas más adelante "
                                "para no hundir el precio.")
                    continue
                if e["ah"] * q < 2000:
                    e["action"] = "vendedor"
                    e["why"] = (f"Vale muy poco ({money(e['ah'] * e['free'])} en total): véndelo al vendedor "
                                "o tíralo para liberar hueco.")
                    c.setdefault("to_vendor", []).append((e["item"], e["free"], e["loc"]))
                    continue
                if e["loc"] == "bank":
                    c["withdraw"][e["item"]] += q
                elif e["loc"] == "warband":
                    c["withdraw"][("warband", e["item"])] += q
                if seller != v["owner"]:
                    e["why"] += f" Lo vende {short_char(seller)}."
                plan.ship(holder, seller, e["item"], q)
                for k, (i, qq, mn) in enumerate(cs["sell"]):
                    if i == e["item"]:
                        cs["sell"][k] = (i, num(qq + q), mn)
                        break
                else:
                    cs["stock_sell"].append((e["item"], q, int(e["ah"] / (1 - AH_CUT) * 0.85)))
                e["sell_now"] = q
                if q < e["free"]:
                    e["why"] += f" Vende {q} ahora y el resto más adelante (el mercado no absorbe más)."
            elif e["action"] == "vendedor" and e["free"] > 0:
                c.setdefault("to_vendor", []).append((e["item"], e["free"], e["loc"]))


def add_position_sales(data, plan, views, positions):
    """Apuestas que toca vender (objetivo, stop o fecha): a la ruta de quien las tenga."""
    richest = plan.banker or max(data.chars, key=lambda k: data.chars[k]["money"] or 0)
    for item, pos in positions.items():
        if not pos["sell"]:
            continue
        left = pos["qty"]
        floor = int(pos["mv"] * (0.85 if pos["status"] == "stop" else 0.92))
        for v in views:
            holder = richest if v["owner"] == "Banda" else v["owner"]
            c = plan.chars[holder]
            for e in v["items"]:
                if e["item"] != item or e["action"] != "cartera" or left <= 0:
                    continue
                q = int(min(e["free"], left))
                left -= q
                if e["loc"] == "bank":
                    c["withdraw"][item] += q
                elif e["loc"] == "warband":
                    c["withdraw"][("warband", item)] += q
                seller = plan.banker or holder
                plan.ship(holder, seller, item, q)
                plan.chars[seller].setdefault("pos_sell", []).append((item, q, floor, pos["status"]))


# ----------------------------------------------------------------------
# Texto de ruta
# ----------------------------------------------------------------------
def route_text(data, plan, ck, generated):
    """Ruta de un personaje. Orden: preparar (banco, correo, vendedor) → comprar → fabricar → enviar → vender.
    El banquero va en dos fases: compra y reparte; cuando los artesanos terminan, recoge y vende."""
    c = plan.chars[ck]
    n = data.name
    is_banker = plan.banker == ck
    L = [f"# Ruta Oroboros — {short_char(ck)} — {generated}"]
    take_bank = [f"{q:g}× {n(i)}" for i, q in c["withdraw"].items() if not isinstance(i, tuple)]
    take_wb = [f"{q:g}× {n(i[1])}" for i, q in c["withdraw"].items() if isinstance(i, tuple)]
    if take_bank:
        L.append("NOTE Saca del banco: " + ", ".join(take_bank))
    if take_wb:
        L.append("NOTE Saca del banco de banda: " + ", ".join(take_wb))

    def mail_in():
        by = defaultdict(list)
        for (frm, i), q in c["mail_in"].items():
            by[frm].append(f"{q:g}× {n(i)}")
        return [f"NOTE Recoge del correo (de {short_char(frm)}): " + ", ".join(v) for frm, v in by.items()]

    def mail_out():
        by = defaultdict(lambda: defaultdict(float))
        for to, i, q in c["mail_out"]:
            by[to][i] += q
        return [f"NOTE Envía por correo a {short_char(to)}: " + ", ".join(f"{q:g}× {n(i)}" for i, q in v.items())
                for to, v in by.items()]

    if not is_banker:
        L += mail_in()
    for i, q in c["vendor"].items():
        L.append(f"NOTE Compra al vendedor: {q:g}× {n(i)}")
    for v in c.get("to_vendor", []):
        L.append(f"NOTE Vende al vendedor: {v[1]}× {n(v[0])}" + {"bank": " (está en el banco)", "warband": " (está en el banco de banda)"}.get(v[2], ""))
    for i, b in c["buy"].items():
        L.append(f"BUY {i} {b['qty']:g} {int(math.ceil(b['max'] * 1.02))}   # {n(i)}")
    for i, q, mx in c["flip_buy"]:
        L.append(f"BUY {i} {q} {mx}   # reventa: {n(i)}")
    merged = defaultdict(int)
    names = {}
    order = []
    for rid, crafts, name in c["craft"]:
        if rid not in merged:
            order.append(rid)
        merged[rid] += crafts
        names[rid] = name
    for rid in order:
        L.append(f"CRAFT {rid} {merged[rid]}   # {names[rid]}")
    L += mail_out()
    if is_banker and c["mail_in"]:
        who = sorted({short_char(frm) for frm, _ in c["mail_in"]})
        L.append("NOTE Ahora entra con " + ", ".join(who) + " y haz su parte; después vuelve aquí")
        L += mail_in()
    for i, q, mn in c["sell"]:
        L.append(f"SELL {i} {q:g} {mn}   # {n(i)}")
    for i, q, mn in c["flip_sell"]:
        L.append(f"SELL {i} {q} {mn}   # reventa: {n(i)}")
    for i, q, mn in c["stock_sell"]:
        L.append(f"SELL {i} {q} {mn}   # stock: {n(i)}")
    for i, q, mn, why in c.get("pos_sell", []):
        L.append(f"SELL {i} {q} {mn}   # cartera ({why}): {n(i)}")
    return "\n".join(L) + "\n"


def combined_route(routes, order, title):
    """Una sola ruta con secciones CHAR: se pega una vez y el addon reparte cada parte a su personaje."""
    out = [f"# {title}"]
    for ck in order:
        body = [l for l in routes[ck]["text"].splitlines() if l and not l.startswith("#")]
        if body:
            out.append(f"CHAR {routes[ck]['short']}")
            out += body
    return "\n".join(out) + "\n"


def count_clicks(text):
    k = {"BUY": 3, "SELL": 2, "CRAFT": 1, "NOTE": 1, "HOLD": 1}
    return sum(k.get(l.split()[0], 0) for l in text.splitlines() if l and not l.startswith("#"))


# ----------------------------------------------------------------------
# Plan completo
# ----------------------------------------------------------------------
def pick_banker(data, name=None):
    """El banquero: --banker Nombre, o el marcado en el juego con /oro banquero."""
    want = name or data.config.get("banker")
    if not want or want == "none":
        return None
    for ck in data.chars:
        if ck == want or short_char(ck).lower() == want.lower():
            return ck
    raise SystemExit(f"No conozco al personaje «{want}». Personajes: " + ", ".join(short_char(c) for c in data.chars))


def build_plan(data, horizon_h=48, budget_pct=0.8, synthetic=False, spec_pct=0.15, banker=None):
    total_gold = sum(c["money"] or 0 for c in data.chars.values())
    budget = total_gold * budget_pct
    banker = pick_banker(data, banker)
    richest = banker or max(data.chars, key=lambda k: data.chars[k]["money"] or 0)

    evaluated = [evaluate(data, r, horizon_h) for r in data.recipes if r["learned"]]
    good, bad = [], []
    for e in evaluated:
        (bad if e.get("reason") else good).append(e)
    for e in good:
        e["kind"] = "craft"
    flips = find_flips(data, horizon_h, richest)

    plan = RoutePlan(data, banker)
    learn = learn_suggestions(data, horizon_h)
    chosen = select(data, plan, good + flips, budget, horizon_h)

    portfolio = oroboros_ideas.portfolio(data)
    open_pos = {p["item"]: p for p in portfolio["positions"] if p["status"] != "cerrada"}
    bets = oroboros_ideas.hold_signals(data, {f["out_item"] for f in flips})
    views, reserve = inventory_view(data, plan, learn, horizon_h, open_pos, bets)
    add_stock_sales(data, plan, views, horizon_h)
    add_position_sales(data, plan, views, open_pos)

    gen = time.strftime("%d/%m %H:%M", time.localtime(data.now))
    routes = {}
    for ck in data.chars:
        text = route_text(data, plan, ck, gen + (" (datos sintéticos)" if synthetic else ""))
        c = plan.chars[ck]
        need = c["spend"]
        money_ = data.chars[ck]["money"] or 0
        routes[ck] = {"short": short_char(ck), "text": text, "spend": need, "money": money_,
                      "clicks": count_clicks(text),
                      "profit": sum(o["profit_total"] for o in chosen if o["char"] == ck),
                      "stock_value": sum(q * mn * (1 - AH_CUT) for _, q, mn in c["stock_sell"]),
                      "lines": len([l for l in text.splitlines() if l and not l.startswith("#")])}
    # oro entre personajes
    gold_moves = []
    for ck, r in routes.items():
        if r["spend"] > r["money"] * 0.95:
            need = r["spend"] - r["money"] * 0.9
            donor = max((k for k in routes if k != ck), key=lambda k: routes[k]["money"] - routes[k]["spend"],
                        default=None)
            if donor:
                gold_moves.append({"from": short_char(donor), "to": short_char(ck), "amount": need})
                routes[donor]["text"] = routes[donor]["text"].replace(
                    "\n", f"\nNOTE Envía {money(math.ceil(need / 10000) * 10000)} por correo a {short_char(ck)}\n", 1)
                routes[ck]["text"] = routes[ck]["text"].replace(
                    "\n", f"\nNOTE Recoge {money(math.ceil(need / 10000) * 10000)} del correo (de {short_char(donor)})\n", 1)
    # orden: el banquero primero; entre artesanos, antes el que fabrica para otro artesano
    feeds = lambda k: sum(1 for to, _, _ in plan.chars[k]["mail_out"] if to != banker)
    crafters_first = sorted(routes, key=lambda k: (k != banker, -feeds(k)))
    steps = [f"{g['from']} envía {money(math.ceil(g['amount'] / 10000) * 10000)} a {g['to']}" for g in gold_moves]
    names = [short_char(k) for k in crafters_first if routes[k]["lines"]]
    if banker and len(names) > 1:
        steps.append(f"{names[0]} compra en la subasta y envía los materiales")
        steps.append(", ".join(names[1:]) + " recogen el correo, fabrican y le devuelven lo fabricado")
        steps.append(f"{names[0]} recoge y vende")
    elif len(names) > 1:
        steps.append(f"{names[0]} hace su ruta y envía por correo lo que necesita el otro")
        steps.append("después " + ", ".join(names[1:]))
    order_txt = ("Orden: " + "; ".join(steps) + ".") if steps else "Una sola ruta."
    route_all = combined_route(routes, crafters_first,
                               f"Ruta Oroboros — todos los personajes — {gen}" + (" (datos sintéticos)" if synthetic else ""))

    # ideas de especulación: con el oro que sobra tras la ruta
    moved = defaultdict(float)
    for g in gold_moves:
        amt = math.ceil(g["amount"] / 10000) * 10000
        moved[g["from"]] -= amt
        moved[g["to"]] += amt
    leftover = {ck: r["money"] - r["spend"] + moved[r["short"]] for ck, r in routes.items()}
    buyer = banker or max(leftover, key=leftover.get)
    spec_budget = max(0, min(total_gold * spec_pct, leftover[buyer] * 0.9))
    storages = [(f"el banco de {short_char(ck)}", data.slots[(ck, "bank")]["free"])
                for ck in sorted(data.chars, key=lambda k: k != banker) if (ck, "bank") in data.slots]
    if ("Banda", "warband") in data.slots:
        storages.append(("el banco de banda", data.slots[("Banda", "warband")]["free"]))
    route_buys = defaultdict(float)
    for c in plan.chars.values():
        for it, b in c["buy"].items():
            route_buys[it] += b["qty"]
    ideas = oroboros_ideas.build_ideas(data, spec_budget, buyer, storages, route_buys,
                                       {f["out_item"] for f in flips}, horizon_h, held=set(open_pos), banker=banker)
    ideas["buyer"] = short_char(buyer)
    ideas["spec_pct"] = spec_pct

    warnings = []
    for ck in data.chars:        # recetas viejas o sin leer: el plan solo sabe lo que cada personaje enseñó al addon
        profs = data.professions.get(ck, {})
        old = [p for p, v in profs.items() if v["t"] and data.now - v["t"] > 7 * 86400]
        if old:
            warnings.append(f"{short_char(ck)}: las recetas de {', '.join(old)} se leyeron hace más de una semana. "
                            "Entra con ese personaje y abre la profesión.")
        elif not profs and ck != banker and (data.chars[ck]["level"] or 0) >= 10:
            warnings.append(f"{short_char(ck)}: no tengo sus recetas. Entra con ese personaje y abre cada profesión una vez.")
    if not banker and len(data.chars) > 1:
        warnings.append("No hay banquero marcado: cada personaje compra y vende lo suyo. "
                        "Marca uno con /oro banquero o con --banker Nombre.")
    if synthetic:
        warnings.append("Datos SINTÉTICOS: precios, inventario y recetas son inventados para probar el planificador.")
    ages = [s["age_h"] for s in (data.stats(i) for i in data.prices) if s["age_h"] is not None]
    if ages and min(ages) > 6:
        warnings.append(f"El último escaneo tiene {min(ages):.0f} h: los precios pueden haber cambiado.")
    for (ow, loc), sl in data.slots.items():
        if sl["total"] and sl["free"] / sl["total"] < 0.1:
            where = {"bags": "las bolsas", "bank": "el banco", "warband": "el banco de banda"}[loc]
            warnings.append(f"{short_char(ow)}: {where} está casi lleno ({sl['free']}/{sl['total']} huecos libres). "
                            "Mira en «Qué tienes» qué ocupa sitio y vale poco.")
    if data.other_markets:
        warnings.append("Hay personajes en otros mercados (" + ", ".join(data.other_markets) +
                        "); este plan solo usa " + str(data.market) + ".")
    for p in portfolio["positions"]:
        if p["status"] in ("stop", "objetivo", "vencida"):
            warnings.append(f"Cartera: {p['name']} — {p['advice']}")
    for g in gold_moves:
        warnings.append(f"{g['to']} no tiene oro suficiente: {g['from']} le envía {money(g['amount'])} (incluido en las rutas).")

    items_used = set()
    for o in good + bad + flips + learn:
        if o.get("out_item"):
            items_used.add(o["out_item"])
        for n in o.get("tree") or []:
            items_used.add(n["item"])
    for v in views:
        for e in v["items"]:
            items_used.add(e["item"])
    for c in ideas["ideas"]:
        items_used.add(c["item"])
    for p in portfolio["positions"]:
        items_used.add(p["item"])
    items = {}
    for i in items_used:
        st = data.stats(i)
        items[i] = {"name": data.name(i), "min": st["min"], "mv": st["mv"], "med7": st["med7"], "qty": st["qty"],
                    "vol": st["vol"], "conf": st["conf"], "cv": st["cv"], "trend": st["trend"],
                    "vendor_buy": data.vendor_buy.get(i),
                    "hist": [[h["day"], h["mv"], h["qty"]] for h in data.history.get(i, [])]}

    profit = sum(o["profit_total"] for o in chosen)
    invest = sum(o["investment"] or 0 for o in chosen)
    return {
        "generated": data.now, "generated_txt": gen, "market": data.market, "synthetic": synthetic,
        "settings": {"horizon_h": horizon_h, "budget_pct": budget_pct, "budget": budget, "min_margin": MIN_MARGIN},
        "summary": {"profit": profit, "investment": invest, "roi": profit / invest if invest else None,
                    "gold": total_gold, "stock_sale": sum(r["stock_value"] for r in routes.values()),
                    "n_chosen": len(chosen), "clicks": sum(r["clicks"] for r in routes.values()),
                    "order": [short_char(k) for k in crafters_first], "order_txt": order_txt},
        "warnings": warnings,
        "opportunities": sorted(good + flips, key=lambda o: -o["profit_total"]),
        "not_profitable": sorted(bad, key=lambda o: -(o.get("profit") or -1e12)),
        "transformations": transformations(data),
        "learn": learn,
        "ideas": ideas,
        "portfolio": portfolio,
        "inventory": views,
        "routes": routes,
        "route_all": route_all,
        "banker": short_char(banker) if banker else None,
        "chars": {k: {"short": short_char(k), "money": v["money"], "level": v["level"], "class": v["class"],
                      "professions": data.professions.get(k, {})} for k, v in data.chars.items()},
        "items": items,
    }


def write_html(plan, path):
    with open(os.path.join(HERE, "planner_ui.html"), encoding="utf-8") as fh:
        tpl = fh.read()
    blob = json.dumps(plan, ensure_ascii=False, default=str).replace("</", "<\\/")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(tpl.replace("/*__PLAN__*/null", blob))


def main():
    from oroboros_export import utf8_output
    utf8_output()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", required=True, help="SQLite generado por oroboros_export.py")
    ap.add_argument("--catalog", default=os.path.join(HERE, "catalog.json"))
    ap.add_argument("--horizon", type=int, default=48, help="horas que cubre la ruta (por defecto 48)")
    ap.add_argument("--budget", type=float, default=0.8, help="fracción del oro total que se puede invertir")
    ap.add_argument("--json", help="guardar el plan en JSON")
    ap.add_argument("--html", help="guardar la interfaz HTML")
    ap.add_argument("--routes", help="carpeta donde guardar una ruta .txt por personaje")
    ap.add_argument("--banker", help="personaje que compra y vende en la subasta (por defecto, el marcado con "
                    "/oro banquero; «none» para que cada uno compre lo suyo)")
    ap.add_argument("--spec", type=float, default=0.15, help="fracción del oro total para ideas de especulación")
    ap.add_argument("--brief", help="guardar un resumen del mercado en Markdown para pedir más ideas a un LLM")
    ap.add_argument("--synthetic", action="store_true", help="marcar el plan como datos sintéticos")
    a = ap.parse_args()

    data = Data(a.db, a.catalog)
    plan = build_plan(data, a.horizon, a.budget, a.synthetic, a.spec, a.banker)
    if a.brief:
        with open(a.brief, "w", encoding="utf-8") as fh:
            fh.write(oroboros_ideas.brief(data, plan))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, indent=1, default=str)
    if a.html:
        write_html(plan, a.html)
    if a.routes:
        os.makedirs(a.routes, exist_ok=True)
        for r in plan["routes"].values():
            with open(os.path.join(a.routes, f"ruta_{r['short']}.txt"), "w", encoding="utf-8") as fh:
                fh.write(r["text"])
        with open(os.path.join(a.routes, "ruta_todo.txt"), "w", encoding="utf-8") as fh:
            fh.write(plan["route_all"])
        with open(os.path.join(a.routes, "ideas_todo.txt"), "w", encoding="utf-8") as fh:
            fh.write(plan["ideas"]["route_all"])
        for r in plan["ideas"]["routes"].values():
            with open(os.path.join(a.routes, f"ideas_{r['short']}.txt"), "w", encoding="utf-8") as fh:
                fh.write(r["text"])
    s = plan["summary"]
    print(f"Beneficio estimado: {money(s['profit'])} invirtiendo {money(s['investment'])} "
          f"({(s['roi'] or 0) * 100:.0f} %). Oportunidades elegidas: {s['n_chosen']}.")
    i = plan["ideas"]
    print(f"Ideas: {sum(1 for c in i['ideas'] if c['included'])} con {money(i['invest'])} "
          f"→ {money(i['profit'])} si se cumplen; {money(i['loss_stop'])} de pérdida si saltan todos los stops.")
    for w in plan["warnings"]:
        print("  ! " + w)


if __name__ == "__main__":
    main()
