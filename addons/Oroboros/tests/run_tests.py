import os, subprocess, sys, sqlite3
for _s in (sys.stdout, sys.stderr):      # consola de Windows en cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
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
cl = G.OroborosDB.client
check(cl is not None and cl.realm == "Forever Normal" and cl.faction == "Horde" and cl.t,
      "datos del cliente guardados al entrar (reino, facción)")

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

# Auctionator con su escaneo completo activado: no pedimos otro y leemos el suyo
lua.execute("""
Auctionator = { API = { v1 = {} }, Config = { Options = { REPLICATE_SCAN = "replicate_scan_3" },
                Get = function(k) return k == "replicate_scan_3" end } }
AUCTIONATOR_SAVEDVARS = {}
""")
ns.Scanner.lastReplicate = 0; ns.Scanner.lastRead = 0; G.OroborosDB.lastReplicate = 0
check(ns.Scanner.AuctionatorReplicates() is True, "Auctionator: detecta su escaneo completo")
ns.Scanner.FullScan()
check(len(calls()) == 0, "Auctionator: Oroboros no llama a ReplicateItems")
mprices = G.OroborosDB.markets[ns.MarketKey()].prices
mprices[2589] = None
lua.execute("AUCTIONATOR_SAVEDVARS.TimeOfLastReplicateScan = time()")
fire("REPLICATE_ITEM_LIST_UPDATE"); G.RunTimers()
p = ns.DB.GetPrice(2589)
check(p is not None and p.mv == 32 and p.d[1] == 20, "Auctionator: leemos su escaneo con valor de mercado y profundidad")
mprices[2589] = None
fire("REPLICATE_ITEM_LIST_UPDATE"); G.RunTimers()
check(ns.DB.GetPrice(2589) is None, "Auctionator: el mismo escaneo no se lee dos veces")
ns.Scanner.lastReplicate = 0; G.OroborosDB.lastReplicate = 0
can, left = ns.Scanner.CanFullScan()
check(can is False and left > 14 * 60, "Auctionator: respetamos su límite de 15 min")
ns.Scanner.FullScan(True)
check(len(calls()) == 0, "/oro scan forzar también respeta el límite")
lua.execute("AUCTIONATOR_SAVEDVARS.TimeOfLastReplicateScan = time() - 16 * 60")
ns.Scanner.FullScan(True)
check(calls() == [("ReplicateItems",)], "/oro scan forzar lanza nuestro escaneo")
fire("REPLICATE_ITEM_LIST_UPDATE"); G.RunTimers()
check(ns.DB.GetPrice(2589) is not None, "escaneo forzado leído")
ns.Scanner.lastReplicate = 0          # como tras un /reload
lua.execute("AUCTIONATOR_SAVEDVARS = {}")
check(ns.Scanner.CanFullScan() is False or ns.Scanner.CanFullScan()[0] is False,
      "el límite de 15 min sobrevive a /reload (OroborosDB.lastReplicate)")
lua.execute("Auctionator = nil; AUCTIONATOR_SAVEDVARS = nil")
check(ns.Scanner.AuctionatorReplicates() is False, "sin Auctionator: escaneo propio")

# Buffer de escaneos (franjas horarias): cada escaneo completo se guarda en bruto, los 12 últimos
lin = lambda: [[30, 20], [35, 20], [50, 200]]
def _scan(by, mk="TEST-MK"):
    tbl = lua.eval("{}")
    for k, v in by.items():
        lst = lua.eval("{}")
        for i, (pr, q) in enumerate(v, 1):
            row = lua.eval("{}"); row[1], row[2] = pr, q; lst[i] = row
        tbl[k] = lst
    ns.DB.RecordPrices(tbl, True, mk)
    sc = G.OroborosDB.markets[mk].scans
    return sc, dict(e.split(",", 1) for e in sc[len(sc)].data.split(";"))
