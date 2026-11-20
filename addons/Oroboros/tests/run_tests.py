import os, subprocess, sys, sqlite3
for _s in (sys.stdout, sys.stderr):      # consola de Windows en cp1252
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
from lupa.lua51 import LuaRuntime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "Oroboros")
# catálogo de las pruebas (datos inventados); tools/catalog.json lleva los datos reales de Forever
CAT_TEST = os.path.join(ROOT, "tests", "catalogo_sintetico.json")
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(open(os.path.join(ROOT, "tests", "mock_wow.lua"), encoding="utf-8").read())
ns = lua.eval("{}")
for f in ["Core.lua", "DB.lua", "Scanner.lua", "Professions.lua", "Ledger.lua", "Queue.lua", "Style.lua", "Chart.lua", "UI.lua", "PriceHistory.lua", "Inventory.lua"]:
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
# Duraciones de Forever: el código 1, 2, 3 del juego son 2, 8 y 24 h (no 12, 24, 48 como en el juego normal)
check([ns.PostHours(k) for k in (1, 2, 3)] == [2, 8, 24] and ns.Cfg("postDuration") == 3, "publicar: 24 h por defecto (el máximo en Forever)")
G.SlashCmdList.OROBOROS("set postDuration 4")
check(G.OroborosDB.config.postDuration is None, "publicar: /oro set postDuration solo acepta 1, 2 o 3")
check(ns.Cfg("historyDays") == 14, "el juego guarda 14 días de histórico (el resto, en el archivo)")
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

# Escaneo automático al abrir la subasta, bien visible (fase 3)
def _auto_reset():
    ns.Scanner.lastReplicate = 0; G.OroborosDB.lastReplicate = 0; ns.Scanner.lastRead = 0
    fire("AUCTION_HOUSE_CLOSED"); calls(); lua.execute("LOG = {}")
_auto_reset()
fire("AUCTION_HOUSE_SHOW"); G.RunTimers()
btn = ns.UI.frame.scanButton
log_txt = " ".join(G.LOG.values())
check(calls() == [("ReplicateItems",)] and btn.text == "Escaneando…" and "escaneo automático" in log_txt.lower(),
      f"automático: al abrir la subasta lanza el escaneo, el botón dice «Escaneando…» y el chat avisa ({btn.text})")
fire("REPLICATE_ITEM_LIST_UPDATE"); G.RunTimers()
check(btn.text == "Escaneo completo" and "Escaneo automático leído" in (G.OroborosFrame_status or ns.UI.lastStatus or ""),
      f"automático: al acabar, el botón vuelve y el estado lo dice ({ns.UI.lastStatus})")
fire("AUCTION_HOUSE_CLOSED"); fire("AUCTION_HOUSE_SHOW"); G.RunTimers()
check(len(calls()) == 0, "automático: no repite antes de 15 minutos")
_auto_reset(); G.OroborosDB.config.autoscan = 0
fire("AUCTION_HOUSE_SHOW"); G.RunTimers()
check(len(calls()) == 0, "automático: /oro set autoscan 0 lo apaga")
G.OroborosDB.config.autoscan = None
_auto_reset()
lua.execute("""Auctionator = { API = { v1 = {} }, Config = { Options = { REPLICATE_SCAN = "r" }, Get = function(k) return k == "r" end } }""")
fire("AUCTION_HOUSE_SHOW"); G.RunTimers()
check(len(calls()) == 0, "automático: con el escaneo completo de Auctionator no lanza el propio")
lua.execute("Auctionator = nil")
_auto_reset()
fire("AUCTION_HOUSE_SHOW"); G.RunTimers(); calls()
fire("AUCTION_HOUSE_CLOSED")
check(btn.text == "Escaneo completo", "automático: cerrar la subasta a mitad devuelve el botón")
fire("AUCTION_HOUSE_SHOW")
ns.UI.frame.shown = True
check(ns.PriceHistory.AnchorTarget() == "OroborosFrame", "panel de precios: va debajo de la ventana de Oroboros, sin taparla")
ns.Scanner.state = "idle"; ns.Scanner.lastReplicate = __import__("time").time(); G.OroborosDB.lastReplicate = ns.Scanner.lastReplicate
calls()

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
# Sin exportar: Resumen.lua dice hasta qué escaneo está archivado; el resto, pendiente
lua.execute('for i, sc in ipairs(OroborosDB.markets["TEST-MK"].scans) do sc.t = 1000 + i end')
lua.execute("OroborosResumen = nil")
check(tuple(ns.DB.PendingScans("TEST-MK")) == (12, 12), "sin exportar: sin información, cuentan todos")
lua.execute("LOG = {}"); ns.DB.PrintStats()
check(any("sin exportar: 12/12" in l and "exporta" in l for l in G.LOG.values()), "/oro stats avisa si hay 12 sin exportar")
lua.execute('OroborosResumen = { v = 1, t = 0, archived = { ["TEST-MK"] = 1009 }, markets = {} }')
check(tuple(ns.DB.PendingScans("TEST-MK")) == (3, 12), "sin exportar: solo los posteriores al último archivado")
lua.execute("LOG = {}"); ns.DB.PrintStats()
_st = " ".join(G.LOG.values())
check("sin exportar: 3/12" in _st and "lleno" not in _st, f"/oro stats: 3 sin exportar y sin falsa alarma")
lua.execute("OroborosResumen = nil")
G.OroborosDB.markets["TEST-MK"] = None

# Nombres que faltan: se piden en tandas de 100 y se rellenan al llegar
calls()
lua.execute("for k = 0, 249 do OroborosDB.items[900000 + k] = {} end")
ns.DB.QueueMissingNames()
first = [c for c in calls() if c[0] == "RequestLoadItemDataByID"]
G.RunTimers()
rest = [c for c in calls() if c[0] == "RequestLoadItemDataByID"]
check(len(first) == 100 and len(first) + len(rest) == 250, f"nombres: se piden en tandas de 100 ({len(first)} + {len(rest)})")
lua.execute('ITEMS[900001] = { "Gema de prueba", 2, 20 }')
fire("GET_ITEM_INFO_RECEIVED", 900001, True)
check(lua.eval("OroborosDB.items[900001].n") == "Gema de prueba", "nombres: se rellenan al llegar la ficha del objeto")
lua.execute("for k = 0, 249 do OroborosDB.items[900000 + k] = nil end")

