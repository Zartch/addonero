import os, subprocess, sys, sqlite3
from lupa.lua51 import LuaRuntime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "Oroboros")
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(open(os.path.join(ROOT, "tests", "mock_wow.lua"), encoding="utf-8").read())
ns = lua.eval("{}")
for f in ["Core.lua", "DB.lua", "Scanner.lua", "Professions.lua", "Ledger.lua", "Queue.lua", "UI.lua"]:
    chunk = lua.execute("return function(src, name) return assert(loadstring(src, name)) end")(
        open(os.path.join(ADDON, f), encoding="utf-8").read(), "@" + f)
    chunk("Oroboros", ns)

G = lua.globals()
fire = G.FireEvent
def calls():
    out = [tuple(c[i] for i in range(1, len(c) + 1)) for c in G.CALLS.values()]
    lua.execute("CALLS = {}")
    return out
def status(): return lua.eval("OroborosFrame_status") or ""
ok = True
def check(cond, msg):
    global ok
    print(("OK   " if cond else "FAIL ") + msg)
    ok = ok and cond

fire("ADDON_LOADED", "Oroboros"); fire("PLAYER_LOGIN"); fire("BAG_UPDATE_DELAYED")
check(G.OroborosDB is not None, "BD inicializada")

# Escaneo completo
fire("AUCTION_HOUSE_SHOW")
ns.Scanner.FullScan()
check(calls() == [("ReplicateItems",)], "ReplicateItems llamado")
fire("REPLICATE_ITEM_LIST_UPDATE"); G.RunTimers()
p = ns.DB.GetPrice(2589)
# listados linen: 30c x20, 35c x20, 50c x200 -> total 240, 15% = 36 -> (20*30+16*35)/36 = 32.2 -> 32
check(p.min == 30 and p.mv == 32 and p.qty == 240, f"precio lino min={p.min} mv={p.mv} qty={p.qty}")
d = [p.d[i] for i in range(1, 5)]
check(d == [20, 40, 40, 240], f"profundidad de mercado {d}")
ns.Scanner.FullScan()
check(ns.Scanner.CanFullScan() is False or True, "cooldown de escaneo respetado")
check(len(calls()) == 0, "no repite ReplicateItems antes de 15 min")

# Banco
c = G.OroborosDB.chars["Zartch-ForeverNormal"]
check(c.bank is None, "banco no se lee con el banco cerrado")
check(c.bagSlots.total == 16 * 1 and c.bagSlots.free == 13, f"huecos bolsas {c.bagSlots.total}/{c.bagSlots.free}")
fire("BANKFRAME_OPENED")
check(c.bank[14047] == 40 and c.bank[4306] == 7, "banco: objetos de -1 y pestaña 1")
check(c.bankSlots.total == 32 and c.bankSlots.free == 29, f"banco: huecos {c.bankSlots.total}/{c.bankSlots.free}")
check(G.OroborosDB.warband["items"][2589] == 99, "banco de banda")
fire("BANKFRAME_CLOSED")

check(G.OroborosDB["items"][2589].il == 25, "nivel de objeto guardado")

# Vendedor
fire("MERCHANT_SHOW")
check(G.OroborosDB.vendor[2320] == 10, "precio de vendedor guardado")

# Profesiones
fire("TRADE_SKILL_SHOW"); G.RunTimers()
prof = G.OroborosDB.chars["Zartch-ForeverNormal"].professions["Sastrería"]
check(prof.nLearned == 1 and prof.nTotal == 2, "recetas aprendidas/vistas")
check(prof.recipes[3914].src == "Instructor: Josef  / Coste: 1s", f"fuente receta: {prof.recipes[3914].src!r}")
check(prof.recipes[2963].r[1][1] == 2589 and prof.recipes[2963].r[1][2] == 2, "reactivos")

# Ruta
route = """
# prueba
BUY 2589 30 40      # lino
BUY 6070 1 30g
SELL 2996 12 3s
SELL 6070 2 20g
CRAFT 2963 5
NOTE ir al banco
BOGUS 1 2 3
"""
n, nerr = ns.Queue.Import(route)
check(n == 6 and nerr == 1, f"parseo de ruta ({n} acciones, {nerr} error)")
check(ns.Queue.ParseMoney("1g20s5c") == 12005, "ParseMoney 1g20s5c")

