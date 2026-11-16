"""
Oroboros — ideas de especulación (comprar hoy para vender dentro de unos días).

Cada idea es una apuesta con su tesis, la evidencia que la apoya, precio de entrada,
objetivo, cuánto comprar, dónde guardarlo, cuándo vender y cuándo rendirse.
Los objetivos son ESCENARIOS, no predicciones: por eso van con riesgo y con stop.

Tipos:
  despensa    – reactivo que ya gastas en tus recetas y hoy está barato: compra para varios días
  rebote      – precio hundido respecto a su mediana, con ventas normales
  semanal     – barato unos días de la semana y caro otros (reinicio de bandas)
  sequia      – cada día hay menos unidades publicadas y el precio sube
  evento      – una fecha conocida (apertura de bandas…) que dispara la demanda
  progresion  – material de nivel bajo, barato mientras todos suben de nivel
"""
import math
import statistics
import time
from collections import defaultdict

AH_CUT = 0.05
RISK_FACTOR = {"bajo": 1.0, "medio": 0.7, "alto": 0.45}
LABEL = {"despensa": "Despensa", "rebote": "Rebote", "semanal": "Ciclo semanal", "sequia": "Oferta que se seca",
         "evento": "Evento", "progresion": "Progresión del servidor"}
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
STOP = 0.8            # si cae un 20 % desde la entrada, se sale
MAX_PER_TYPE = 4


def _money(c):
    if c is None:
        return "?"
    c = int(round(abs(c)))
    g, s, cu = c // 10000, (c % 10000) // 100, c % 100
    if g:
        return f"{g:,}".replace(",", ".") + f"g {s:02d}s"
    return f"{s}s {cu:02d}c" if s else f"{cu}c"


def _date(ts):
    return time.strftime("%d/%m", time.localtime(ts))


def _past(data, item):
    return [h for h in data.history.get(item, []) if h["day"] < data.today and h["mv"]]


def _med14(data, item):
    v = [h["mv"] for h in _past(data, item)[-14:]]
    return statistics.median(v) if len(v) >= 4 else None


def _slope(values):
    """Pendiente diaria relativa a la media (regresión lineal)."""
    n = len(values)
    if n < 5:
        return None
    mx, my = (n - 1) / 2, statistics.mean(values)
    den = sum((i - mx) ** 2 for i in range(n))
    return sum((i - mx) * (v - my) for i, v in enumerate(values)) / den / my


def _halves(data, item):
    """Cambio de lo publicado y del precio a lo largo del histórico."""
    h = [x for x in data.history.get(item, []) if x["qty"] is not None and x["mv"]]
    if len(h) < 10:
        return None
    # tendencia por regresión sobre todos los días: aguanta mejor los dientes de sierra de compras y reposiciones
    qs, ps = [x["qty"] for x in h], [x["mv"] for x in h]
    dq, dp = (_slope(qs) or 0) * (len(h) - 1), (_slope(ps) or 0) * (len(h) - 1)
    qm = statistics.mean(qs)
    q0, q1 = qm * (1 - dq / 2), qm * (1 + dq / 2)
    if q0 <= 0:
        return None
    return {"qty": q1 / q0 - 1, "price": dp, "s5": _slope(ps[-5:]), "q0": q0, "q1": q1}