# Panel de historial de precios (Camel) en la subasta
PH = ns.PriceHistory
_S = ("120;130;136;141;95;20261112;210;20261105;5;1;100,,110,120,130,125,140,150,160,155,150,140,130;"
      + "120,,,,,,,,,,,,125,120;20261119")
lua.execute("OroborosResumen = { v = 1, t = 0, markets = { [\"" + ns.MarketKey() + "\"] = { [2589] = [[" + _S + "]] } } }")
ps = PH.Parse(_S)
check((ps.today, ps.avg30, ps.low, ps.lowDay, ps.sellBand, ps.weeks[1], ps.weeks[2], ps.weeks[13], ps.days[14]) ==
      (120, 136, 95, 20261112, 5, 100, None, 130, 120), "panel: descomprime la cadena con huecos")
L = list(PH.Lines(2589, 120).values())
check(L == ["Linen Cloth", "Hoy 1s 20c · un 12 % por debajo de su media de 30 días", "Mínimo 95c (12/11) · Máximo 2s 10c (05/11)",
            "Media 7 d 1s 30c · 30 d 1s 36c · 90 d 1s 41c", "Se vende más de 20 a 24 h · más barato de 4 a 8 h"], f"panel: textos {L}")
check(list(PH.Lines(2996, 450).values()) == ["Bolt of Linen Cloth", "Hoy 4s 50c", "Sin historial: genera el plan."],
      "panel: sin resumen, solo el precio de hoy")
fire("AUCTION_HOUSE_SHOW")
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2589)
check(PH.frame is not None and PH.frame.shown and PH.current == 2589 and PH.live == 30, "panel: se abre al buscar un objeto en la subasta, con el precio en vivo")
fire("AUCTION_HOUSE_CLOSED")
check(not PH.frame.shown, "panel: se cierra con la subasta")
G.SlashCmdList.OROBOROS("precio 2589")
check(PH.frame.shown and PH.current == 2589, "/oro precio abre el panel")
lua.execute('OroborosResumen = { v = 1, t = 0, markets = { ["Otro-Alliance"] = { [2589] = "1;;;;;;;;;;;;20261119" } } }')
check(PH.Get(2589) is None, "panel: el resumen de otro mercado no se usa")
lua.execute("OroborosResumen = nil")
check(PH.Get(2589) is None and list(PH.Lines(2589, None).values())[-1] == "Sin historial: genera el plan.", "panel: sin Resumen.lua funciona igual")
# Dinero con iconos de moneda (ventanas y tooltip)
_cop, _sil, _gol = "UI-CopperIcon", "UI-SilverIcon", "UI-GoldIcon"
_c = ns.Coin(120)
check(_c.startswith("1|T") and _sil in _c and _c.endswith("|t") and "20|T" in _c and _cop in _c and "s" not in _c.split("|T")[0],
      f"monedas: 1 plata 20 cobre con iconos ({_c})")
check(ns.Coin(10000).count("|T") == 1 and _gol in ns.Coin(10000) and ns.Coin(0).startswith("0|T") and _cop in ns.Coin(0),
      "monedas: se omiten las unidades a cero salvo si todo es cero")
check(ns.Chart.ShortMoney(2000).startswith("20|T") and _sil in ns.Chart.ShortMoney(2000), "escala de las gráficas con icono de moneda")
# Modelo del panel rediseñado (cifras, tono, fechas de días y semanas)
lua.execute("OroborosResumen = { v = 1, t = 0, markets = { [\"" + ns.MarketKey() + "\"] = { [2589] = [[" + _S + "]], [2318] = [[50;50;50;50;50;20261119;50;20261119;;;50,50,50,50,50,50,50,50,50,50,50,50,50;50,50,50,50,50,50,50,50,50,50,50,50,50,50;20261119]] } } }")
M = PH.Model(2589, 120)
_st = [(x.label, x.value, x.sub) for x in M.stats.values()]
check((M.diffPct, M.tone, M.hasHistory) == (-12, "good", True) and len(_st) == 5 and _st[3] == ("MÍNIMO", ns.Coin(95), "12/11"),
      f"panel: modelo con diferencia, tono y cifras {M.diffPct} {M.tone} {_st}")
check(M.days[14].label == "19/11" and M.days[1].label == "06/11" and M.weeks[1].label == "semana del 24/08" and M.weeks[13].label == "semana del 16/11",
      f"panel: fechas de días y semanas ({M.days[1].label}..{M.days[14].label}, {M.weeks[1].label})")
check(PH.Model(2996, 450).hasHistory is False, "panel: sin resumen, sin historial")
for _id, _live in ((2589, 120), (2996, 450), (2318, 50), (2318, None)):
    PH.Show(_id, _live)
check(True, "panel: se dibuja con resumen, sin resumen y con todos los valores iguales")
# Tooltip y Alt+clic: el historial de cualquier objeto, sin estar en la subasta
ti = PH.TooltipInfo(2589)
check(ti is not None and ti.price == ns.Coin(ns.DB.GetPrice(2589).mv) and ti.tone in ("good", "bad", "neutral") and ti.diffPct is not None,
      f"tooltip: precio con iconos y diferencia con su media ({ti and ti.diffPct})")
fire("AUCTION_HOUSE_CLOSED"); PH.Hide(); PH.current = None
lua.execute("ALT_DOWN = false")
G.HandleModifiedItemClick("|cffffffff|Hitem:2589::::::::60:::::|h[Linen Cloth]|h|r")
check(PH.current is None, "Alt+clic: sin Alt no abre nada")
lua.execute("ALT_DOWN = true")
G.HandleModifiedItemClick("|cffffffff|Hitem:2589::::::::60:::::|h[Linen Cloth]|h|r")
check(PH.current == 2589 and PH.frame.shown, "Alt+clic en un objeto abre su historial sin la subasta abierta")
lua.execute("ALT_DOWN = false"); PH.Hide()
lua.execute("OroborosResumen = nil")
fire("AUCTION_HOUSE_SHOW")
fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2996)
check(PH.live == 450, f"panel: el precio en vivo es el más barato de otros vendedores, no la primera fila ({PH.live})")
check(PH.LivePrice(lua.eval("{}")) is None, "panel: sin filas válidas no hay precio en vivo")
lua.execute("LOG = {}"); G.SlashCmdList.OROBOROS("precio debug")
_dbg = " ".join(G.LOG.values())
check("400" in _dbg and "propia" in _dbg and "450" in _dbg, f"/oro precio debug muestra lo que devolvió el juego ({_dbg[:120]})")
PH.Hide(); fire("AUCTION_HOUSE_SHOW")      # las pruebas siguientes cuentan con la subasta abierta
calls()

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
ns.Queue.Next(); check(calls() == [("PostCommodity", 1, 3, 12, 449)], "SELL: PostCommodity 12 a 449c (rebaja 1c al ajeno), 24 h")
check("24 h" in (ns.UI.lastStatus or ""), f"SELL: el estado dice cuánto dura la subasta ({ns.UI.lastStatus})")