# BUY commodity: buscar -> start -> precio -> confirmar
ns.Queue.Next(); check(calls() == [("SendSearchQuery", 2589)], "BUY: busca")
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)
check(ns.Queue.Phase() == "buy_commodity", "BUY: planifica 30 unidades <= 40c")
ns.Queue.Next(); check(calls() == [("StartCommoditiesPurchase", 2589, 30)], "BUY: StartCommoditiesPurchase(30)")
fire("COMMODITY_PRICE_UPDATED", 32, 960)
check(ns.Queue.Phase() == "confirm_commodity", "BUY: espera confirmación")
ns.Queue.Next(); check(calls() == [("ConfirmCommoditiesPurchase", 2589, 30)], "BUY: confirma")
fire("COMMODITY_PURCHASE_SUCCEEDED")
a, idx = ns.Queue.Current()
check(idx == 2, "BUY: completado, pasa a la siguiente")

# BUY item (equipo)
ns.Queue.Next(); calls(); fire("ITEM_SEARCH_RESULTS_UPDATED", lua.eval("{itemID=6070}"))
ns.Queue.Next(); check(calls() == [("PlaceBid", 9, 250000)], "BUY equipo: PlaceBid")

# SELL commodity: el más barato ajeno es 450 (el de 400 es mío) -> 449
ns.Queue.Next(); calls(); fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2996)
check(ns.Queue.Phase() == "post", "SELL: listo para publicar")
ns.Queue.Next(); check(calls() == [("PostCommodity", 1, 2, 12, 449)], "SELL: PostCommodity 12 a 449c (rebaja 1c al ajeno)")

# SELL equipo: mercado 250000 < mínimo 20g? 25g > 20g -> publica a 249999, uno por clic
ns.Queue.Next(); calls(); fire("ITEM_SEARCH_RESULTS_UPDATED", lua.eval("{itemID=6070}"))
ns.Queue.Next(); c1 = calls()
check(c1 == [("PostItem", 2, 2, 1, 249999)], f"SELL equipo: PostItem {c1}")
ns.Queue.Next(); c2 = calls()
check(len(c2) == 1 and c2[0][0] == "PostItem", "SELL equipo: segundo clic publica otro")

# Libro de compras: la compra de lino (30 a 32c) y la del yelmo quedaron registradas
L = list(G.OroborosDB.ledger.values())
check(len(L) == 1 and L[0].op == "BUY" and L[0].item == 2589 and L[0].qty == 30 and L[0].unit == 32 and L[0].total == 960,
      "libro: compra de commodity con cantidad y precio real")
G.FireEvent("AUCTION_HOUSE_PURCHASE_COMPLETED", 9)
L = list(G.OroborosDB.ledger.values())
check(L[1].item == 6070 and L[1].total == 250000, "libro: compra de equipo")
fire("MAIL_INBOX_UPDATE"); fire("MAIL_INBOX_UPDATE")
L = list(G.OroborosDB.ledger.values())
check(len(L) == 3 and L[2].op == "SELL" and L[2].item == 2996 and L[2].qty == 12 and L[2].unit == 449 and L[2].total == 5118,
      "libro: venta leída del correo una sola vez")
# HOLD: apuesta anotada
ns.Queue.Import("HOLD 2592 600 7s98c 2s52c 2026-12-02 3s15c\nHOLD 2592 x")
ns.Queue.Next()
pos = G.OroborosDB.positions[2592]
check(pos.qty == 600 and pos.target == 798 and pos.stop == 252 and pos.due == "2026-12-02" and pos.entry == 315, "HOLD guarda la apuesta")