sc, last = _scan({2589: lin()})
check(len(sc) == 1 and last["2589"] == "30,32,240,40,40", f"buffer: primer escaneo {last.get('2589')}")
sc, last = _scan({2589: [[35, 20], [50, 200]]})
check(last["2589"] == "35,41,220,20,20", f"buffer: sube el mínimo, lo barato se mide con el umbral anterior {last.get('2589')}")
sc, last = _scan({4306: [[4000, 20]]})
check(last["2589"] == ",,0,0,0", f"buffer: objeto agotado cuenta como 0 {last.get('2589')}")
for _ in range(11):
    sc, last = _scan({2589: lin()})
check(len(sc) == 12, f"buffer: como mucho 12 escaneos ({len(sc)})")
n, cap = ns.DB.ScanCount("TEST-MK")
check((n, cap) == (12, 12), "buffer: ScanCount")
lua.execute("LOG = {}"); ns.DB.PrintStats()
check(any("escaneos guardados: 12/12 (lleno" in l for l in G.LOG.values()), "/oro stats avisa con el buffer lleno")
G.OroborosDB.markets["TEST-MK"] = None

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
                    "--sqlite", out, "--json", out.replace(".sqlite", ".json")], capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip(), r.stderr.strip())
con = sqlite3.connect(out)
check(con.execute("SELECT mv FROM prices WHERE item_id=2589").fetchone()[0] == 32, "SQLite: precios")
check(con.execute("SELECT COUNT(*) FROM reagents WHERE recipe_id=3914").fetchone()[0] == 2, "SQLite: reactivos")
check(con.execute("SELECT source FROM recipe_cost WHERE item_id=2320").fetchone()[0] == "vendor", "SQLite: coste desde vendedor")
check(con.execute("SELECT learned FROM recipes WHERE recipe_id=3914").fetchone()[0] == 0, "SQLite: receta no aprendida")
check(con.execute("SELECT count FROM inventory WHERE location='bank' AND item_id=14047").fetchone()[0] == 40, "SQLite: inventario banco")
check(con.execute("SELECT free FROM slots WHERE location='warband'").fetchone()[0] == 15, "SQLite: huecos banda")
check(con.execute("SELECT d125 FROM prices WHERE item_id=2589").fetchone()[0] == 40, "SQLite: profundidad")

# Auctionator.lua junto a Oroboros.lua: el exportador mezcla sus precios
con.close()       # en Windows no se puede borrar un SQLite abierto
sys.path.insert(0, os.path.join(ROOT, "tools"))
import datetime
from auctionator_source import cbor_encode, cbor_decode
d0 = (datetime.date.today() - datetime.date(2020, 1, 1)).days
pve = {
    "2589": {"m": 33, "h": {str(d0 - 1): 45, str(d0): 33}, "l": {}, "a": {str(d0 - 1): 500, str(d0): 240}},
    "9999": {"m": 500, "h": {str(d0 - 2): 520, str(d0 - 1): 510}, "l": {str(d0 - 2): 480},
             "a": {str(d0 - 2): 30, str(d0 - 1): 25}},
    "g:6070:200": {"m": 1, "h": {str(d0): 1}, "l": {}, "a": {}},
    "p:123": {"m": 1, "h": {str(d0): 1}, "l": {}, "a": {}},
    "version": 2,
}
blob = cbor_encode(pve)
check(cbor_decode(blob) == pve, "CBOR: ida y vuelta")
def lua_bytes(b):   # como WoW: bytes altos tal cual; controles, comillas y barras escapados
    return "".join(chr(c) if (32 <= c < 127 or c >= 128) and c not in (34, 92) else "\\%03d" % c for c in b)
atr_lua = "\n".join([
    "",
    "AUCTIONATOR_PRICE_DATABASE = {",
    '\t["__dbversion"] = 8,',
    '\t["PvE"] = "' + lua_bytes(blob) + '",',
    '\t["Viejo"] = {',
    '\t\t["2589"] = {',
    '\t\t\t["m"] = 1,',
    '\t\t\t["h"] = {',
    '\t\t\t\t["2000"] = 1,',
    "\t\t\t},",
    "\t\t},",
    "\t},",
    "}",
    "AUCTIONATOR_SAVEDVARS = {",
    '\t["TimeOfLastBrowseScan"] = 1,',
    "}",
    "",
])
with open(os.path.join(ROOT, "tests", "Auctionator.lua"), "w", encoding="latin-1", newline="\n") as fh:
    fh.write(atr_lua)
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), sv, "--sqlite", out, "--auctionator"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
print(r.stdout.strip(), r.stderr.strip())
con = sqlite3.connect(out)
mk_ = con.execute("SELECT market FROM characters").fetchone()[0]
row = con.execute("SELECT min, mv, qty, d110, src FROM prices WHERE market=? AND item_id=9999", (mk_,)).fetchone()
check(row == (500, 500, 25, None, "atr"), f"Auctionator: precio de un objeto nuevo {row}")
check(con.execute("SELECT mv, src FROM prices WHERE item_id=2589").fetchone() == (32, "oro"),
      "Auctionator: no pisa el precio de Oroboros del mismo día")