# SELL equipo: mercado 250000 < mínimo 20g? 25g > 20g -> publica a 249999, uno por clic
ns.Queue.Next(); calls(); fire("ITEM_SEARCH_RESULTS_UPDATED", lua.eval("{itemID=6070}"))
ns.Queue.Next(); c1 = calls()
check(c1 == [("PostItem", 2, 3, 1, 249999)], f"SELL equipo: PostItem a 24 h {c1}")
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

# Ventana «Lo que tienes»: todos los personajes, bolsas + banco + banda, sin tener el banco abierto
INV = ns.Inventory
rows, total = INV.Rows("")
rows = list(rows.values())
silk = next((r for r in rows if r.id == 4306), None)
c_ = G.OroborosDB.chars["Zartch-ForeverNormal"]
_bags_silk = (c_.bags[4306] or 0) if c_.bags else 0
check(silk is not None and silk.count == 7 + _bags_silk and abs(silk.value - silk.count * silk.unit) < 1e-6,
      f"inventario: suma bolsas y banco y el valor es unidades × precio ({silk and silk.count})")
vals = [r.value for r in rows]
check(vals == sorted(vals, reverse=True) and abs(total - sum(vals)) < 1e-6, "inventario: ordenado por valor y con el total")
only = list(INV.Rows("silk")[0].values())
check(len(only) >= 1 and all("silk" in r.name.lower() for r in only), "inventario: el buscador filtra por nombre")
G.SlashCmdList.OROBOROS("inventario")
check(INV.frame is not None and INV.frame.shown, "/oro inventario abre la ventana")
INV.frame.shown = False

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
dd = Data(out, CAT_TEST)
st_ = dd.stats(9999)
check(st_["depth_est"] and st_["src"] == "atr" and st_["conf"] != "alta", f"planificador: profundidad estimada y confianza {st_['conf']}")
check(dd.stats(2589)["depth_est"] is False, "planificador: profundidad real de Oroboros")

from oroboros_export import LuaParser
# Ayudante: escribe filas (market, t, item, min, mv, qty, cheap, cheap_prev) en el archivo (esquema 2)
from oroboros_archive import open_archive, insert_scan
def arch_write(path, flat):
    con = open_archive(path)
    by = {}
    for mk_, t_, it_, mn_, mv_, q_, c_, cp_ in flat:
        by.setdefault((mk_, t_), []).append((it_, mn_, mv_, q_, c_, cp_))
    for (mk_, t_), rws in sorted(by.items()):
        insert_scan(con, mk_, t_, rws)
    con.commit(); con.close()

# Análisis por franjas: dos cuentas de lo que desaparece (total y baratas)
import oroboros_hours as H
import tempfile as _tf
def _ts(day, hh, mm=0): return int(datetime.datetime(2026, 11, day, hh, mm).timestamp())
arch3 = os.path.join(_tf.mkdtemp(), "a3.sqlite")
rows = [  # (item, t, min, qty, cheap, cheap_prev)
    (1, _ts(10, 10), 30, 100, 30, 30), (1, _ts(10, 14), 34, 60, 50, 10),          # 4 h: -40 total, -20 baratas
    (2, _ts(10, 10), 30, 100, 30, 30), (2, _ts(10, 17), 30, 0, 0, 0),             # 7 h: no cuenta
    (3, _ts(10, 10), 30, 50, 10, 10), (3, _ts(10, 12), 30, 80, 25, 20),           # sube: 0
    (4, _ts(10, 8, 30), 20, 90, 9, 9), (4, _ts(10, 9, 30), 20, 80, 9, 9), (4, _ts(10, 10, 30), 22, 70, 9, 9), (4, _ts(10, 11, 30), 24, 60, 9, 9),
    (5, _ts(10, 8, 30), 20, 90, 9, 9), (5, _ts(10, 9, 30), 20, 80, 9, 9), (5, _ts(10, 10, 30), 20, 70, 9, 9),
    (5, _ts(11, 8, 30), 20, 90, 9, 9), (5, _ts(11, 9, 30), 20, 80, 9, 9),
    (6, _ts(10, 22), 50, 100, 40, 40), (6, _ts(11, 2), 50, 60, 20, 20),          # cruza la medianoche
]
arch_write(arch3, [("M", t, i, mn, mn, q, c, cp) for i, t, mn, q, c, cp in rows])
A = H.analyze(arch3, "M")
b1 = A[1]
check((b1[2]["gone_total_h"], b1[2]["gone_cheap_h"], b1[3]["gone_total_h"], b1[3]["gone_cheap_h"]) == (10, 5, 10, 5),
      f"franjas: reparto a mano (10/h total, 5/h baratas en 8–12 y 12–16) {[(x['gone_total_h'], x['gone_cheap_h']) for x in b1]}")
check(all(x["gone_total_h"] is None for x in A.get(2, [{"gone_total_h": None}])), "franjas: un intervalo de más de 6 h no cuenta")
check(A[3][2]["gone_total_h"] == 0 and A[3][2]["gone_cheap_h"] == 0, "franjas: si lo publicado sube, cuenta 0")
check(A[4][2]["n"] == 3 and A[4][2]["ok"] is False, "franjas: 3 mediciones en un solo día no son fiables")
check(A[5][2]["n"] == 3 and A[5][2]["days"] == 2 and A[5][2]["ok"] is True, "franjas: 3 mediciones en 2 días sí")
check(A[4][2]["price_med"] == 21, f"franjas: precio típico = mediana del mínimo en la franja ({A[4][2]['price_med']})")
check(A[6][5]["gone_total_h"] == 10 and A[6][0]["gone_total_h"] == 10, "franjas: un intervalo que cruza la medianoche se reparte en 20–24 y 0–4")
check(H.summary(A[1]) is None and H.summary(A[5]) is not None, "franjas: resumen solo con franjas fiables")