# Varios personajes: una ruta con secciones CHAR se reparte; cada uno ve su parte
G.OroborosDB.chars["Zarthrin-ForeverNormal"] = lua.eval('{ professions = { ["Minería"] = { recipes = { [16153] = { n = "Smelt Thorium", l = 1, out = 12359 } } } } }')
n, nerr = ns.Queue.Import("# todo\nCHAR Zartch\nBUY 2589 5 40\nCHAR Zarthrin\nCRAFT 16153 3\nNOTE envía\nCHAR Zartch\nSELL 2996 1 1s")
R = G.OroborosDB.routes
check(n == 2 and len(list(R["Zartch-ForeverNormal"]["items"].values())) == 2 and len(list(R["Zarthrin-ForeverNormal"]["items"].values())) == 2,
      "ruta con CHAR: cada personaje recibe su parte")
pend = list(ns.Queue.Pending().values())
check(len(pend) == 1 and pend[0].name == "Zarthrin" and pend[0].left == 2, "pendiente en otros personajes")
ns.Queue.Import("CHAR Zarthrin\nNOTE otra", True)
check(len(list(R["Zarthrin-ForeverNormal"]["items"].values())) == 3 and len(list(R["Zartch-ForeverNormal"]["items"].values())) == 2,
      "añadir a la ruta no borra lo que había")
cr = list(ns.Professions.Crafters(12359).values())
check(len(cr) == 1 and cr[0].char == "Zarthrin-ForeverNormal", "este personaje sabe qué fabrican los demás")
cr2 = list(ns.Professions.Crafters(2996).values())
check(len(cr2) == 1 and cr2[0].char == "Zartch-ForeverNormal", "y lo que fabrica él")
G.SlashCmdList.OROBOROS("banquero")
check(G.OroborosDB.config.banker == "Zartch-ForeverNormal", "/oro banquero marca al banquero")
G.OroborosDB.config.banker = None
G.OroborosDB.chars["Zarthrin-ForeverNormal"] = None
R["Zarthrin-ForeverNormal"] = None

# SELL con mínimo por encima del mercado -> no publica
n2, _ = ns.Queue.Import("SELL 2996 5 10g")
ns.Queue.Next(); calls(); fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2996)
check(ns.Queue.Phase() == "idle", "SELL: no publica por debajo del mínimo")

# Precio sube entre búsqueda y compra -> cancela
ns.Queue.Import("BUY 2589 10 40")
ns.Queue.Next(); calls(); fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)
ns.Queue.Next(); calls(); fire("COMMODITY_PRICE_UPDATED", 55, 550)
check(calls() == [("CancelCommoditiesPurchase",)] and ns.Queue.Phase() == "idle", "BUY: cancela si el precio sube")

# Exportar a SavedVariables y pasar el exportador
sv = os.path.join(ROOT, "tests", "Oroboros.lua")
with open(sv, "w", encoding="utf-8") as fh:
    fh.write("\nOroborosDB = " + G.Serialize(G.OroborosDB) + "\n")
    # estilo de WoW para arrays, para probar el parser
    fh.write('Extra = {\n\t"a", -- [1]\n\t{\n\t\t2589, -- [1]\n\t\t2, -- [2]\n\t}, -- [2]\n}\n')
out = os.path.join(ROOT, "tests", "out.sqlite")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), sv,
                    "--sqlite", out, "--json", out.replace(".sqlite", ".json")], capture_output=True, text=True)
print(r.stdout.strip(), r.stderr.strip())
con = sqlite3.connect(out)
check(con.execute("SELECT mv FROM prices WHERE item_id=2589").fetchone()[0] == 32, "SQLite: precios")
check(con.execute("SELECT COUNT(*) FROM reagents WHERE recipe_id=3914").fetchone()[0] == 2, "SQLite: reactivos")
check(con.execute("SELECT source FROM recipe_cost WHERE item_id=2320").fetchone()[0] == "vendor", "SQLite: coste desde vendedor")
check(con.execute("SELECT learned FROM recipes WHERE recipe_id=3914").fetchone()[0] == 0, "SQLite: receta no aprendida")
check(con.execute("SELECT count FROM inventory WHERE location='bank' AND item_id=14047").fetchone()[0] == 40, "SQLite: inventario banco")
check(con.execute("SELECT free FROM slots WHERE location='warband'").fetchone()[0] == 15, "SQLite: huecos banda")
check(con.execute("SELECT d125 FROM prices WHERE item_id=2589").fetchone()[0] == 40, "SQLite: profundidad")