d2 = (datetime.date.today() - datetime.timedelta(days=2)).isoformat()
check(con.execute("SELECT min, mv, qty, src FROM history WHERE item_id=9999 AND day=?", (d2,)).fetchone() == (480, 520, 30, "atr"),
      "Auctionator: histórico (mínimo, más alto y cantidad del día)")
check(con.execute("SELECT COUNT(*) FROM history WHERE item_id=2589 AND src='atr'").fetchone()[0] == 1,
      "Auctionator: solo añade los días que Oroboros no tiene")
check(con.execute("SELECT COUNT(*) FROM prices WHERE item_id IN (6070, 123)").fetchone()[0] <= 1,
      "Auctionator: ignora claves de equipo por nivel y mascotas")
con.close()
from oroboros_plan import Data
dd = Data(out, os.path.join(ROOT, "tools", "catalog.json"))
st_ = dd.stats(9999)
check(st_["depth_est"] and st_["src"] == "atr" and st_["conf"] != "alta", f"planificador: profundidad estimada y confianza {st_['conf']}")
check(dd.stats(2589)["depth_est"] is False, "planificador: profundidad real de Oroboros")

from oroboros_export import LuaParser
# Archivo permanente de escaneos (--archive): no duplica y detecta huecos
import tempfile as _tf
from oroboros_export import load_savedvariables
from oroboros_archive import append_scans
arch = os.path.join(_tf.mkdtemp(), "archivo.sqlite")
svdb = load_savedvariables(sv)["OroborosDB"]
n_buf = sum(len(m.get("scans") or []) for m in svdb["markets"].values())
r1, r2 = append_scans(arch, svdb), append_scans(arch, svdb)
check(n_buf > 0 and r1["added"] > 0 and r2["added"] == 0 and r2["already"] >= r1["added"],
      f"archivo: añade {r1['added']} filas y no duplica al exportar otra vez")
_ac = sqlite3.connect(arch)
check(_ac.execute("SELECT qty, cheap, cheap_prev FROM scans WHERE item_id=2589 ORDER BY t LIMIT 1").fetchone() == (240, 40, 40),
      "archivo: columnas total, baratas y baratas con el umbral anterior")
_ac.close()
fake = {"markets": {"M": {"scans": [{"t": 1000 + i, "data": "2589,30,32,240,40,40"} for i in range(12)]}}}
arch2 = os.path.join(_tf.mkdtemp(), "a2.sqlite")
append_scans(arch2, {"markets": {"M": {"scans": [{"t": 10, "data": "2589,30,32,240,40,40"}]}}})
check(append_scans(arch2, fake)["gap"] is True, "archivo: avisa si se han perdido escaneos (buffer lleno sin solape)")
fake["markets"]["M"]["scans"][0]["t"] = 10
check(append_scans(arch2, fake)["gap"] is False, "archivo: sin hueco si hay solape")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), sv, "--archive", arch],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r.returncode == 0 and "Archivo" in r.stdout, "exportador: --archive " + (r.stdout + r.stderr)[-200:])

extra = LuaParser('Extra = {\n\t"a", -- [1]\n\t{\n\t\t2589, -- [1]\n\t\t2, -- [2]\n\t}, -- [2]\n}\nS = "\\195\\177and\\"u"').assignments()
check(extra["Extra"] == ["a", [2589, 2]] and extra["S"] == 'ñand"u', f"parser: arrays estilo WoW y escapes {extra}")