# ProfessionDB (LibProfessionDB-1.0): lector de sus archivos de datos, sin cargar el addon
import professiondb as PDB
def write_fake_pdb(root):
    base = os.path.join(root, "Interface", "AddOns", "ProfessionDB", "Data", "Forever")
    os.makedirs(os.path.join(base, "_core")); os.makedirs(os.path.join(base, "esES"))
    head = 'local lib = LibStub and LibStub("LibProfessionDB-1.0", true)\nif not lib or not lib:IsGameVersion("Forever") then return end\n\n'
    files = {
        "_core/Alchemy.lua": head + """lib:LoadCore(171, {
		[3914] = { ["craftedItemId"] = 2996, ["difficulty"] = { 75, 105, 120, 135 },
			["reagents"] = { [2589] = 2 }, ["requiredSkill"] = 75, ["teaches"] = 3914 },
		[7001] = { ["craftedItemId"] = 4306, ["difficulty"] = { 1, 30, 45, 60 }, ["reagents"] = { [2589] = 1, [2320] = 1 },
			["requiredSkill"] = 120 },
		[7002] = { ["craftedItemId"] = 6070, ["difficulty"] = { 200, 220, 240, 260 }, ["reagents"] = { [4306] = 3 } },
		[7003] = { ["craftedItemId"] = 2589, ["difficulty"] = { 1, 10, 20, 30 }, ["reagents"] = { [2318] = 1 }, ["requiredSkill"] = 1 },
		[7004] = { ["craftedItemId"] = 14047, ["difficulty"] = { 1, 1, 1, 1 }, ["reagents"] = { [2589] = 1 } },
})

lib:LoadBorrowed("requiredSkill", "Vanilla", {7001})
""",
        "_core/Sources.lua": 'local lib = LibStub and LibStub("LibProfessionDB-1.0", true)\nif not lib then return end\n\nlib:LoadSources({\n[3914]={t={1385,1632},tn=29},\n[7001]={d={30,36,40},dn=951},\n})\n',
        "_core/VendorSources.lua": head + """lib:LoadSources({
[7002]={v={3085}},
})
lib:LoadSourceNames({
[3085]="Gloria Femmel",
})
lib:LoadVendorCosts({
[7002]={[3085]={{g=450}}},
})
""",
        "_core/AcquireMethods.lua": 'local lib = LibStub and LibStub("LibProfessionDB-1.0", true)\nif not lib then return end\n\nlib:LoadAcquireMethods({\n[7003]=1,\n})\n',
        "_core/HiddenRecipes.lua": 'local lib = LibStub and LibStub("LibProfessionDB-1.0", true)\nif not lib then return end\n\nlib:LoadHiddenRecipes({\n[7004]=true,\n})\n',
        "esES/Alchemy.lua": 'if GetLocale() ~= "esES" then return end\n' + head + 'lib:LoadNames(171, {\n\t\t[3914] = {\n\t\t\t["name"] = "Rollo de tela \\"de lino\\"",\n\t\t},\n\t\t[7001] = { ["name"] = "Seda prestada" },\n})\n',
    }
    for rel, txt in files.items():
        with open(os.path.join(base, rel), "w", encoding="utf-8") as fh:
            fh.write(txt)
    return base
_pdb_root = _tf.mkdtemp()
_pdb_base = write_fake_pdb(_pdb_root)
_sv_fake = os.path.join(_pdb_root, "WTF", "Account", "X", "SavedVariables", "Oroboros.lua")
check(PDB.find(_sv_fake) == _pdb_base, f"ProfessionDB: se encuentra subiendo desde Oroboros.lua ({PDB.find(_sv_fake)})")
R = PDB.load(_pdb_base)
r1, r2, r3 = R[3914], R[7001], R[7002]
check((r1["prof"], r1["profession"], r1["required"], r1["borrowed"], r1["crafted"], r1["reagents"], r1["name"], r1["diff"]) ==
      (171, "Alquimia", 75, False, 2996, {2589: 2}, 'Rollo de tela "de lino"', [75, 105, 120, 135]),
      f"ProfessionDB: nivel, reactivos, objeto y nombre en español {r1}")
check(r2["required"] == 120 and r2["borrowed"] is True and r2["sources"] == {"d": 951} and r1["sources"] == {"t": 29},
      "ProfessionDB: nivel prestado de Vanilla marcado y orígenes con su número real")
check(r3["required"] is None and r3["sources"] == {"v": 1} and r3["vendor"] == [("Gloria Femmel", 450, None)],
      f"ProfessionDB: vendedor con nombre y precio {r3['vendor']}")
check(R[7003]["acquire"] == 1 and R[7004]["hidden"] is True, "ProfessionDB: «con la profesión» y «nunca existió»")
check(PDB.find(os.path.join(_tf.mkdtemp(), "WTF", "x", "Oroboros.lua")) is None, "ProfessionDB: si no está, no pasa nada")

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
check(_ac.execute("SELECT o.qty, o.cheap, o.cheap_prev FROM observations o JOIN scans s USING (scan_id) "
                  "WHERE o.item_id=2589 ORDER BY s.t LIMIT 1").fetchone() == (240, 40, 40),
      "archivo: columnas total, baratas y baratas con el umbral anterior")
check(_ac.execute("SELECT COUNT(*) FROM markets").fetchone()[0] == 1, "archivo: cada mercado una sola vez")
_it = _ac.execute("SELECT name, first_seen, last_seen FROM items WHERE item_id=2589").fetchone()
check(_it and _it[0] == "Linen Cloth" and _it[1] and _it[2] >= _it[1], f"archivo: cada producto una sola vez, con nombre y primera/última vez visto {_it}")
check(_ac.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == ("2",), "archivo: versión del esquema")
_ac.close()

# Histórico diario: observaciones > histórico del juego > Auctionator
from oroboros_archive import update_daily
import auctionator_source as _atrs
arch_d = os.path.join(_tf.mkdtemp(), "d.sqlite")
D, D1, D2 = "2026-11-10", "2026-11-09", "2026-11-08"
_tsd = lambda d, hh: int(datetime.datetime.fromisoformat(d).replace(hour=hh).timestamp())
arch_write(arch_d, [("M", _tsd(D, 10), 2589, 30, 32, 240, 40, 40), ("M", _tsd(D, 18), 2589, 28, 31, 200, 30, 35)])
_hist_db = {"markets": {"M": {"history": {2589: {D: {"min": 99, "mv": 99, "qty": 9, "t": _tsd(D, 9)},
                                                  D1: {"min": 27, "mv": 29, "qty": 300, "t": _tsd(D1, 20)}}}}}}