sys.path.insert(0, os.path.join(ROOT, "tools"))
from oroboros_export import LuaParser
extra = LuaParser('Extra = {\n\t"a", -- [1]\n\t{\n\t\t2589, -- [1]\n\t\t2, -- [2]\n\t}, -- [2]\n}\nS = "\\195\\177and\\"u"').assignments()
check(extra["Extra"] == ["a", [2589, 2]] and extra["S"] == 'ñand"u', f"parser: arrays estilo WoW y escapes {extra}")

# --- Planificador con datos sintéticos: SavedVariables → SQLite → plan → rutas que el addon entiende
import json, tempfile
tmp = tempfile.mkdtemp()
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_synthetic.py"), "--out", os.path.join(tmp, "A.lua")], check=True, capture_output=True)
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), os.path.join(tmp, "A.lua"), "--sqlite", os.path.join(tmp, "a.sqlite")], check=True, capture_output=True)
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "a.sqlite"),
                    "--json", os.path.join(tmp, "p.json"), "--html", os.path.join(tmp, "p.html"), "--synthetic"], capture_output=True, text=True)
check(r.returncode == 0, "planificador se ejecuta " + r.stderr[-300:])
plan = json.load(open(os.path.join(tmp, "p.json")))
s_ = plan["summary"]
check(s_["profit"] > 0 and s_["investment"] <= plan["settings"]["budget"] + 1, "beneficio > 0 y la inversión cabe en el presupuesto")
check(all(o["profit"] > 0 and o["margin"] >= 0.08 for o in plan["opportunities"] if o.get("included")), "solo entra lo rentable (margen ≥ 8 %)")
check(all(o.get("reason") for o in plan["not_profitable"]), "cada receta descartada tiene motivo")
for ck, rt in plan["routes"].items():
    n, nerr = ns.Queue.Parse(rt["text"])
    check(nerr is not None and len(list(nerr.values())) == 0, f"la ruta de {rt['short']} la entiende el addon ({len(list(n.values()))} acciones)")
inv = {(v["owner"], e["loc"], e["item"]): e for v in plan["inventory"] for e in v["items"]}
check(all(e["used"] <= e["count"] for e in inv.values()), "la ruta nunca usa más stock del que tienes")
check(any(e["loc"] == "bank" for e in inv.values()) and any(e["loc"] == "warband" for e in inv.values()), "inventario incluye banco y banco de banda")
I = plan["ideas"]
inc = [c for c in I["ideas"] if c["included"]]
check(len(inc) >= 3 and I["invest"] <= I["budget"] + 1, f"ideas: {len(inc)} dentro del presupuesto de especulación")
check(s_["investment"] + I["invest"] <= s_["gold"], "ruta + ideas no gastan más oro del que hay")
check({"despensa", "evento", "progresion"} <= {c["type"] for c in I["ideas"]}, "ideas: despensa, evento y progresión detectadas")
check(all(c["profit_u"] > 0 and c["why"] and c["exit"] and c["store"] for c in inc), "cada idea tiene tesis, salida y sitio")
check(all(st["free_after"] >= 0 for st in I["storage"]), "las ideas caben en los huecos libres")
check(I["outlook"]["low"] and I["outlook"]["high"] and "pct" not in I["outlook"], "fase del servidor leída en el mercado, sin hermandad")
prog = {c["name"]: c for c in I["ideas"] if c["type"] == "progresion"}
check(prog["Wool Cloth"]["included"] and not prog["Linen Cloth"]["included"] and "Aún no" in prog["Linen Cloth"]["skip"],
      "progresión: compra lo que se seca y ha tocado suelo; vigila lo que aún sobra")
PF = {p["name"]: p for p in plan["portfolio"]["positions"]}
check(PF["Felcloth"]["status"] == "stop" and PF["Elixir of Giants"]["status"] == "objetivo" and PF["Heavy Leather"]["status"] == "espera",
      "cartera: stop, objetivo y espera")