def outlook(data, uses):
    """En qué momento está el servidor, leído en el propio mercado: si los materiales de nivel bajo
    escasean y los de nivel alto abundan, la gente ya está arriba. No depende de ninguna hermandad."""
    out = {"days_since_launch": None, "low": None, "high": None, "events": [], "text": []}
    srv = data.catalog.get("server", {})
    if srv.get("launch"):
        launch = time.mktime(time.strptime(srv["launch"], "%Y-%m-%d"))
        out["days_since_launch"] = int((data.now - launch) // 86400)
        out["text"].append(f"El servidor lleva {out['days_since_launch']} días abierto.")
    thr = srv.get("low_level_max_ilvl", 40)
    groups = {"low": [], "high": []}
    for item in data.prices:
        ilvl = (data.items.get(item) or {}).get("ilvl")
        hv = _halves(data, item)
        if not ilvl or not hv or item not in uses:
            continue                                   # solo materiales (lo que se usa en recetas)
        if ilvl <= thr:
            groups["low"].append(hv)
        elif ilvl >= 50:
            groups["high"].append(hv)
    for k in groups:
        if len(groups[k]) >= 3:
            out[k] = {"n": len(groups[k]), "qty": statistics.median(g["qty"] for g in groups[k]),
                      "price": statistics.median(g["price"] for g in groups[k])}
    lo, hi = out["low"], out["high"]
    f = lambda x: f"{'+' if x >= 0 else '−'}{abs(x) * 100:.0f} %"
    if lo:
        out["text"].append(f"Materiales de nivel bajo ({lo['n']} objetos), últimas dos semanas: oferta {f(lo['qty'])}, "
                           f"precio {f(lo['price'])}.")
    if hi:
        out["text"].append(f"Materiales de nivel alto ({hi['n']} objetos): oferta {f(hi['qty'])}, precio {f(hi['price'])}.")
    if lo and hi:
        if lo["qty"] < -0.1 and hi["qty"] > 0.1:
            out["phase"] = "subiendo"
            out["text"].append("Lectura: cada vez se farmea menos en zonas bajas y más en las altas. La gente está llegando "
                               "arriba y los materiales de nivel bajo empiezan a escasear.")
        elif lo["qty"] >= 0:
            out["phase"] = "pronto"
            out["text"].append("Lectura: todavía sobra material de nivel bajo. Es pronto para acaparar en general; "
                               "mira objeto por objeto.")
        else:
            out["phase"] = "mixto"
            out["text"].append("Lectura: señales mezcladas; decide objeto por objeto.")
    else:
        out["text"].append("Aún no hay histórico suficiente (10 días) para leer la fase del servidor en los precios.")
    for ev in data.catalog.get("events", []):
        ts = time.mktime(time.strptime(ev["date"], "%Y-%m-%d"))
        days = math.ceil((ts - data.now) / 86400)
        if 0 <= days <= 60:
            out["events"].append({"name": ev["name"], "date": _date(ts), "days": days, "note": ev.get("note")})
            out["text"].append(f"{ev['name']}: {_date(ts)} (faltan {days} días).")
    return out


def _uses(data):
    uses = defaultdict(list)
    for r in data.recipes:
        for it, _ in r["reagents"]:
            if r["name"] not in uses[it]:
                uses[it].append(r["name"])
    for prof in data.catalog.get("professions", {}).values():
        for cr in prof.get("recipes", {}).values():
            for it, _ in cr["r"]:
                uses[it].append(cr["n"])
    return uses


# ----------------------------------------------------------------------
# Detectores: cada uno devuelve candidatos {type, item, target, horizon, risk, why, ...}
# ----------------------------------------------------------------------
def _cand(data, kind, item, target, horizon, risk, title, why, **extra):
    return {"type": kind, "item": item, "target": target, "horizon": max(1, int(horizon)), "risk": risk,
            "title": title, "why": list(why), **extra}


def detect_pantry(data, route_buys, horizon_h):
    out = []
    for item, qty in route_buys.items():
        st, med = data.stats(item), _med14(data, item)
        if not med or not st["mv"] or st["mv"] > med * 0.92:
            continue
        daily = qty / (horizon_h / 24)
        out.append(_cand(
            data, "despensa", item, med, 5, "bajo",
            f"Llena la despensa de {data.name(item)}",
            [f"Hoy está a {_money(st['mv'])}, un {(1 - st['mv'] / med) * 100:.0f} % por debajo de su mediana de 14 días "
             f"({_money(med)}).",
             f"Tus recetas de la ruta gastan unas {daily:.0f} al día: comprar para 5 días más te ahorra la diferencia.",
             "Riesgo bajo: lo vas a usar igualmente; si el precio no vuelve a subir, solo has adelantado la compra."],
            want=math.ceil(daily * 5), saving=True))
    return out


def detect_rebound(data, skip):
    out = []
    for item in data.prices:
        if item in skip:
            continue
        st, med = data.stats(item), _med14(data, item)
        if not med or not st["mv"] or (st["vol"] or 0) < 3 or st["days"] < 7:
            continue
        if st["mv"] > med * 0.85:
            continue
        out.append(_cand(
            data, "rebote", item, med * 0.95, 4, "medio",
            f"{data.name(item)} está hundido: compra y espera el rebote",
            [f"Hoy está a {_money(st['mv'])}; su mediana de 14 días es {_money(med)} "
             f"({(1 - st['mv'] / med) * 100:.0f} % menos).",
             f"Se siguen vendiendo unas {st['vol']:.0f} al día, así que la demanda no ha desaparecido: "
             "lo normal es que alguien haya volcado mucho stock y el precio vuelva.",
             "El riesgo es que la bajada sea permanente (más gente farmeándolo)."]))
    return out


def detect_weekly(data):
    out = []
    today_wd = time.localtime(data.now).tm_wday
    for item in data.prices:
        past = _past(data, item)
        st = data.stats(item)
        if len(past) < 13 or not st["mv"] or (st["vol"] or 0) < 3:
            continue
        by = defaultdict(list)
        for h in past:
            wd = time.strptime(h["day"], "%Y-%m-%d").tm_wday
            by[wd].append(h["mv"])
        med = statistics.median(h["mv"] for h in past)
        means = {wd: statistics.mean(v) for wd, v in by.items() if len(v) >= 2}
        if len(means) < 5:
            continue
        best = max(means, key=means.get)
        cheap = min(means, key=means.get)
        if not all(v > med for v in by[best]) or not all(v < med for v in by[cheap]):
            continue
        # con dos semanas el azar engaña: pide que las dos muestras se parezcan, que la diferencia sea
        # grande y que el día de al lado también sea caro (un ciclo, no un pico suelto)
        near = [w for w in ((best - 1) % 7, (best + 1) % 7) if w in means and all(v > med for v in by[w])]
        if max(by[best]) > min(by[best]) * 1.08 or means[best] < means[cheap] * 1.15 or not near:
            continue
        if st["mv"] > med * 0.97 or means[best] * (1 - AH_CUT) < st["mv"] * 1.08:
            continue
        days = (best - today_wd) % 7 or 7
        out.append(_cand(
            data, "semanal", item, means[best] * 0.97, days, "medio",
            f"{data.name(item)}: compra hoy, vende el {WEEKDAYS[best]}",
            [f"En las dos últimas semanas el {WEEKDAYS[best]} se ha vendido a {_money(means[best])} de media y el "
             f"{WEEKDAYS[cheap]} a {_money(means[cheap])}.",
             f"Hoy ({WEEKDAYS[today_wd]}) está a {_money(st['mv'])}.",
             "Suele pasar con consumibles: la gente los compra justo antes de entrar a mazmorras o bandas.",
             "Solo hay dos semanas de datos: el patrón puede ser casualidad."]))
    return out


def detect_drought(data, uses):
    out = []
    for item in data.prices:
        h = [x for x in data.history.get(item, []) if x["qty"] is not None and x["mv"]]
        st = data.stats(item)
        if len(h) < 10 or item not in uses or not st["mv"]:
            continue
        q0, q1 = statistics.mean(x["qty"] for x in h[:4]), statistics.mean(x["qty"] for x in h[-4:])
        slope = _slope([x["mv"] for x in h])
        qslope = _slope([x["qty"] for x in h])
        if q0 <= 0 or q1 / q0 > 0.7 or not slope or slope < 0.003 or (qslope or 0) > -0.02:
            continue
        target = st["mv"] * (1 + slope * 10)
        out.append(_cand(
            data, "sequia", item, target, 10, "medio",
            f"Cada día hay menos {data.name(item)} en subasta",
            [f"Lo publicado ha pasado de unas {q0:.0f} a unas {q1:.0f} unidades en dos semanas "
             f"({(1 - q1 / q0) * 100:.0f} % menos) y el precio sube un {slope * 100:.1f} % al día.",
             f"Se usa en: {', '.join(uses[item][:3])}.",
             f"Objetivo: si sigue al mismo ritmo 10 días más, {_money(target)}.",
             "El riesgo es que alguien vuelva a farmearlo en cuanto el precio compense."]))
    return out


def detect_event(data):
    out = []
    for ev in data.catalog.get("events", []):
        ts = time.mktime(time.strptime(ev["date"], "%Y-%m-%d"))
        days = math.ceil((ts - data.now) / 86400)
        if not 3 <= days <= 35:
            continue
        up = ev.get("uplift", 1.25)
        for item in ev.get("items", []):
            st, med = data.stats(item), _med14(data, item)
            if not med or not st["mv"] or (st["vol"] or 0) < 2:
                continue
            base = max(med, st["mv"]) if st["mv"] <= med * 1.08 else None
            if base is None:
                continue
            out.append(_cand(
                data, "evento", item, base * up, max(3, days - 1), "medio",
                f"{data.name(item)} antes de: {ev['name'].lower()}",
                [f"{ev['name']} el {_date(ts)} (faltan {days} días).",
                 f"Hoy está a {_money(st['mv'])}, sin subida previa respecto a su mediana ({_money(med)}).",
                 f"Escenario: sube un {(up - 1) * 100:.0f} % la semana del evento, hasta {_money(base * up)}. "
                 "Ese porcentaje es una suposición del catálogo, no un dato.",
                 "Vende desde uno o dos días antes hasta el primer reinicio: después la oferta se pone al día."],
                event=ev["name"]))
    return out


def detect_progression(data, uses, look):
    """Material de nivel bajo. La señal de compra sale del propio objeto: que se publique cada vez menos
    y que el precio haya dejado de bajar. Si aún baja o aún sobra, queda en vigilancia."""
    out = []
    srv = data.catalog.get("server", {})
    thr = srv.get("low_level_max_ilvl", 40)
    horizon = srv.get("progression_horizon_days", 21)
    theses = data.catalog.get("progression", {})
    for item in data.prices:
        it = data.items.get(item) or {}
        ilvl = it.get("ilvl")
        if not ilvl or ilvl > thr:
            continue
        st, med, hv = data.stats(item), _med14(data, item), _halves(data, item)
        th = theses.get(str(item))
        if not med or not hv or not st["mv"] or (st["vol"] or 0) < 5 or st["mv"] > med * 1.03:
            continue
        if not th and item not in uses:
            continue
        scen = (th or {}).get("scenario", 1.4)
        s5 = hv["s5"] or 0
        drying, bottomed = hv["qty"] <= -0.12, s5 >= -0.005
        why = [f"Material de nivel bajo (nivel de objeto {ilvl}) a {_money(st['mv'])}; su mediana de 14 días es {_money(med)}.",
               f"Oferta: de unas {hv['q0']:.0f} publicadas a unas {hv['q1']:.0f} en dos semanas "
               f"({'+' if hv['qty'] >= 0 else '−'}{abs(hv['qty']) * 100:.0f} %). "
               + ("Cada vez lo farmea menos gente." if drying else "Todavía no escasea."),
               f"Precio de los últimos 5 días: {'+' if s5 >= 0 else '−'}{abs(s5) * 100:.1f} % al día. "
               + ("Ha dejado de bajar." if bottomed else "Sigue bajando.")]
        if th:
            why.append(f"Se seguirá pidiendo: {th['note']}.")
        elif item in uses:
            why.append(f"Se seguirá pidiendo para: {', '.join(uses[item][:3])}.")
        why.append(f"Escenario: ×{scen:g} sobre su mediana, {_money(med * scen)}, en unas {horizon // 7} semanas. "
                   "Es una suposición del catálogo: puede tardar más o no pasar.")
        floor = it.get("vendor_sell") or 0
        if floor >= st["mv"] * 0.3:
            why.append(f"Suelo: el vendedor paga {_money(floor)}, así que lo máximo que pierdes es "
                       f"{(1 - floor / st['mv']) * 100:.0f} %.")
        wait = None
        if not bottomed:
            wait = "Aún no: el precio sigue bajando. Entra cuando lleve varios días sin marcar un mínimo nuevo."
        elif not drying:
            wait = "Aún no: no se publica menos que antes. Entra cuando lo publicado empiece a caer."
        out.append(_cand(data, "progresion", item, med * scen, horizon, "alto",
                         (f"Acapara {data.name(item)}: se está secando y ha tocado suelo" if not wait
                          else f"Vigila {data.name(item)}"), why, wait=wait))
    return out


# ----------------------------------------------------------------------
# Tamaño de la posición, almacén y ruta
# ----------------------------------------------------------------------
def _craft_lines(data, node, qty, buys, crafts, mats):
    """Reparte lo necesario para conseguir `qty` de un nodo: compras (buys), fabricación (crafts)
    y la lista de materiales comprados (mats) por si hay que enviarlos a otro personaje."""
    item = node["item"]
    if node["method"] == "subasta":
        buys.append(f"BUY {item} {math.ceil(qty)} {int(math.ceil((node.get('max') or node['unit']) * 1.02))}"
                    f"   # {data.name(item)}")
        mats.append(f"{math.ceil(qty)}× {data.name(item)}")
    elif node["method"] == "vendedor":
        crafts.append(f"NOTE Compra al vendedor: {math.ceil(qty)}× {data.name(item)}")
    else:
        n = math.ceil(qty / node["yield"])
        for ch in node["children"]:
            _craft_lines(data, ch, ch["per_craft"] * n, buys, crafts, mats)
        crafts.append(f"CRAFT {node['recipe']} {n}   # {node['recipe_name']}")


def build_ideas(data, budget, buyer, storages, route_buys, skip_items, horizon_h, held=(), banker=None):
    uses = _uses(data)
    look = outlook(data, uses)
    cands = (detect_pantry(data, route_buys, horizon_h) + detect_event(data) + detect_weekly(data)
             + detect_drought(data, uses) + detect_progression(data, uses, look)
             + detect_rebound(data, skip_items))

    # una idea por objeto: la mejor, y las demás señales como apoyo
    by_item = defaultdict(list)
    for c in cands:
        if c["item"] in held:
            continue                                   # ya hay una apuesta abierta con este objeto
        st = data.stats(c["item"])
        c["gain"] = c["target"] * (1 - AH_CUT) / st["mv"] - 1 if not c.get("saving") else c["target"] / st["mv"] - 1
        by_item[c["item"]].append(c)
    merged = []
    for item, lst in by_item.items():
        lst.sort(key=lambda c: (c["type"] != "despensa", -c["gain"] * RISK_FACTOR[c["risk"]]))
        best = lst[0]
        for other in lst[1:]:
            best["why"].append(f"Además ({LABEL[other['type']].lower()}): {other['why'][0]}")
        best["signals"] = [LABEL[c["type"]] for c in lst]
        merged.append(best)

    total_free = sum(f for _, f in storages)
    free = {label: f for label, f in storages}
    ideas = []
    for c in merged:
        item, st = c["item"], data.stats(c["item"])
        stack = data.stack(item)
        depth = st["depth"][0] if st["depth"] else 0
        exit_cap = (st["vol"] or 0) * min(c["horizon"], 7) * 0.25
        want = c.get("want") or 10 ** 9
        qty = int(min(depth, exit_cap if not c.get("saving") else depth, want))
        mode, tree, char = "comprar", None, buyer
        entry_info = data.buy_unit(item, max(1, qty)) if qty >= 1 else None
        src = data.best_source(item, max(1, qty)) if qty >= 1 else None
        if src and src["method"] == "fabricar" and entry_info and src["unit"] < entry_info[0] * 0.95 \
                and not c.get("saving"):
            mode, tree, char = "fabricar", src, src["char"]
            entry, max_buy = src["unit"], None
        elif entry_info:
            entry, max_buy = entry_info[0], int(math.ceil(entry_info[1] * 1.02))
        else:
            continue
        net_target = c["target"] if c.get("saving") else c["target"] * (1 - AH_CUT)
        profit_u = net_target - entry
        c.update({"id": f"{c['type']}-{item}", "label": LABEL[c["type"]], "name": data.name(item), "mode": mode,
                  "char": char, "entry": entry, "max_buy": max_buy, "stack": stack, "cap_qty": qty,
                  "profit_u": profit_u, "gain": profit_u / entry, "breakeven": entry / (1 - AH_CUT),
                  "stop": entry * STOP, "floor": (data.items.get(item) or {}).get("vendor_sell") or 0,
                  "sell_date": _date(data.now + c["horizon"] * 86400), "tree": tree,
                  "vol": st["vol"], "mv": st["mv"], "med14": _med14(data, item)})
        if mode == "fabricar":
            c["why"].append(f"Sabes fabricarlo: te sale a {_money(entry)} en vez de {_money(entry_info[0])} comprándolo "
                            f"({tree['recipe_name']}, {char.split('-')[0]}).")
        if profit_u / entry < 0.05:
            continue
        c["score"] = profit_u * max(1, qty) * RISK_FACTOR[c["risk"]]
        ideas.append(c)

    # como mucho N por tipo, las mejores
    ideas.sort(key=lambda c: -c["score"])
    seen, keep = defaultdict(int), []
    for c in ideas:
        if seen[c["type"]] < MAX_PER_TYPE:
            seen[c["type"]] += 1
            keep.append(c)
    ideas = keep

    # reparto de presupuesto y huecos: primero lo que más rinde por oro, ponderado por riesgo
    ideas.sort(key=lambda c: (c["risk"] != "bajo", -(c["gain"] * RISK_FACTOR[c["risk"]] / math.sqrt(c["horizon"]))))
    left = budget
    routes = defaultdict(list)       # primera parte de cada personaje
    tails = defaultdict(list)        # lo que hace el banquero cuando los artesanos le devuelven lo fabricado
    short = lambda ck: ck.split("-")[0]
    for c in ideas:
        cap_budget = min(left, budget * 0.35)
        cap_slots = int(sum(free.values()) and min(sum(free.values()), max(1, total_free * 0.4)))
        by_budget = int(cap_budget // c["entry"])
        qty = min(c["cap_qty"], by_budget, cap_slots * c["stack"])
        if qty >= c["stack"]:
            qty -= qty % c["stack"]
        c["included"] = qty >= 1 and c["profit_u"] * qty >= 5000 and not c.get("wait")
        if not c["included"]:
            c["qty"], c["invest"], c["profit"], c["slots"], c["store"] = 0, 0, 0, 0, None
            c["skip"] = c.get("wait") or ("No queda presupuesto de especulación." if by_budget <= qty and by_budget < c["cap_qty"] else
                         "No queda sitio donde guardarlo." if cap_slots < 1 else
                         "Con el presupuesto que queda y lo que hay a ese precio no llega a 50s de beneficio.")
            continue
        slots = math.ceil(qty / c["stack"])
        store = max(free, key=free.get)
        if free[store] < slots:
            slots = free[store]
            qty = slots * c["stack"]
        free[store] -= slots
        c.update({"qty": qty, "invest": qty * c["entry"], "profit": qty * c["profit_u"], "slots": slots,
                  "store": store, "loss_stop": qty * (c["entry"] - c["stop"] * (1 - AH_CUT)),
                  "per_slot": qty * c["profit_u"] / slots})
        left -= c["invest"]
        c["exit"] = [
            (f"Úsalo en tus recetas; no hace falta venderlo." if c.get("saving") else
             f"Vende a partir del {c['sell_date']} o en cuanto pase de {_money(c['target'])}."),
        ]
        if not c.get("saving"):
            c["exit"] += [f"No pierdes si lo vendes por encima de {_money(c['breakeven'])}.",
                          f"Si cae por debajo de {_money(c['stop'])}, véndelo y acepta la pérdida "
                          f"(unos {_money(c['loss_stop'])})."]
        lines = routes[c["char"]]
        if c["mode"] == "fabricar":
            buys, crafts, mats = [], [], []
            _craft_lines(data, {**c["tree"], "item": c["item"]}, qty, buys, crafts, mats)
            if banker and banker != c["char"]:
                # el banquero compra y envía; el artesano fabrica y devuelve; el banquero lo guarda
                routes[banker] += buys + ([f"NOTE Envía por correo a {short(c['char'])}: " + ", ".join(mats)] if mats else [])
                lines += ([f"NOTE Recoge del correo (de {short(banker)}): " + ", ".join(mats)] if mats else []) + crafts
                lines.append(f"NOTE Envía por correo a {short(banker)}: {qty}× {c['name']}")
                lines = tails[banker]
                lines.append(f"NOTE Recoge del correo (de {short(c['char'])}): {qty}× {c['name']}")
            else:
                lines += buys + crafts
        else:
            lines.append(f"BUY {c['item']} {qty} {c['max_buy']}   # {c['label'].lower()}: {c['name']}")
        lines.append(f"NOTE Guarda {qty}× {c['name']} en {store}"
                     + ("" if c.get("saving") else f" hasta el {c['sell_date']}; vende a {_money(c['target'])} o más"))
        if not c.get("saving"):
            due = time.strftime("%Y-%m-%d", time.localtime(data.now + c["horizon"] * 86400))
            lines.append(f"HOLD {c['item']} {qty} {int(c['target'])} {int(c['stop'])} {due} {int(round(c['entry']))}"
                         f"   # apuesta: {c['name']}")
    for c in ideas:
        c.pop("tree", None)

    gen = time.strftime("%d/%m %H:%M", time.localtime(data.now))
    for ck, tail in tails.items():
        who = sorted({short(k) for k in routes if k != ck})
        routes[ck] += ["NOTE Ahora entra con " + ", ".join(who) + " y haz su parte; después vuelve aquí"] + tail
    order = sorted(routes, key=lambda k: k != banker)
    route_out = {ck: {"short": short(ck),
                      "text": f"# Ideas Oroboros — {short(ck)} — {gen}\n" + "\n".join(routes[ck]) + "\n"}
                 for ck in order}
    route_all = f"# Ideas Oroboros — todos los personajes — {gen}\n" + "".join(
        f"CHAR {short(ck)}\n" + "\n".join(routes[ck]) + "\n" for ck in order)
    inc = [c for c in ideas if c["included"]]
    return {"budget": budget, "invest": sum(c["invest"] for c in inc),
            "profit": sum(c["profit"] for c in inc), "loss_stop": sum(c.get("loss_stop", 0) for c in inc),
            "outlook": look, "ideas": ideas, "routes": route_out, "route_all": route_all,
            "storage": [{"label": l, "free_before": f, "free_after": free[l]} for l, f in storages]}


def brief(data, plan):
    """Resumen del mercado en Markdown para pegárselo a un LLM y pedirle más ideas."""
    uses = _uses(data)
    L = ["# Mercado de WoW Forever — resumen para proponer ideas de especulación", "",
         "Contexto:"] + [f"- {t}" for t in plan["ideas"]["outlook"]["text"]]
    L += [f"- Presupuesto para especular: {_money(plan['ideas']['budget'])}. "
          f"Huecos libres: " + ", ".join(f"{s['label']} {s['free_after']}" for s in plan["ideas"]["storage"]) + ".",
          "- La subasta se queda el 5 % de cada venta. Precios en oro.", "",
          "| Objeto | Nivel | Precio | Mediana 14 d | vs mediana | Tendencia | Ventas/día | Publicadas | Vendedor paga | Se usa en |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for item in sorted(data.prices, key=data.name):
        st, med = data.stats(item), _med14(data, item)
        if not st["mv"]:
            continue
        it = data.items.get(item) or {}
        L.append(f"| {data.name(item)} | {it.get('ilvl') or ''} | {st['mv'] / 1e4:.2f} | "
                 f"{(med or 0) / 1e4:.2f} | {((st['mv'] / med - 1) * 100 if med else 0):+.0f} % | "
                 f"{((st['trend'] or 0) * 100):+.0f} % | {st['vol'] or 0:.0f} | {st['qty']} | "
                 f"{(it.get('vendor_sell') or 0) / 1e4:.2f} | {', '.join(uses.get(item, [])[:3])} |")
    L += ["", "Ideas que ya han encontrado las reglas automáticas:"]
    L += [f"- [{c['label']}, riesgo {c['risk']}] {c['title']}" for c in plan["ideas"]["ideas"]]
    L += ["", "Tarea: propón 5 ideas más que estas reglas no vean (relaciones entre objetos, sustitutos, cuellos de "
          "botella de profesiones, efectos de los eventos). Para cada una: tesis en una frase, qué comprar y a qué "
          "precio máximo, cuándo vender y a cuánto, qué dato la desmentiría y riesgo (bajo/medio/alto). "
          "No inventes precios: usa solo los de la tabla y di qué datos te faltan."]
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------------
# Cartera: apuestas abiertas (HOLD) con lo que pagaste de verdad
# ----------------------------------------------------------------------
def portfolio(data):
    out = []
    held_now = defaultdict(int)
    for items in data.inventory.values():
        for it, n in items.items():
            held_now[it] += n
    for p in data.positions:
        item = p["item_id"]
        t0 = (p["t"] or 0) - 86400
        buys = [e for e in data.ledger if e["op"] == "BUY" and e["item_id"] == item and (e["t"] or 0) >= t0]
        sells = [e for e in data.ledger if e["op"] == "SELL" and e["item_id"] == item and (e["t"] or 0) >= t0]
        bq = sum(e["qty"] for e in buys)
        entry = sum(e["qty"] * e["unit"] for e in buys) / bq if bq else p["entry"]
        entry_src = "lo que pagaste (libro de compras)" if bq else "precio previsto en el plan"
        sold = sum(e["qty"] for e in sells)
        realized = sum(e["total"] - e["qty"] * entry for e in sells) if entry else 0
        plan_qty = p["qty"] or bq
        qty = max(0, min(plan_qty - sold, held_now.get(item, 0)))
        st = data.stats(item)
        mv = st["mv"]
        net = mv * (1 - AH_CUT) if mv else None
        days_left = None
        if p["due"]:
            days_left = math.ceil((time.mktime(time.strptime(p["due"], "%Y-%m-%d")) - data.now) / 86400)
        pnl = (net - entry) * qty if net and entry else None
        if qty <= 0:
            status, advice = "cerrada", "Ya no lo tienes: apuesta cerrada."
        elif mv and p["target"] and mv >= p["target"]:
            status, advice = "objetivo", f"Objetivo alcanzado ({_money(mv)} ≥ {_money(p['target'])}): vende ya."
        elif mv and p["stop"] and mv <= p["stop"]:
            status, advice = "stop", (f"Ha caído a {_money(mv)}, por debajo de tu stop ({_money(p['stop'])}): "
                                      "vende y acepta la pérdida.")
        elif days_left is not None and days_left <= 0:
            status = "vencida"
            advice = ("Ha pasado la fecha sin llegar al objetivo: "
                      + ("vende, que estás en beneficio." if pnl and pnl > 0 else "decide si sales o le das más tiempo."))
        else:
            status = "espera"
            advice = (f"Espera: faltan {days_left} días y le queda un "
                      f"{(p['target'] / mv - 1) * 100:.0f} % hasta el objetivo." if mv and p["target"] and days_left
                      else "Espera.")
        out.append({"item": item, "name": data.name(item), "qty": qty, "plan_qty": plan_qty, "sold": sold,
                    "entry": entry, "entry_src": entry_src, "cost": entry * qty if entry else None, "mv": mv,
                    "net": net, "value": net * qty if net else None, "pnl": pnl,
                    "pnl_pct": (net / entry - 1) if net and entry else None, "realized": realized,
                    "target": p["target"], "stop": p["stop"], "due": p["due"], "days_left": days_left,
                    "breakeven": entry / (1 - AH_CUT) if entry else None, "status": status, "advice": advice,
                    "sell": status in ("objetivo", "stop") or (status == "vencida" and (pnl or 0) > 0)})
    order = {"stop": 0, "objetivo": 1, "vencida": 2, "espera": 3, "cerrada": 4}
    out.sort(key=lambda x: order[x["status"]])
    recent = sorted(data.ledger, key=lambda e: -(e["t"] or 0))[:40]
    ledger = [{"t": time.strftime("%d/%m %H:%M", time.localtime(e["t"])), "char": (e["char"] or "").split("-")[0],
               "op": e["op"], "item": e["item_id"], "name": data.name(e["item_id"]), "qty": e["qty"],
               "unit": e["unit"], "total": e["total"]} for e in recent]
    open_ = [x for x in out if x["status"] != "cerrada"]
    return {"positions": out, "ledger": ledger,
            "cost": sum(x["cost"] or 0 for x in open_), "value": sum(x["value"] or 0 for x in open_),
            "pnl": sum(x["pnl"] or 0 for x in open_), "realized": sum(x["realized"] or 0 for x in out),
            "alerts": sum(1 for x in open_ if x["status"] in ("stop", "objetivo", "vencida"))}


def hold_signals(data, skip=()):
    """Objetos sobre los que hoy hay señal de compra para guardar: no tiene sentido vender el stock que ya tienes."""
    uses = _uses(data)
    look = outlook(data, uses)
    out = {}
    for c in (detect_event(data) + detect_drought(data, uses) + detect_progression(data, uses, look)
              + detect_rebound(data, skip)):
        st = data.stats(c["item"])
        if c.get("wait") or not st["mv"] or c["target"] * (1 - AH_CUT) / st["mv"] - 1 < 0.05:
            continue
        out.setdefault(c["item"], LABEL[c["type"]].lower())
    return out