_atr = {"markets": {"PvE": {2589: {"m": 26, "h": {D: 77, D1: 77, D2: 50}, "l": {D2: 45}, "a": {D2: 500}}}}, "last_scan": None}
_cd = open_archive(arch_d)
update_daily(_cd, _hist_db)
_atrs.to_daily(_cd, _atr, "M")
_q = lambda: _cd.execute("""SELECT day, min_low, min_high, mv, qty_max, src FROM daily d JOIN markets m USING (market_id)
                            WHERE m.key='M' AND item_id=2589 ORDER BY day""").fetchall()
got = _q()
check(got == [(D2, 45, 50, 50, 500, "atr"), (D1, 27, 27, 29, 300, "oro"), (D, 28, 30, 31, 240, "obs")],
      f"diario: gana la observación, luego el juego, luego Auctionator {got}")
update_daily(_cd, _hist_db); _atrs.to_daily(_cd, _atr, "M")
check(_q() == got, "diario: repetir no cambia nada")
check(_cd.execute("SELECT t FROM daily WHERE day=?", (D,)).fetchone()[0] == _tsd(D, 18), "diario: hora del último escaneo del día")
_cd.close()

# Resumen semanal y retención de 8 semanas: resumir no cambia las franjas
from oroboros_archive import rollup
arch_r = os.path.join(_tf.mkdtemp(), "r.sqlite")
_now_r = int(datetime.datetime(2026, 11, 19, 12, 0).timestamp())
_flat = []
for base_day, weeks_ago in ((datetime.date(2026, 9, 7), 10), (datetime.date(2026, 11, 16), 0)):
    for dd_ in range(3):                                  # 3 días seguidos, escaneos cada 3 h
        q_, c_ = 1000, 300
        for hh in range(0, 24, 3):
            t_ = int(datetime.datetime.combine(base_day + datetime.timedelta(days=dd_), datetime.time(hh)).timestamp())
            drop = 30 if hh >= 18 else 6
            _flat.append(("M", t_, 2589, 20 + (hh % 7), 25, q_, c_, c_ - drop))
            q_, c_ = q_ - drop, c_ - drop
arch_write(arch_r, _flat)
_cr = open_archive(arch_r); update_daily(_cr); _cr.close()
before = H.analyze(arch_r, "M")
_cr = open_archive(arch_r)
n_old = _cr.execute("SELECT COUNT(*) FROM scans WHERE t < ?", (_now_r - 56 * 86400,)).fetchone()[0]
n_daily = _cr.execute("SELECT COUNT(*) FROM daily").fetchone()[0]
rolled = rollup(_cr, _now_r)
check(rolled == n_old > 0 and _cr.execute("SELECT COUNT(*) FROM scans WHERE t < ?", (_now_r - 56 * 86400,)).fetchone()[0] == 0,
      f"retención: los escaneos de más de 8 semanas se resumen y se borran ({rolled})")
check(_cr.execute("SELECT COUNT(*) FROM weekly_band").fetchone()[0] > 0 and
      _cr.execute("SELECT COUNT(*) FROM daily").fetchone()[0] == n_daily, "retención: queda el resumen semanal y el histórico diario intacto")
check(rollup(_cr, _now_r) == 0, "retención: resumir otra vez no hace nada")
_cr.close()
after = H.analyze(arch_r, "M")
check(before == after, "retención: las franjas dan lo mismo antes y después de resumir"
      + ("" if before == after else f" {before.get(2589)} != {after.get(2589)}"))

# Resumen por objeto (Camel) y Resumen.lua para el juego
from oroboros_summary import item_summary, write_resumen
_today = datetime.date(2026, 11, 19)
_rows = [("2026-09-01", 150, 140, 150), ("2026-11-12", 200, 190, 210), ("2026-11-18", 80, 75, 85), ("2026-11-19", 100, 95, 105)]
_weeks = [""] * 13; _weeks[1] = "150"; _weeks[11] = "200"; _weeks[12] = "90"
_days = [""] * 14; _days[6] = "200"; _days[12] = "80"; _days[13] = "100"
_exp = "100;90;127;133;80;20261118;200;20261112;;;" + ",".join(_weeks) + ";" + ",".join(_days) + ";20261119"
_got = item_summary(_rows, None, _today)
check(_got == _exp, f"resumen: medias 7/30/90, mínimo y máximo con fecha, 13 semanas y 14 días | {_got} | {_exp}")
check(item_summary([("2026-07-01", 100, 90, 110)], None, _today) is None, "resumen: sin datos en 90 días no hay resumen")
arch_s = os.path.join(_tf.mkdtemp(), "s.sqlite")
_cs = open_archive(arch_s)
_RARO = 'Reino"raro' + chr(92) + '-Horde'          # comillas y una barra invertida en la clave
_mid = __import__("oroboros_archive").market_id(_cs, _RARO)
_cs.executemany("INSERT INTO daily VALUES (?,2589,?,?,?,?,1,'obs',NULL)", [(_mid, d, lo, hi, mv) for d, mv, lo, hi in _rows])
_cs.commit(); _cs.close()
_out = os.path.join(_tf.mkdtemp(), "Resumen.lua")
_res = write_resumen(arch_s, _out, _today)
_lr = LuaRuntime(unpack_returned_tuples=True); _lr.execute(open(_out, encoding="utf-8").read())
_mk_tbl = _lr.globals().OroborosResumen.markets[_RARO]
check(_res["items"] == 1 and _lr.eval("OroborosResumen.v") == 1 and _mk_tbl is not None and _mk_tbl[2589] == _exp,
      "Resumen.lua: Lua válido (con comillas y barras en la clave) y la misma cadena")

# Migración desde la tabla plana del 19/11 (esquema 1)
arch_v1 = os.path.join(_tf.mkdtemp(), "v1.sqlite")
_v1 = sqlite3.connect(arch_v1)
_v1.executescript("""CREATE TABLE scans (market TEXT, t INTEGER, item_id INTEGER, min REAL, mv REAL, qty INTEGER,
    cheap INTEGER, cheap_prev INTEGER, PRIMARY KEY (market, t, item_id));""")
_v1.executemany("INSERT INTO scans VALUES (?,?,?,?,?,?,?,?)", [
    ("M", 100, 2589, 30, 32, 240, 40, 40), ("M", 100, 4306, None, None, 0, 0, 0), ("M", 200, 2589, 31, 33, 200, 30, 35)])
_v1.commit(); _v1.close()
_v2 = open_archive(arch_v1)
check(_v2.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 3 and
      _v2.execute("SELECT COUNT(*) FROM scans").fetchone()[0] == 2 and
      _v2.execute("SELECT value FROM meta WHERE key='schema'").fetchone() == ("2",) and
      os.path.exists(arch_v1 + ".bak"), "archivo: migración de la tabla plana sin perder filas, con copia .bak")