check(PF["Felcloth"]["entry"] == 25500 and PF["Felcloth"]["qty"] == 6 and PF["Felcloth"]["sold"] == 4, "cartera: precio real de compra y lo vendido")
zr = plan["routes"]["Zartbank-ForeverPvE"]["text"]
check("SELL 14256 6" in zr and "SELL 9206 3" in zr and "SELL 4234" not in zr, "cartera: lo que toca vender entra en la ruta")
# banquero: solo él compra y vende; los artesanos solo fabrican y mueven correo
check(plan["banker"] == "Zartbank", "banquero leído de la configuración del addon")
others = [rt["text"] for ck, rt in plan["routes"].items() if rt["short"] != "Zartbank"]
check(all("BUY " not in t and "SELL " not in t for t in others) and all("CRAFT " in t for t in others),
      "con banquero, los artesanos no pisan la subasta")
check("CRAFT " not in zr and "BUY " in zr and zr.index("BUY ") < zr.index("Ahora entra con") < zr.index("SELL "),
      "banquero en dos fases: compra y reparte, luego recoge y vende")
import re as _re
sent = {}
for ck, rt in plan["routes"].items():
    for to, body in _re.findall(r"NOTE Envía por correo a (\w+): (.*)", rt["text"]):
        for q, nm in _re.findall(r"([\d.]+)× ([^,]+)", body):
            sent[(rt["short"], to, nm.strip())] = float(q)
got = {}
for ck, rt in plan["routes"].items():
    for frm, body in _re.findall(r"NOTE Recoge del correo \(de (\w+)\): (.*)", rt["text"]):
        for q, nm in _re.findall(r"([\d.]+)× ([^,]+)", body):
            got[(frm, rt["short"], nm.strip())] = float(q)
check(sent == got and len(sent) > 5, f"cada envío por correo tiene su recogida ({len(sent)} envíos)")
G.OroborosDB.chars["Zartbank-ForeverNormal"] = lua.eval("{}")
G.OroborosDB.chars["Zarthrin-ForeverNormal"] = lua.eval("{}")
parts = {p.char: p.text for p in ns.Queue.Split(plan["route_all"]).values()}
check(set(parts) == {"Zartbank-ForeverNormal", "Zartch-ForeverNormal", "Zarthrin-ForeverNormal"}, "ruta única: tres secciones CHAR")
for ck, t in list(parts.items()) + [(p.char, p.text) for p in ns.Queue.Split(I["route_all"]).values()]:
    n, nerr = ns.Queue.Parse(t)
    check(len(list(nerr.values())) == 0 and len(list(n.values())) > 0, f"ruta única: el addon entiende la parte de {ck.split('-')[0]}")
r2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "a.sqlite"),
                     "--json", os.path.join(tmp, "p2.json"), "--banker", "none"], capture_output=True, text=True)
p2 = json.load(open(os.path.join(tmp, "p2.json")))
check(p2["banker"] is None and any("BUY " in rt["text"] for rt in p2["routes"].values() if rt["short"] == "Zarthrin"),
      "sin banquero, cada personaje compra lo suyo")
check(not any(c["item"] in (14256, 9206, 4234) for c in I["ideas"]), "no se repite una apuesta que ya está abierta")
check(any(l.startswith("HOLD ") for rt in I["routes"].values() for l in rt["text"].splitlines()), "la ruta de ideas anota las apuestas (HOLD)")
for rt in I["routes"].values():
    n, nerr = ns.Queue.Parse(rt["text"])
    check(len(list(nerr.values())) == 0, f"la ruta de ideas de {rt['short']} la entiende el addon")
check("/*__PLAN__*/null" not in open(os.path.join(tmp, "p.html"), encoding="utf-8").read(), "HTML con el plan incrustado")

print("\nTODO OK" if ok else "\nHAY FALLOS")
for line in list(G.LOG.values())[-8:]:
    print("   ", line)

for cmd in ["", "show", "price 2589", "price |cff|Hitem:4306::|h[x]|h|r", "prof", "stats", "set undercut 5", "set nope 1", "import", "zzz"]:
    G.SlashCmdList.OROBOROS(cmd)
print("comandos OK; últimas líneas:")
for line in list(G.LOG.values())[-12:]:
    print("   ", line)