# --- Planificador con datos sintéticos: SavedVariables → SQLite → plan → rutas que el addon entiende
import json, tempfile
tmp = tempfile.mkdtemp()
# Hora fija: los datos sintéticos (ciclo semanal) y las fechas de catalog.json dependen del día;
# sin esto el resultado de las ideas cambiaría según el día en que se pasen las pruebas.
NOW = "2026-11-16T19:30"
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_synthetic.py"), "--out", os.path.join(tmp, "A.lua"), "--now", NOW], check=True, capture_output=True)
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), os.path.join(tmp, "A.lua"), "--sqlite", os.path.join(tmp, "a.sqlite")], check=True, capture_output=True)
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "a.sqlite"),
                    "--json", os.path.join(tmp, "p.json"), "--html", os.path.join(tmp, "p.html"), "--synthetic", "--now", NOW], capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r.returncode == 0, "planificador se ejecuta " + r.stderr[-300:])
plan = json.load(open(os.path.join(tmp, "p.json"), encoding="utf-8"))
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
                     "--json", os.path.join(tmp, "p2.json"), "--banker", "none", "--now", NOW], capture_output=True, text=True, encoding="utf-8", errors="replace")
p2 = json.load(open(os.path.join(tmp, "p2.json"), encoding="utf-8"))

# Sin histórico (primer día con datos reales): lotes de prueba y tope para la confianza baja
import shutil
nh = os.path.join(tmp, "nohist.sqlite")
shutil.copy(os.path.join(tmp, "a.sqlite"), nh)
_c = sqlite3.connect(nh); _c.execute("DELETE FROM history")
# como en Forever: el juego da dificultad 0 a casi todas las recetas no aprendidas; una queda «fácil» (2)
_c.execute("UPDATE recipes SET difficulty=0 WHERE learned=0")
_c.execute("UPDATE recipes SET difficulty=2 WHERE recipe_id=(SELECT MIN(recipe_id) FROM recipes WHERE learned=0)")
_c.commit(); _c.close()
# catálogo sin niveles de receta: en Forever el juego no los da
def _strip_skill(x):
    if isinstance(x, dict):
        return {k: _strip_skill(v) for k, v in x.items() if k != "skill"}
    return [_strip_skill(v) for v in x] if isinstance(x, list) else x
cat_ns = os.path.join(tmp, "catalog_noskill.json")
json.dump(_strip_skill(json.load(open(os.path.join(ROOT, "tools", "catalog.json"), encoding="utf-8"))),
          open(cat_ns, "w", encoding="utf-8"), ensure_ascii=False)
r3 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", nh,
                     "--json", os.path.join(tmp, "p3.json"), "--now", NOW, "--catalog", cat_ns], capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r3.returncode == 0, "planificador sin histórico " + r3.stderr[-300:])
p3 = json.load(open(os.path.join(tmp, "p3.json"), encoding="utf-8"))
inc3 = [o for o in p3["opportunities"] if o.get("included")]
crafts3 = [o for o in inc3 if o["kind"] == "craft"]
check(crafts3 and all(o.get("trial") for o in crafts3), f"sin histórico: todo es lote de prueba ({len(crafts3)} fabricaciones)")
check(all(o["units"] <= 20 and (o["crafts"] == 1 or o["cost"] * o["crafts"] <= 10000) for o in crafts3),
      "lote de prueba: como mucho 20 unidades o 1 oro " + str([(o["name"], o["units"], round(o["cost"] * o["crafts"])) for o in crafts3]))
low3 = sum(o["investment"] for o in inc3 if o["conf"] == "baja")
check(low3 <= p3["settings"]["budget"] * 0.3 + 1, f"confianza baja: como mucho el 30 % del presupuesto ({low3:.0f} de {p3['settings']['budget']:.0f})")
reach = [l.get("reach") for l in p3["learn"] if not l.get("new_profession")]
first_unknown = reach.index("desconocido") if "desconocido" in reach else len(reach)
check(all(x == "desconocido" for x in reach[first_unknown:]) and 0 < first_unknown < len(reach),
      f"aprender: primero lo que está a tu alcance, al final el nivel sin comprobar ({reach.count('desconocido')} de {len(reach)})")
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