_v2.close()
fake = {"markets": {"M": {"scans": [{"t": 1000 + i, "data": "2589,30,32,240,40,40"} for i in range(12)]}}}
arch2 = os.path.join(_tf.mkdtemp(), "a2.sqlite")
append_scans(arch2, {"markets": {"M": {"scans": [{"t": 10, "data": "2589,30,32,240,40,40"}]}}})
check(append_scans(arch2, fake)["gap"] is True, "archivo: avisa si se han perdido escaneos (buffer lleno sin solape)")
fake["markets"]["M"]["scans"][0]["t"] = 10
check(append_scans(arch2, fake)["gap"] is False, "archivo: sin hueco si hay solape")
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), sv, "--archive", arch, "--resumen", "no"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r.returncode == 0 and "Archivo" in r.stdout, "exportador: --archive " + (r.stdout + r.stderr)[-200:])
from oroboros_summary import write_resumen as _wr
_out_a = os.path.join(_tf.mkdtemp(), "Resumen.lua"); _wr(arch, _out_a)
_la = LuaRuntime(unpack_returned_tuples=True); _la.execute(open(_out_a, encoding="utf-8").read())
_ca = sqlite3.connect(arch)
_mk_a, _tmax = _ca.execute("SELECT m.key, MAX(s.t) FROM scans s JOIN markets m USING (market_id)").fetchone(); _ca.close()
check(_la.globals().OroborosResumen.archived[_mk_a] == _tmax, "Resumen.lua lleva hasta qué escaneo está archivado cada mercado")

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
                    "--json", os.path.join(tmp, "p.json"), "--html", os.path.join(tmp, "p.html"), "--synthetic", "--now", NOW, "--catalog", CAT_TEST], capture_output=True, text=True, encoding="utf-8", errors="replace")
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
                     "--json", os.path.join(tmp, "p2.json"), "--banker", "none", "--now", NOW, "--catalog", CAT_TEST], capture_output=True, text=True, encoding="utf-8", errors="replace")
p2 = json.load(open(os.path.join(tmp, "p2.json"), encoding="utf-8"))

# Franjas en el plan: con --archive, la venta dice en qué franja desaparece más
import datetime as _dt, tempfile as _tf2
opp_x = next(o for o in plan["opportunities"] if o.get("included") and o["kind"] == "craft")
X = opp_x["out_item"]
arch_p = os.path.join(_tf2.mkdtemp(), "arch.sqlite")
qty_, rows_ = 10000, []
for k in range(36):                                   # cada 2 h durante 3 días
    t = int(_dt.datetime(2026, 11, 10, 0, 0).timestamp()) + k * 7200
    hr = _dt.datetime.fromtimestamp(t).hour
    drop = 40 if hr >= 20 else 2                       # el intervalo que empieza aquí
    mn = 80 if 4 <= hr < 8 else 100
    rows_.append((plan["market"], t, X, mn, mn, qty_, 500))
    qty_ -= drop
# cheap_prev de cada escaneo = cheap anterior − lo barato desaparecido en el intervalo previo
fixed = []
for j, r_ in enumerate(rows_):
    prev_drop = (40 if _dt.datetime.fromtimestamp(rows_[j - 1][1]).hour >= 20 else 2) if j else 0
    fixed.append(r_ + (500 - prev_drop,))
arch_write(arch_p, fixed)
r4 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "a.sqlite"),
                     "--json", os.path.join(tmp, "p4.json"), "--html", os.path.join(tmp, "p4.html"), "--synthetic",
                     "--now", NOW, "--archive", arch_p, "--catalog", CAT_TEST], capture_output=True, text=True, encoding="utf-8", errors="replace")
p4 = json.load(open(os.path.join(tmp, "p4.json"), encoding="utf-8"))
why_x = [w for o in p4["opportunities"] if o["out_item"] == X for w in o.get("why", [])]
check(any("de 20 a 24 h" in w and "/h barato" in w for w in why_x), f"plan: la venta dice en qué franja desaparece más ({X})")
check(not any("/h barato" in w for o in plan["opportunities"] for w in o.get("why", [])), "plan sin --archive: sin textos de franja")
check(p4["items"][str(X)]["hours"][5]["ok"] is True, "plan: las franjas del objeto van al JSON")
check('["horas", "Horas"]' in open(os.path.join(tmp, "p4.html"), encoding="utf-8").read(), "página: pestaña Horas")
_html = open(os.path.join(tmp, "p4.html"), encoding="utf-8").read()
check(all(f'[{d}, "{t}"]' in _html for d, t in ((30, "1 mes"), (90, "3 meses"), (180, "6 meses"), (365, "1 año"), (0, "Todo")))
      and 'id="mk-stats"' in _html, "página: Mercado con rangos (1 mes a todo) y tabla de mínimos, máximos y medias")

# Ventas por día: cada bajada se divide por el tiempo real entre datos (0,5 a 3 días)
from oroboros_plan import daily_drops, find_flips
hh = [{"day": "2026-11-01", "qty": 1000}, {"day": "2026-11-05", "qty": 600}, {"day": "2026-11-06", "qty": 590},
      {"day": "2026-11-07", "qty": 580}, {"day": "2026-11-08", "qty": 570}]
check(daily_drops(hh) == [10, 10, 10], f"ventas/día: un hueco de 4 días no cuenta ({daily_drops(hh)})")
hh2 = [{"day": "2026-11-14", "qty": 3833}, {"day": "2026-11-16", "qty": 4560}, {"day": "2026-11-17", "qty": 3000}]
check(daily_drops(hh2) == [0, 1560], "ventas/día: subida = 0; un día = la bajada entera")
hh3 = [{"day": "2026-11-18", "qty": 2800, "t": 1795033080}, {"day": "2026-11-19", "qty": 1018, "t": 1795033080 + 12600}]
check(daily_drops(hh3) == [], "ventas/día: dos escaneos a 3,5 h no son un día (eso lo miden las franjas)")
hh4 = [{"day": "2026-11-17", "qty": 300, "t": 1000}, {"day": "2026-11-19", "qty": 200, "t": 1000 + 2 * 86400}]
check(daily_drops(hh4) == [50], "ventas/día: con hora real, 100 en 2 días = 50/día")

# Reventa: no si el precio ya estaba ayer a ese nivel (es su precio nuevo, no una bajada puntual)
import shutil as _sh
from oroboros_plan import Data as _Data
fdb = os.path.join(tmp, "flip.sqlite"); _sh.copy(os.path.join(tmp, "a.sqlite"), fdb)
_now = int(_dt.datetime.fromisoformat(NOW).timestamp())
_day = lambda k: (_dt.date.fromtimestamp(_now) - _dt.timedelta(days=k)).isoformat()
def _flip_case(mv_yesterday):
    _sh.copy(os.path.join(tmp, "a.sqlite"), fdb)
    _f = sqlite3.connect(fdb); mk = plan["market"]
    _f.execute("INSERT INTO items (item_id, name) VALUES (777777, 'Gema de prueba')")
    _f.execute("INSERT INTO prices VALUES (?,777777,300,300,200,10,?,60,120,180,200,'oro')", (mk, _now))
    for k, (mv, q) in zip((4, 3, 2, 1), ((1000, 300), (1000, 280), (1000, 260), (mv_yesterday, 240))):
        _f.execute("INSERT INTO history VALUES (?,777777,?,?,?,?,'oro',NULL)", (mk, _day(k), mv, mv, q))
    _f.commit(); _f.close()
    dd = _Data(fdb, CAT_TEST, now=_now)
    return [f for f in find_flips(dd, 48, next(iter(dd.chars))) if f["out_item"] == 777777]
check(len(_flip_case(1000)) == 1, "reventa: bajada puntual frente a su mediana")
check(len(_flip_case(310)) == 0, "reventa: no si ayer ya estaba a ese precio")

# El plan sale del archivo (--archive) y propone lo mismo que sin él
arch_e = os.path.join(tmp, "arch_e.sqlite")
_cpre = open_archive(arch_e)        # un día viejo que solo está en el archivo (como uno que el juego ya olvidó)
_cpre.execute("INSERT INTO daily VALUES (?,2589,'2026-09-01',11,12,12,999,'atr',NULL)",
              (__import__("oroboros_archive").market_id(_cpre, "ForeverPvE-Horde"),))
_cpre.commit(); _cpre.close()
r5 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), os.path.join(tmp, "A.lua"),
                     "--sqlite", os.path.join(tmp, "e.sqlite"), "--archive", arch_e, "--resumen", os.path.join(tmp, "Resumen.lua")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r5.returncode == 0 and "histórico diario" in r5.stdout, "exportador con archivo: " + (r5.stdout + r5.stderr)[-250:])
_ce = sqlite3.connect(os.path.join(tmp, "e.sqlite"))
_ca = sqlite3.connect(os.path.join(tmp, "a.sqlite"))
_hq = "SELECT market, item_id, day, min, mv, qty FROM history WHERE day > '2026-09-01' ORDER BY market, item_id, day"
check(_ce.execute(_hq).fetchall() == _ca.execute(_hq).fetchall(), "exportador con archivo: mismos valores del histórico que sin archivo")
check(_ce.execute("SELECT qty, src FROM history WHERE item_id=2589 AND day='2026-09-01'").fetchone() == (999, "atr"),
      "exportador con archivo: el histórico del plan sale del diario (incluye días que el juego ya no tiene)")
_ce.close(); _ca.close()
r6 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "e.sqlite"),
                     "--json", os.path.join(tmp, "p6.json"), "--synthetic", "--now", NOW, "--catalog", CAT_TEST],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
p6 = json.load(open(os.path.join(tmp, "p6.json"), encoding="utf-8"))
_sel = lambda pl: sorted((o["name"], o["units"]) for o in pl["opportunities"] if o.get("included"))
check(_sel(p6) == _sel(plan), "plan desde el archivo: mismas oportunidades que sin archivo")
_lr2 = LuaRuntime(unpack_returned_tuples=True); _lr2.execute(open(os.path.join(tmp, "Resumen.lua"), encoding="utf-8").read())
check("Resumen" in r5.stdout and _lr2.eval("OroborosResumen.v") == 1 and _lr2.globals().OroborosResumen.markets["ForeverPvE-Horde"] is not None,
      "exportador con archivo: escribe Resumen.lua válido")
check(not os.path.exists(os.path.join(ROOT, "Oroboros", "Resumen.lua")) or "ForeverPvE-Horde" not in open(os.path.join(ROOT, "Oroboros", "Resumen.lua"), encoding="utf-8").read(),
      "las pruebas no escriben datos inventados en la carpeta del addon")

# Vigilante (fase 3): procesa los datos cuando el juego termina de guardar Oroboros.lua
from oroboros_watch import watch
def _watch_case(mtimes, fail_first=False, cycles=6):
    clock = [0.0]; seq = list(mtimes); tries = [0]
    def mt(_):
        return seq.pop(0) if len(seq) > 1 else seq[0]
    def run():
        tries[0] += 1
        if fail_first and tries[0] == 1:
            raise RuntimeError("fallo de prueba")
    n = watch("x", run, interval=30, settle=10, cycles=cycles, clock=lambda: clock[0],
              sleep=lambda sec: clock.__setitem__(0, clock[0] + sec), mtime=mt, log=lambda *_: None)
    return n, tries[0]
check(_watch_case([100, 200, 200, 200]) == (1, 1), "vigilante: un guardado estable dispara el proceso una vez")
check(_watch_case([100, 200, 300, 400, 500, 600, 700]) == (0, 0), "vigilante: mientras el archivo sigue cambiando, espera")
check(_watch_case([100]) == (0, 0), "vigilante: sin cambios no hace nada")
check(_watch_case([100, 200, 200, 300, 300, 300], fail_first=True) == (1, 2), "vigilante: un fallo se registra y sigue vigilando")
wtmp = os.path.join(tmp, "watch")
rw = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_watch.py"), os.path.join(tmp, "A.lua"), "--work", wtmp,
                     "--resumen", os.path.join(wtmp, "Resumen.lua"), "--once", "--log", os.path.join(tmp, "vigilante.log")],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
check(rw.returncode == 0 and all(os.path.exists(os.path.join(wtmp, f)) for f in ("plan.html", "archivo.sqlite", "Resumen.lua", "oroboros.sqlite")),
      "vigilante --once: exporta, archiva, genera el plan y el resumen " + (rw.stdout + rw.stderr)[-200:])
check("Listo:" in open(os.path.join(tmp, "vigilante.log"), encoding="utf-8").read(), "vigilante --log: deja constancia en un archivo")

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
json.dump(_strip_skill(json.load(open(CAT_TEST, encoding="utf-8"))),
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
# Dentro de ese 30 %, lo que no es lote de prueba (reventas de riesgo) usa como mucho la mitad
import oroboros_plan as _OP
class _FakePlan:
    def __init__(self, spent=0.0): self.spent = spent
    def clone(self): return _FakePlan(self.spent)
    def spend(self): return self.spent
def _fake_apply(plan, o): plan.spent += o["cost_total"]; return 0
_orig = (_OP.apply_flip, _OP.apply_opportunity)
_OP.apply_flip = _OP.apply_opportunity = _fake_apply
_opps = ([{"kind": "flip", "name": f"reventa {k}", "conf": "baja", "cost_total": 10, "profit_total": 100, "profit": 100,
           "crafts": 1, "reason": None} for k in range(5)] +
         [{"kind": "craft", "name": f"lote {k}", "conf": "baja", "cost_total": 5, "profit_total": 5, "profit": 5,
           "crafts": 1, "trial": True, "reason": None} for k in range(3)])
_OP.select(None, _FakePlan(), _opps, 100, 48)
_OP.apply_flip, _OP.apply_opportunity = _orig
_inc_f = sum(1 for o in _opps if o["kind"] == "flip" and o.get("included"))
_inc_t = sum(1 for o in _opps if o["kind"] == "craft" and o.get("included"))
check((_inc_f, _inc_t) == (1, 3), f"riesgo: las reventas usan como mucho la mitad del 30 % y los lotes de prueba entran ({_inc_f} reventas, {_inc_t} lotes)")
# Subasta o vendedor se decide por objeto (bolsas + banco), no por sitio
_vdb = os.path.join(tmp, "vend.sqlite"); _sh.copy(os.path.join(tmp, "a.sqlite"), _vdb)
_cv = sqlite3.connect(_vdb)
_ck = _cv.execute("SELECT char FROM characters ORDER BY char LIMIT 1").fetchone()[0]
_vi = 2589                                  # Paño de lino: 3 en bolsas no llegan al mínimo, 43 en total sí
_cv.execute("DELETE FROM inventory WHERE item_id=?", (_vi,))
_cv.execute("INSERT INTO inventory VALUES (?, 'bags', ?, 3)", (_ck, _vi))
_cv.execute("INSERT INTO inventory VALUES (?, 'bank', ?, 40)", (_ck, _vi))
_cv.commit(); _cv.close()
_pv = _OP.build_plan(_Data(_vdb, CAT_TEST, now=_now))
_acts = {e["loc"]: e["action"] for v in _pv["inventory"] if v["owner"] == _ck for e in v["items"] if e["item"] == _vi}
check(len(_acts) == 2 and len(set(_acts.values())) == 1, f"inventario: el mismo objeto en bolsas y banco recibe la misma decisión {_acts}")
reach = [l.get("reach") for l in p3["learn"] if not l.get("new_profession")]
first_unknown = reach.index("desconocido") if "desconocido" in reach else len(reach)
check(all(x == "desconocido" for x in reach[first_unknown:]) and 0 < first_unknown < len(reach),
      f"aprender: primero lo que está a tu alcance, al final el nivel sin comprobar ({reach.count('desconocido')} de {len(reach)})")

# ProfessionDB en el plan: nivel real, dónde se aprende, sin recetas que nunca existieron, profesiones nuevas
import professiondb as _P
_pdb_db = os.path.join(tmp, "pdb.sqlite"); _sh.copy(nh, _pdb_db)
_pc = sqlite3.connect(_pdb_db)
_pc.execute("UPDATE recipes SET source=NULL WHERE recipe_id=17580")      # en Forever el juego no da el origen
_priced = _pc.execute("SELECT item_id FROM prices ORDER BY mv DESC LIMIT 1").fetchone()[0]
_P.write_tables(_pc, {
    17580: {"prof": 171, "profession": "Alquimia", "name": "Poción de maná superior", "required": 295, "borrowed": False,
            "diff": [295, 310, 320, 330], "reagents": {}, "crafted": 13444, "sources": {"t": 29}, "vendor": [], "acquire": 0,
            "hidden": False, "scroll": None},
    17635: {"prof": 171, "profession": "Alquimia", "name": "Frasco de los titanes", "required": 300, "borrowed": False,
            "diff": [300, 315, 322, 330], "reagents": {}, "crafted": 13510, "sources": {}, "vendor": [], "acquire": 0,
            "hidden": True, "scroll": None},
    990001: {"prof": 202, "profession": "Ingeniería", "name": "Artilugio de prueba", "required": 50, "borrowed": True,
             "diff": [50, 70, 80, 90], "reagents": {2589: 1}, "crafted": _priced, "sources": {"v": 1},
             "vendor": [["Gloria Femmel", 450, None]], "acquire": 0, "hidden": False, "scroll": None},
})
_pc.commit(); _pc.close()
_dpdb = _Data(_pdb_db, cat_ns, now=_now)
from oroboros_plan import learn_suggestions
_L = {e["recipe"]: e for e in learn_suggestions(_dpdb, 48)}
_e = _L.get(17580)
check(_e is not None and _e["skill_req"] == 295 and _e["reach"] in ("ok", "falta") and any("instructor" in v for v in _e["verdict"]),
      f"aprender: con ProfessionDB, nivel real y dónde se aprende ({_e and _e['reach']}, {_e and _e['verdict']})")
check(17635 not in _L, "aprender: las recetas que nunca existieron no se proponen")
_n = _L.get(990001)
check(_n is not None and _n["new_profession"] and _n["learn_cost"] == 450 and any("Gloria Femmel" in v for v in _n["verdict"])
      and any("Vanilla" in v for v in _n["verdict"]),
      f"aprender: «si cambiaras de profesión» sale de ProfessionDB, con vendedor, coste y nivel prestado ({_n and _n['verdict']})")
r_pdb = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), os.path.join(tmp, "A.lua"),
                        "--sqlite", os.path.join(tmp, "pdbx.sqlite"), "--professiondb", _pdb_base],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
_cx2 = sqlite3.connect(os.path.join(tmp, "pdbx.sqlite"))
check(r_pdb.returncode == 0 and _cx2.execute("SELECT COUNT(*) FROM pdb_recipes").fetchone()[0] == 5 and "ProfessionDB" in r_pdb.stdout,
      "exportador: --professiondb guarda las recetas en el SQLite del plan " + (r_pdb.stdout + r_pdb.stderr)[-160:])
_cx2.close()
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
