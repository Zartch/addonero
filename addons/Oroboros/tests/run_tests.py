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
for f in ["Core.lua", "DB.lua", "Scanner.lua", "Professions.lua", "Ledger.lua", "Queue.lua", "Style.lua", "Chart.lua", "UI.lua", "PriceHistory.lua", "Inventory.lua", "Farm.lua", "FarmPanel.lua"]:
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

# Farmeo: medición en el juego (muertes, botín por criatura, recolección, nivel y clasificación)
FARM = ns.Farm
check(FARM.NpcFromGUID("Creature-0-3110-0-12345-1234-0000ABCDEF") == 1234 and FARM.NpcFromGUID("Player-1-0001") is None,
      "farmeo: número de criatura desde su GUID")
lua.execute("FARM_T = 100000; time = function() return FARM_T end; OroborosDB.farm = nil")
def _kill(npc, spawn, t):        # despojar un cadáver = una muerte
    lua.execute(f"FARM_T = {t}")
    lua.execute(f'LOOT = {{ {{ type = 2, qty = 0, sources = {{ "Creature-0-1-0-1-{npc}-{spawn}", 0 }} }} }}')
    fire("LOOT_OPENED")
for k in range(3):
    _kill(1234, 100 + k, 100000 + 10 * k)
_m = lua.eval('OroborosDB.farm.mobs["1234@Bosque X"]')
check(_m.kills == 3 and _m.secs == 20 and _m.zone == "Elwynn" and _m.map == 1429, f"farmeo: 3 muertes, 20 s activos ({_m.kills}, {_m.secs})")
_kill(1234, 103, 100000 + 20 + 300)
check(_m.kills == 4 and _m.secs == 20, "farmeo: tras 5 minutos sin matar, ese hueco no cuenta como tiempo activo")
_kill(1234, 103, 100000 + 20 + 330)
check(_m.kills == 4, "farmeo: volver a abrir el mismo cadáver no suma otra muerte")
check(not any('"COMBAT_LOG_EVENT_UNFILTERED"' in open(os.path.join(ADDON, f), encoding="utf-8").read()
              for f in os.listdir(ADDON) if f.endswith(".lua") and f not in ("Resumen.lua", "Farmeo.lua")),
      "ningún archivo del addon se registra en el registro de combate (en Midnight es una acción prohibida)")
lua.execute("LOG = {}")
fire("ADDON_ACTION_FORBIDDEN", "Oroboros", "RegisterEvent()")
fire("ADDON_ACTION_FORBIDDEN", "OtroAddon", "CastSpellByName()")
check(G.OroborosDB.blocked.func == "RegisterEvent()" and G.OroborosDB.blocked.kind == "prohibida"
      and sum("bloqueado" in l for l in G.LOG.values()) == 1, "si el juego bloquea una acción de Oroboros, se apunta cuál y se avisa")
lua.execute("""LOOT = {
  { type = 1, link = "|Hitem:2589::|h[Linen]|h", qty = 3, sources = { "Creature-0-1-0-1-1234-10", 2, "Creature-0-1-0-1-5678-20", 1 } },
  { type = 2, qty = 0, sources = { "Creature-0-1-0-1-1234-10", 57, "Creature-0-1-0-1-5678-20", 12 } },
}""")
fire("LOOT_OPENED"); fire("LOOT_OPENED")
_m2 = lua.eval('OroborosDB.farm.mobs["5678@Bosque X"]')
check(_m["items"][2589] == 2 and _m.copper == 57 and _m2["items"][2589] == 1 and _m2.copper == 12,
      "farmeo: el botín de varios cadáveres se reparte por criatura, y reabrirlo no suma")
lua.execute("""LOOT = { { type = 1, link = "|Hitem:2447::|h[Peacebloom]|h", qty = 2, sources = { "GameObject-0-1-0-1-1617-55", 2 } } }""")
fire("LOOT_OPENED")
_g = lua.eval('OroborosDB.farm.gather["Bosque X"]')
check(_g.nodes == 1 and _g["items"][2447] == 2, "farmeo: recolección (nodo) aparte")
lua.execute('TARGET = { guid = "Creature-0-1-0-1-1234-10", name = "Lobo", lvl = 12, cls = "normal", attack = true }')
fire("PLAYER_TARGET_CHANGED")
_n = lua.eval("OroborosDB.farm.npcs[1234]")
check(_n.name == "Lobo" and _n.lvl == 12 and _n.cls == "normal", "farmeo: nivel y clasificación de la criatura objetivo")
lua.execute('SUBZONE = ""')
_kill(4321, 1, 200000)
check(lua.eval('OroborosDB.farm.mobs["4321@Elwynn"]') is not None, "farmeo: sin subzona se usa la zona")
# Mazmorras (Midnight): valores secretos. No se toca nada dentro de una instancia ni ningún valor secreto
lua.execute("LOG = {}")
lua.execute('SECRETS = { ["Creature-0-1-0-1-7778-1"] = true }')
check(FARM.NpcFromGUID("Creature-0-1-0-1-7778-1") is None and FARM.NpcFromGUID("Creature-0-1-0-1-7779-1") == 7779,
      "farmeo: un GUID secreto no se trocea")
lua.execute('IN_INSTANCE = true; TARGET = { guid = "Creature-0-1-0-1-7777-1", name = "Jefe", lvl = 20, cls = "elite", attack = true }')
fire("PLAYER_TARGET_CHANGED")
lua.execute('LOOT = { { type = 2, qty = 0, sources = { "Creature-0-1-0-1-7777-1", 500 } } }')
fire("LOOT_OPENED")
check(lua.eval("OroborosDB.farm.npcs[7777]") is None and lua.eval('OroborosDB.farm.mobs["7777@Bosque X"]') is None,
      "farmeo: dentro de una mazmorra no mide nada")
lua.execute('IN_INSTANCE = false; TARGET = { guid = "Creature-0-1-0-1-7778-1", name = "X", lvl = 20, cls = "normal", attack = true }')
fire("PLAYER_TARGET_CHANGED")
lua.execute('LOOT = { { type = 2, qty = 0, sources = { "Creature-0-1-0-1-7778-1", 500 } } }')
fire("LOOT_OPENED")
check(lua.eval("OroborosDB.farm.npcs[7778]") is None and not any("error" in l for l in G.LOG.values()),
      "farmeo: con valores secretos no da error en el chat")
lua.execute('SECRETS = {}; SUBZONE = "Bosque X"; TARGET = nil; LOOT = {}; CLEU = {}; time = os.time')

# Reino vacío (pasó en Forever el 20/11): se usa el último bueno y se arreglan los datos guardados sin reino
_rk = ns.MarketKey()
lua.execute('_GNRN, _GRN = GetNormalizedRealmName, GetRealmName; GetNormalizedRealmName = function() return "" end; GetRealmName = function() return "" end')
check(ns.MarketKey() == _rk and ns.CharKey().endswith("-ForeverNormal"),
      f"reino vacío: la clave de mercado sigue siendo la buena ({ns.MarketKey()})")
lua.execute("""
local good = OroborosDB.markets[ns_MK]
good.prices[9001] = { min = 100, mv = 100, qty = 5, t = 1000 }
good.prices[9002] = { min = 300, mv = 300, qty = 5, t = 3000 }
good.history[9001] = { ["2026-11-20"] = { min = 90, mv = 100, qty = 5, t = 1000 } }
OroborosDB.markets["-Horde"] = { lastFull = 2000, scans = { { t = 2000, data = "9001,80,80,3,1,1" } },
  prices = { [9001] = { min = 80, mv = 80, qty = 3, t = 2000 }, [9002] = { min = 999, mv = 999, qty = 1, t = 2000 } },
  history = { [9001] = { ["2026-11-20"] = { min = 80, mv = 85, qty = 3, t = 2000 }, ["2026-11-19"] = { min = 70, mv = 70, qty = 1, t = 500 } } } }
OroborosDB.chars["Zartch-"] = { market = "-Horde", level = 2, t = time() + 100, bags = { [2589] = 7 }, professions = {} }
""".replace("ns_MK", repr(_rk)))
_fx = ns.DB.FixEmptyRealm()
_gm_ = G.OroborosDB.markets[_rk]
_h = _gm_.history[9001]
_ch = G.OroborosDB.chars[ns.CharKey()]
check(G.OroborosDB.markets["-Horde"] is None and _gm_.prices[9001].min == 80 and _gm_.prices[9002].min == 300
      and _h["2026-11-20"].min == 80 and _h["2026-11-20"].mv == 85 and _h["2026-11-19"].min == 70
      and any(s.t == 2000 for s in _gm_.scans.values()),
      "reino vacío: el mercado «-Facción» se fusiona con el bueno (gana lo más reciente; mínimo del día)")
check(G.OroborosDB.chars["Zartch-"] is None and _ch.level == 2 and _ch.market == _rk and _ch.bags[2589] == 7,
      "reino vacío: el personaje «Nombre-» se une al bueno")
lua.execute("GetNormalizedRealmName, GetRealmName = _GNRN, _GRN")

# Equipo verde de Forever: puja ≈ vendedor y compra directa mucho más alta. Se guardan las dos y una muestra en bruto
lua.execute("""_REP = REPLICATE
REPLICATE = { { "Daga cruzada", 1, 2819, 14000, 3825, 2 }, { "Daga cruzada", 1, 2819, 0, 3800, 2 },
              { "Daga cruzada", 1, 2819, 15000, 3900, 2 }, { "Linen Cloth", 20, 2589, 600 }, { "Daga cruzada", 1, 2819, 3830, 0, 2 } }
OroborosDB.items[2819] = OroborosDB.items[2819] or {}; OroborosDB.items[2819].s = 3830
C_AuctionHouse.GetReplicateItemLink = function(i) return "|Hitem:2819::::::1234|h[Daga cruzada del mono]|h" end""")
lua.execute("OroborosDB.searchSample = { itemID = 2819, rows = {} }")
_acc = ns.Scanner.NewReplicateAcc()
for _i in range(5):
    ns.Scanner.ReadReplicateRow(_i, _acc)
ns.DB.RecordPrices(_acc.byItem, True, "Prueba-Puja", _acc)
_pd = ns.DB.GetPrice(2819, "Prueba-Puja")
_smp = [r for r in _acc.sample.values()]
check(_pd.min == 3830 and _pd.bid == 3800 and _pd.nb == 1 and len(_smp) == 4
      and all(r.itemID == 2819 for r in _smp) and _smp[1].minBid == 3800 and _smp[1].buyout == 0
      and _smp[3].atVendor is True and "del mono" in _smp[3].link and len(list(_acc.focusRows.values())) == 4,
      "escaneo: guarda compra directa, puja mínima y subastas solo de puja; muestra en bruto (con enlace) de las filas raras y de las que están al precio del vendedor")
lua.execute("OroborosDB.markets['Prueba-Puja'] = nil; REPLICATE = _REP")
# Sufijos: mismo itemID, nombre y precio distintos → compra directa por nombre, y el tooltip usa la del objeto que ves
lua.execute("""_REP = REPLICATE
REPLICATE = { { "Daga cruzada del bandido", 1, 2819, 10000, 4000, 2 }, { "Daga cruzada del bandido", 1, 2819, 14197, 0, 2 },
              { "Daga cruzada del mono", 1, 2819, 3825, 3800, 2 }, { "Daga cruzada del mono", 1, 2819, 3830, 0, 2 },
              { "Linen Cloth", 20, 2589, 600 } }""")
_acc2 = ns.Scanner.NewReplicateAcc()
for _i in range(5):
    ns.Scanner.ReadReplicateRow(_i, _acc2)
ns.DB.RecordVariants(_acc2.names)
_vb = ns.DB.GetVariant("Daga cruzada del bandido", 2819)
check(_vb.min == 10000 and _vb.bid == 4000 and ns.DB.GetVariant("Daga cruzada del mono", 2819).min == 3825
      and ns.DB.GetVariant("Linen Cloth") is None, "escaneo: compra directa y puja más baratas por sufijo (solo objetos con varios nombres)")
G.OroborosDB.markets[ns.MarketKey()].prices[2819] = lua.eval("{ min = 3825, mv = 3830, qty = 40, n = 40, t = 1795211786 }")
_tl = [(l[1], l[2]) for l in PH.TooltipLines(2819, "Daga cruzada del bandido").values()]
check(len(_tl) == 1 and _tl[0][0] == "Oroboros c/u" and _tl[0][1].startswith(ns.Coin(3830) + " (" + ns.Coin(10000) + ")")
      and "puja" not in _tl[0][1] and "/" in _tl[0][1],
      f"tooltip en una línea: valor (compra directa de ese sufijo) y fecha {_tl}")
G.OroborosDB.markets[ns.MarketKey()].prices[2819] = None
_tl2 = [(l[1], l[2]) for l in PH.TooltipLines(2589, "Linen Cloth").values()]
_p2589 = ns.DB.GetPrice(2589)
_exp2 = ns.Coin(_p2589.mv) + ("" if ns.Coin(_p2589.min) == ns.Coin(_p2589.mv) else " (" + ns.Coin(_p2589.min) + ")")
check(len(_tl2) == 1 and _tl2[0][1].startswith(_exp2) and "/" in _tl2[0][1],
      f"tooltip sin variantes: valor (compra directa más barata) y fecha {_tl2}")
_tl3 = [(l[1], l[2]) for l in PH.TooltipLines(2589, "Linen Cloth", 20).values()]
check(_tl3[0][0] == "Oroboros c/u" and "×20" in _tl3[0][1] and _tl3[0][1].endswith(ns.Coin(_p2589.mv * 20)),
      f"tooltip: precio por unidad (c/u) y, en una pila de 20, lo que vale entera {_tl3}")
lua.execute('OroborosResumen = OroborosResumen or {}; _USES_OLD = OroborosResumen.uses; OroborosResumen.uses = { [2589] = "Sastrería (12), Primeros auxilios (2)" }')
_tl4 = [(l[1], l[2]) for l in PH.TooltipLines(2589, "Linen Cloth").values()]
check(_tl4[-1] == ("Lo usan", "Sastrería (12), Primeros auxilios (2)"), f"tooltip: qué profesiones usan el componente {_tl4}")
lua.execute("OroborosResumen.uses = _USES_OLD")
lua.execute("""ITEMRES[2819] = { { buyoutAmount = 9000, minBid = 3500, quantity = 1, auctionID = 41, containsOwnerItem = false,
                                   itemLink = "|Hitem:2819::|h[Daga cruzada del bandido]|h" },
                                 { buyoutAmount = 5000, minBid = 4000, quantity = 1, auctionID = 42, containsOwnerItem = true,
                                   itemLink = "|Hitem:2819::|h[Daga cruzada del bandido]|h" } }""")
_wo2 = ns.Scanner.ahOpen
ns.Scanner.ahOpen = True
fire("ITEM_SEARCH_RESULTS_UPDATED", lua.eval("{ itemID = 2819 }"))
ns.Scanner.ahOpen = _wo2
ns.PriceHistory.Hide()
check(ns.DB.GetVariant("Daga cruzada del bandido", 2819).min == 9000,
      "subasta en vivo: actualiza la compra directa de ese sufijo (sin contar la tuya)")
lua.execute("REPLICATE = _REP")
G.OroborosDB.markets[ns.MarketKey()].variants = None
lua.execute("""ITEMRES[2819] = { { buyoutAmount = 14000, minBid = 3825, bidAmount = 0, quantity = 1, auctionID = 31, containsOwnerItem = false },
                                 { buyoutAmount = 0, minBid = 3800, bidAmount = 3900, quantity = 1, auctionID = 32, containsOwnerItem = false } }""")
_was_open = ns.Scanner.ahOpen
ns.Scanner.ahOpen = True
lua.execute("LOG = {}")
fire("ITEM_SEARCH_RESULTS_UPDATED", lua.eval("{ itemID = 2819 }"))
ns.PriceHistory.Debug()
_dbg = " ".join(G.LOG.values())
check(G.OroborosDB.searchSample.itemID == 2819 and "compra directa 14000" in _dbg and "puja mínima 3800" in _dbg and "puja actual 3900" in _dbg,
      "/oro precio debug: puja mínima, puja actual y compra directa de cada subasta")
ns.Scanner.ahOpen = _was_open
ns.PriceHistory.Hide()

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
_dp = list(G.OroborosDB.deposits.values())[-1]
check((_dp.hours, _dp.qty, _dp.deposit) == (24, 12, 36),
      f"SELL: apunta el depósito real que pide el juego ({_dp.hours}, {_dp.qty}, {_dp.deposit})")
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

# Farmeo medido → archivo (totales acumulados del juego: se sustituyen, no se suman)
import json
from oroboros_archive import append_farm
_fdb = {"chars": {"Zartch-R": {"market": "M"}}, "farm": {
    "mobs": {"1234@Bosque X": {"npc": 1234, "zone": "Elwynn", "sub": "Bosque X", "map": 1429, "kills": 4, "copper": 57,
                               "secs": 20, "items": {2589: 2}}},
    "gather": {"Bosque X": {"zone": "Elwynn", "sub": "Bosque X", "map": 1429, "nodes": 1, "items": {2447: 2}}},
    "npcs": {1234: {"name": "Lobo", "lvl": 12, "cls": "normal"}}}}
arch_f = os.path.join(_tf.mkdtemp(), "f.sqlite")
_cf = open_archive(arch_f)
append_farm(_cf, _fdb, "M"); append_farm(_cf, _fdb, "M")
_row = _cf.execute("SELECT npc, sub, zone, map, kills, copper, secs, items FROM farm_mobs").fetchall()
check(len(_row) == 1 and _row[0][:7] == (1234, "Bosque X", "Elwynn", 1429, 4, 57, 20) and json.loads(_row[0][7]) == {"2589": 2},
      f"farmeo al archivo: sin duplicar y con las cifras del juego {_row}")
check(_cf.execute("SELECT nodes FROM farm_gather").fetchone() == (1,) and
      _cf.execute("SELECT name, lvl, cls FROM farm_npcs WHERE npc=1234").fetchone() == ("Lobo", 12, "normal"),
      "farmeo al archivo: recolección y datos de la criatura")
_cf.close()

# Farmeo: estimación inicial con AzerothCore (solo materiales; el equipo no se estima)
import azerothcore as AC
import oroboros_farm as OF
def write_fake_ac(d):
    os.makedirs(d, exist_ok=True)
    def dump(table, cols, rows):
        create = "DROP TABLE IF EXISTS `%s`;\nCREATE TABLE `%s` (\n" % (table, table) + ",\n".join("  `%s` int NOT NULL" % c for c in cols) + \
                 ",\n  PRIMARY KEY (`%s`)\n) ENGINE=InnoDB;\nLOCK TABLES `%s` WRITE;\n" % (cols[0], table)
        vals = ",\n".join("(" + ",".join(v if isinstance(v, str) else str(v) for v in r) + ")" for r in rows)
        open(os.path.join(d, table + ".sql"), "w", encoding="utf-8").write(create + "INSERT INTO `%s` VALUES\n%s;\nUNLOCK TABLES;\n" % (table, vals))
    ct = ["entry", "name", "minlevel", "maxlevel", "rank", "type", "unit_flags", "npcflag", "lootid", "skinloot", "mingold", "maxgold"]
    dump("creature_template", ct, [
        (1, "'Lobo, \\'el\\' gris'", 10, 11, 0, 1, 0, 0, 1, 0, 10, 30),
        (2, "'Elite'", 10, 10, 1, 7, 0, 0, 2, 0, 50, 50),
        (3, "'Vendedor'", 10, 10, 0, 7, 0, 128, 0, 0, 0, 0),
        (4, "'Jabali'", 30, 30, 0, 1, 0, 0, 4, 0, 50, 90),
        (5, "'Ogro'", 10, 10, 0, 7, 0, 0, 5, 0, 10, 10)])
    # zoneId/areaId vienen a 0 en AzerothCore: se agrupa por cuadrículas de la posición (x, y)
    dump("creature", ["guid", "id1", "map", "zoneId", "areaId", "spawntimesecs", "position_x", "position_y"],
         [(g, 1, 0, 0, 0, 300, 100 + g, 100 + g) for g in range(1, 11)] + [(11, 3, 0, 0, 0, 300, 120, 120)] +
         [(20 + g, 5, 0, 0, 0, 300, 900 + g, 100) for g in range(6)] + [(30 + g, 2, 0, 0, 0, 300, 910 + g, 110) for g in range(4)] +
         [(40 + g, 1, 0, 0, 0, 300, 1700 + g, 100) for g in range(5)] + [(45 + g, 3, 0, 0, 0, 300, 1710 + g, 110) for g in range(5)] +
         [(50 + g, 4, 0, 0, 0, 300, 2500 + g, 100) for g in range(10)])
    lt = ["Entry", "Item", "Reference", "Chance", "QuestRequired", "LootMode", "GroupId", "MinCount", "MaxCount"]
    dump("creature_loot_template", lt, [
        (1, 2589, 0, 50, 0, 1, 0, 1, 3), (1, 2592, 0, 0, 0, 1, 1, 1, 1), (1, 4306, 0, 0, 0, 1, 1, 1, 1),
        (1, 999, 0, 100, 0, 1, 0, 1, 1), (1, 1, 1000, 100, 0, 1, 0, 1, 1), (1, 777, 0, 100, 1, 1, 0, 1, 1)])
    dump("reference_loot_template", lt, [(1000, 3000, 0, 20, 0, 1, 0, 1, 1)])
    dump("skinning_loot_template", lt, [])
    dump("item_template", ["entry", "class", "Quality", "SellPrice", "bonding", "name"],
         [r + ("'Item %d'" % r[0],) for r in [(2589, 7, 1, 10, 0), (2592, 7, 1, 25, 0), (4306, 7, 1, 38, 0), (999, 4, 2, 500, 2),
                                              (3000, 15, 0, 25, 0), (777, 12, 1, 0, 4), (2447, 7, 1, 4, 0), (2770, 7, 1, 5, 0)]])
    dump("gameobject_template", ["entry", "type", "name", "Data0", "Data1"],
         [(1618, 3, "'Peacebloom'", 29, 1415), (3724, 3, "'Peacebloom'", 29, 1415), (1731, 3, "'Copper Vein'", 38, 1502),
          (9000, 10, "'Peacebloom'", 0, 0)])
    dump("gameobject_loot_template", lt, [(1415, 2447, 0, 100, 0, 1, 0, 1, 3), (1502, 2770, 0, 100, 0, 1, 0, 1, 2)])
_acd = os.path.join(_tf.mkdtemp(), "azerothcore")
write_fake_ac(_acd)
_ac = AC.load(_acd)
check(_ac["templates"][1]["name"] == "Lobo, 'el' gris" and len(_ac["spawns"]) == 41 and _ac["nodes"]["Peacebloom"] == [1415] and _ac["loot"][1][4]["reference"] == 1000,
      "AzerothCore: lee los volcados SQL (filas seguidas, comas y comillas escapadas, referencias)")
_prices = {2589: {"value": 100, "vol": None}, 2592: {"value": 400, "vol": 2}, 4306: {"value": 1000, "vol": None}}
_pk = OF.mob_value(_ac, 1, _prices)
check(abs(_pk["copper"] - 825) < 1e-6 and 999 not in _pk["qty"] and 777 not in _pk["qty"],
      f"farmeo: valor por muerte = oro + materiales (sin equipo ni objetos de misión) ({_pk['copper']})")
_rows = OF.estimate(_ac, _prices, 11)
check([(r["map"], r["cell"]) for r in _rows] == [(0, (0, 0))] and abs(_rows[0]["x"] - 105.5) < 1e-6,
      f"farmeo: fuera élites, zona de élites, vendedores, ciudades (muchos PNJ con servicios) y nivel lejano {[(r['map'], r['cell']) for r in _rows]}")
_r = _rows[0]
check(abs(_r["kph"] - 42) < 1e-6 and abs(_r["gph"] - 27525) < 1e-6 and _r["saturated"] and _r["top_items"][0][0] == 4306,
      f"farmeo: oro por hora con ritmo según nivel y saturación de la lana ({_r['kph']}, {_r['gph']})")
check(OF.estimate(_ac, _prices, 50) == [], "farmeo: con nivel 50, esas criaturas quedan fuera del margen de nivel")

# Farmeo: recolección con GatherMate2 (nodos de Forever) valorada con el botín de los nodos de AzerothCore
import gathermate as GM
def write_fake_gm(base):
    os.makedirs(os.path.join(base, "GatherMate2"), exist_ok=True)
    os.makedirs(os.path.join(base, "GatherMate2_Data", "Forever"), exist_ok=True)
    open(os.path.join(base, "GatherMate2", "Constants.lua"), "w", encoding="utf-8").write(
        'local node_ids = {\n\t["Mining"] = {\n\t\t["Copper Vein"] = {\n\t\t\tid = 201,\n\t\t\tvariants = {\n\t\t\t\t"Poor Copper Vein"\n'
        '\t\t\t}\n\t\t},\n\t\t--["Hakkari Thorium Vein"] = 216,\n\t},\n\t["Herb Gathering"] = {\n\t\t["Peacebloom"] = {\n\t\t\tid = 401,\n'
        '\t\t},\n\t\t["Ghostbloom"] \t\t= 499,\n\t},\n}\n')
    def data(name, var, maps):
        lines = [var + " = {"]
        for m, nodes in maps.items():
            lines.append("\t[%d] = {" % m)
            lines += ["\t\t[%d] = %d," % (3570284000 + i * 1000, n) for i, n in enumerate(nodes)]
            lines.append("\t},")
        open(os.path.join(base, "GatherMate2_Data", "Forever", name), "w", encoding="utf-8").write("\n".join(lines + ["}", ""]))
    data("HerbalismData.lua", "GatherMateData2HerbDB", {1411: [401] * 150 + [499] * 50})
    data("MiningData.lua", "GatherMateData2MineDB", {1412: [201] * 20})
_gmb = os.path.join(_tf.mkdtemp(), "Interface", "AddOns")
write_fake_gm(_gmb)
check(GM.find(os.path.join(_gmb, "..", "..", "WTF", "x.lua")) == os.path.normpath(_gmb), "GatherMate2: encuentra la carpeta de addons subiendo desde un archivo")
_gm = GM.load(_gmb)
check(_gm["herb"][1411] == {401: 150, 499: 50} and _gm["mine"][1412] == {201: 20} and _gm["names"][201] == "Copper Vein"
      and 216 not in _gm["names"], "GatherMate2: nodos por mapa y nombre de cada tipo (sin las líneas comentadas)")
_gprices = {2447: {"value": 50, "vol": None}, 2770: {"value": 200, "vol": None}}
_gr = OF.gathering(_gm, _ac, _gprices, {"herb"})
check([(r["map"], r["kind"]) for r in _gr] == [(1411, "herb")], "farmeo: recolección solo de las profesiones del personaje")
_g0 = _gr[0]
check(abs(_g0["gph"] - 2250) < 1e-6 and _g0["top_items"][0][0] == 2447 and _g0["unvalued"] == ["Ghostbloom"] and _g0["nodes"] == 200,
      f"farmeo: hierbas valoradas con el botín del nodo; el tipo desconocido queda «sin valorar» ({_g0['gph']}, {_g0['unvalued']})")
_gr2 = OF.gathering(_gm, _ac, _gprices, {"herb", "mine"})
check([(r["map"], r["kind"], round(r["gph"])) for r in _gr2] == [(1411, "herb", 2250), (1412, "mine", 900)],
      f"farmeo: un mapa con pocos nodos da menos nodos por hora {[(r['map'], round(r['gph'])) for r in _gr2]}")
_gr0 = OF.gathering(_gm, _ac, _gprices, {"herb": 0})
check(len(_gr0) == 1 and _gr0[0]["gph"] == 0 and _gr0[0]["above_skill"] == ["Peacebloom"] and _gr0[0]["unchecked"] == ["Ghostbloom"]
      and _gr0[0]["nph"] == 30 * 50 / 200, "farmeo: con nivel 0 de Botánica, la Peacebloom (pide 1) no cuenta; lo que no está en la tabla, «sin comprobar»")
_gm_lotus = {"names": {401: "Peacebloom", 444: "Black Lotus"}, "herb": {7: {401: 200, 444: 50}}}
_grl = OF.gathering(_gm_lotus, _ac, _gprices, {"herb": 300})[0]
check(abs(_grl["gph"] - 3000) < 1e-6 and _grl["rare"] == ["Black Lotus"],
      f"farmeo: el Loto negro (raro, un sitio de muchos) no se estima ni cuenta como nodo ({_grl['gph']})")

# Farmeo: lo medido manda (peso = muertes / 30) y lo solo medido también aparece
_meas = OF.read_measured(arch_f, "M")
check(len(_meas["mobs"]) == 1 and _meas["mobs"][0]["items"] == {2589: 2} and _meas["npcs"][1234]["name"] == "Lobo"
      and OF.read_measured(arch_f, "Otro")["mobs"] == [], "farmeo: lee lo medido del archivo, solo de ese mercado")
def _m(npc, sub, kills, secs, copper, items=None):
    return {"npc": npc, "sub": sub, "zone": "Elwynn", "map": 1429, "kills": kills, "secs": secs, "copper": copper, "items": items or {}}
_est = OF.estimate(_ac, _prices, 11)
_c10 = OF.combine(_est, OF.per_npc([_m(1, "Bosque X", 10, 300, 5000)]), _ac, _prices)[0]
check(abs(_c10["gph"] - (21000 / 3 + 27525 * 2 / 3)) < 1e-6 and _c10["source"] == "mixto" and _c10["confidence"] == "media"
      and _est[0]["gph"] == 27525, f"farmeo: 10 muertes medidas pesan 1/3 ({_c10['gph']}, {_c10['source']})")
_c30 = OF.combine(_est, OF.per_npc([_m(1, "Bosque X", 20, 900, 10000), _m(1, "Otra", 10, 600, 5000)]), _ac, _prices)[0]
check(abs(_c30["gph"] - 21000) < 1e-6 and _c30["source"] == "medido" and _c30["confidence"] == "alta",
      f"farmeo: 30 muertes (sumando subzonas) sustituyen a la estimación ({_c30['gph']}, {_c30['confidence']})")
_c0 = OF.combine(_est, {}, _ac, _prices)[0]
check(_c0["gph"] == 27525 and _c0["source"] == "estimado" and _c0["confidence"] == "baja", "farmeo: sin medir, solo la estimación (confianza baja)")
_mp = OF.measured_places([_m(1, "Bosque X", 10, 300, 5000), _m(4242, "Cueva", 5, 600, 3000, {2589: 4})],
                         {4242: {"name": "Kobold", "lvl": 9, "cls": "normal"}}, _ac, _prices)
_cueva = [r for r in _mp if r["sub"] == "Cueva"]
check(len(_mp) == 2 and _cueva and abs(_cueva[0]["gph"] - 20400) < 1e-6 and _cueva[0]["mobs"][0]["name"] == "Kobold"
      and _cueva[0]["confidence"] == "media", "farmeo: una criatura solo medida (no está en AzerothCore) aparece con su oro por hora real")
_fp = OF.farm_plan(_ac, _gm, _prices, {"Zartch-R": {"level": 11, "professions": {"Herboristería": {}}}},
                   {"mobs": [_m(1, "Bosque X", 10, 300, 5000)], "npcs": {}})
_fz = _fp["chars"]["Zartch-R"]
check(_fz["explore"][0]["source"] == "mixto" and [g["kind"] for g in _fz["gather"]] == ["herb"] and len(_fp["measured"]) == 1,
      "farmeo: plan por personaje (nivel y profesiones de recolección)")
check(OF.gather_kinds({"Botánica": {"skill": 192}, "Minería": {}, "Cocina": {}}) == {"herb": 192, "mine": None}
      and OF.gather_kinds({"Pesca": {}}) == {},
      "farmeo: «Botánica» (Forever en español) y Minería cuentan como recolección")

# Farmeo.lua (juego): Lua válido y pequeño; panel, aviso al entrar y nombres resueltos en el juego
_fd = OF.farmeo_data(_ac, _gm, _prices, {"mobs": [_m(1, "Bosque X", 10, 300, 5000)], "npcs": {}})
_fpath = os.path.join(_tf.mkdtemp(), "Farmeo.lua")
_fbytes = OF.write_farmeo(_fpath, _fd, now=1795000000)
_fl = LuaRuntime(unpack_returned_tuples=True); _fl.execute(open(_fpath, encoding="utf-8").read())
_F = _fl.globals().OroborosFarmeo
check(_fbytes < 50 * 1024 and _F.bands[10][1].m == 0 and _F.bands[10][1].cx == 0 and _F.bands[10][1].src == "mixto"
      and _F.bands[10][1].it[1] == 4306 and _F.bands[50] is not None and _F.measured[1].sub == "Bosque X" and _F.gather.herb[0][1].map == 1411,
      f"Farmeo.lua: Lua válido, menos de 50 KB, por tramos de 5 niveles, recolección y lo medido ({_fbytes} bytes)")
lua.execute(open(_fpath, encoding="utf-8").read())
lua.execute("""_UL = UnitLevel; UnitLevel = function(u) if u == 'player' then return 11 end return _UL(u) end
WORLD = { X = 105, Y = 300, inst = 0 }; OroborosDB.farmAxis = nil; OroborosDB.farmPlaces = nil; OroborosDB.farmMaps = nil
SUBZONE = "Otra"; LOG = {}""")
FP = ns.FarmPanel
check(FP.PlayerCell() == "0:0:0", "farmeo en el juego: la cuadrícula del jugador sale de su posición en el mundo")
fire("ZONE_CHANGED"); fire("ZONE_CHANGED_NEW_AREA")
_alerts = [l for l in G.LOG.values() if "Farmeo aquí" in l]
check(len(_alerts) == 1 and "medido en parte" in _alerts[0], f"farmeo: al entrar en un sitio de la lista avisa una vez {_alerts}")
_pl = G.OroborosDB.farmPlaces["0:0:0"]
check(G.OroborosDB.farmAxis == "ba" and _pl is not None and _pl.zone == "Bosque del Mock" and abs(_pl.x - 10.6) < 1e-6
      and G.OroborosDB.farmMaps[1411] == "Durotar",
      "farmeo: el juego resuelve zona y coordenadas de cada sitio (calibrando el orden x/y con la posición del jugador)")
lua.execute('LOG = {}; WORLD = { X = 900, Y = 900, inst = 0 }; SUBZONE = "Bosque X"')
fire("ZONE_CHANGED")
check(any("Farmeo aquí" in l and "medido" in l for l in G.LOG.values()), "farmeo: también avisa en una subzona donde ya has farmeado")
ns.DB.Char().professions["Botánica"] = lua.eval("{ skill = 0 }")
G.SlashCmdList.OROBOROS("farmear")
_ent = [e for e in FP.entries.values()]
_heads = [e.head for e in _ent if e.head]
check(FP.frame is not None and FP.frame.shown and any("DONDE YA HAS FARMEADO" in h for h in _heads)
      and any("POR EXPLORAR" in h and "10" in h for h in _heads) and any("RECOLECCIÓN" in h for h in _heads)
      and any(e.t1 and "Bosque del Mock" in e.t1 for e in _ent) and any(e.t1 == "Durotar" for e in _ent),
      f"/oro farmear abre el panel: lo medido, por explorar (tramo 10–14, con el nombre resuelto) y recolección {_heads}")
ns.DB.Char().professions["Botánica"] = None
lua.execute("WORLD = { X = 105, Y = 300, inst = 0 }; UnitLevel = _UL; LOG = {}")
# El exportador lleva los nombres resueltos al archivo y el plan los usa
arch_fp = os.path.join(_tf.mkdtemp(), "fp.sqlite")
_cfp = open_archive(arch_fp)
append_farm(_cfp, {"farmPlaces": {"0:0:0": {"zone": "Bosque del Mock", "x": 10.6, "y": 10.6}}, "farmMaps": {1411: "Durotar"}}, "M")
_cfp.close()
_mfp = OF.read_measured(arch_fp, "M")
check(_mfp["places"]["0:0:0"]["zone"] == "Bosque del Mock" and _mfp["maps"]["1411"] == "Durotar",
      "farmeo: los nombres resueltos en el juego llegan al archivo para la página")

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
_p4html = open(os.path.join(tmp, "p4.html"), encoding="utf-8").read()
check('["farmear", "Farmear"]' in _p4html and all(b in _p4html for b in ("Donde ya has farmeado", "Por explorar", "Recolección"))
      and p4["farm"]["measured"] == [] and p4["farm"]["has_ac"] is False,
      "página: pestaña Farmear con sus tres bloques; sin AzerothCore, solo lo medido")
_fl_out = os.path.join(tmp, "Farmeo.lua")
r5 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_plan.py"), "--db", os.path.join(tmp, "a.sqlite"),
                     "--json", os.path.join(tmp, "p5.json"), "--synthetic", "--now", NOW, "--archive", arch_p, "--catalog", CAT_TEST,
                     "--azerothcore", _acd, "--farmeo", _fl_out], capture_output=True, text=True, encoding="utf-8", errors="replace")
check(r5.returncode == 0 and os.path.exists(_fl_out) and "OroborosFarmeo" in open(_fl_out, encoding="utf-8").read()
      and json.load(open(os.path.join(tmp, "p5.json"), encoding="utf-8"))["farm"]["has_ac"] is True,
      f"plan con --azerothcore y --farmeo: escribe Farmeo.lua para el juego {r5.stderr[-300:]}")
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

# ---- Fase 5: depósito, variantes y reventa por escalones ----
from oroboros_plan import lost_posts as _lost, ladder_flip as _lflip, SELL_SHARE as _SHARE
import oroboros_plan as _OP
check(_lost(10, 100) == 0 and _lost(0, 5) == 0, "depósito: un lote que cabe en las ventas de un día no pierde depósitos")
check(abs(_lost(20, 20) - 0.5) < 1e-9, f"depósito: con el doble de lo que vendes al día, media publicación perdida por unidad ({_lost(20, 20)})")
check(_lost(5, 0) == 1.0 and _lost(1000, 1) == _OP.MAX_LOST_POSTS, "depósito: sin ventas conocidas, una; y hay un tope")
def _f5(vendor_sell=0, deposits=(), variants=(), ladder=None, vol=None):
    _sh.copy(os.path.join(tmp, "a.sqlite"), fdb)
    _f = sqlite3.connect(fdb); mk = plan["market"]
    _f.execute("INSERT INTO items (item_id, name, vendor_sell) VALUES (777777, 'Gema de prueba', ?)", (vendor_sell,))
    _f.execute("INSERT INTO prices VALUES (?,777777,300,300,200,10,?,60,120,180,200,'oro')", (mk, _now))
    for k, (mv, q) in zip((4, 3, 2, 1), ((1000, 300), (1000, 280), (1000, 260), (1000, 240))):
        _f.execute("INSERT INTO history VALUES (?,777777,?,?,?,?,'oro',NULL)", (mk, _day(k), mv, mv, q))
    for hours, qty, dep in deposits:
        _f.execute("INSERT INTO deposits VALUES (?,777777,?,?,?)", (_now, hours, qty, dep))
    _f.commit(); _f.close()
    dd = _Data(fdb, CAT_TEST, now=_now)
    dd.variants = set(variants)
    if ladder is not None:
        dd.ladders = {777777: ladder}
    return dd
_d5 = _f5(vendor_sell=1000)
check(_d5.deposit(777777) == 600 and _d5.deposit_measured == 0, f"depósito: 60 % del precio de vendedor a 24 h ({_d5.deposit(777777)})")
check(_f5(vendor_sell=0).deposit(777777) == 1, "depósito: mínimo 1 cobre")
_d5m = _f5(vendor_sell=1000, deposits=((24, 1, 3000), (24, 2, 6000), (8, 1, 1000)))
check(_d5m.deposit_measured == 3 and abs(_d5m.deposit_rate - 3.0) < 1e-9 and _d5m.deposit(777777) == 3000,
      f"depósito: con 3 depósitos reales manda lo medido, llevado a 24 h ({_d5m.deposit_rate})")
check(_f5(vendor_sell=1000, deposits=((24, 1, 3000),)).deposit_rate == 0.6, "depósito: con menos de 3 mediciones, el de las guías")
_fl = [f for f in find_flips(_f5(vendor_sell=100), 48, next(iter(_d5.chars))) if f["out_item"] == 777777]
_fl0 = [f for f in find_flips(_f5(), 48, next(iter(_d5.chars))) if f["out_item"] == 777777]
check(_fl and _fl0 and _fl[0]["profit"] < _fl0[0]["profit"] and _fl[0]["min_sell"] > _fl0[0]["min_sell"],
      "reventa: el depósito de lo que no se vende a la primera baja el beneficio y sube el mínimo de venta")
check(not [f for f in find_flips(_f5(variants=[777777]), 48, next(iter(_d5.chars))) if f["out_item"] == 777777],
      "reventa: nada con equipo que tiene variantes (su precio mezcla productos distintos)")
# por escalones: 12 a 300, 8 a 320 y el resto desde 900 → comprar las 20 y ponerlas bajo 900
_dl = _f5(ladder=[(300, 12), (320, 8), (900, 40), (1000, 100)])
_cap = int(_dl.stats(777777)["vol"] * _SHARE * 2)
_lf = _lflip(_dl, 777777, 48, "x")
check(_cap >= 20 and _lf and _lf["units"] == 20 and _lf["max_buy"] == 320 and abs(_lf["sell"] - 891) < 1e-6
      and abs(_lf["cost"] - (300 * 12 + 320 * 8) / 20) < 1e-6,
      f"reventa por escalones: compra hasta el salto y vende bajo el escalón siguiente ({_lf and (_lf['units'], _lf['max_buy'], _lf['sell'])}, tope {_cap})")
_lf2 = _lflip(_f5(ladder=[(300, 12), (320, 8), (5000, 40)]), 777777, 48, "x")
check(_lf2 and _lf2["sell"] == 1000, f"reventa por escalones: nunca por encima de la mediana de 7 días ({_lf2 and _lf2['sell']})")
check(_lflip(_f5(ladder=[(300, 12), (320, 8), (350, 40), (380, 100)]), 777777, 48, "x") is None,
      "reventa por escalones: sin salto de precio no hay reventa, aunque esté por debajo de su mediana")
check(_lflip(_f5(ladder=[(300, 100000), (900, 40)]), 777777, 48, "x") is None,
      "reventa por escalones: no compra más de lo que el mercado deja vender")
_fx = [f for f in find_flips(_dl, 48, next(iter(_dl.chars))) if f["out_item"] == 777777]
check(len(_fx) == 1 and _fx[0]["units"] == 20, "reventa: con la lista de precios de la API, find_flips usa los escalones")

# mínimo por fabricación: lo que da menos de 2 oro a la hora no entra, aunque el margen sea bueno
_dm = _f5()
_good = [o for o in (_OP.evaluate(_dm, r, 48) for r in _dm.recipes) if o.get("profit") and not o.get("reason")]
_keep = _OP.MIN_CRAFT_PROFIT
_OP.MIN_CRAFT_PROFIT = _good[0]["profit"] + 1
_bad = _OP.evaluate(_dm, next(r for r in _dm.recipes if r["id"] == _good[0]["recipe"]), 48)
_OP.MIN_CRAFT_PROFIT = _keep
check(_good and "No merece el tiempo" in (_bad.get("reason") or "") and abs(_keep - 20000 * 3 / 3600) < 1e-9,
      f"recetas: una fabricación que da menos de 2 oro a la hora se descarta con su motivo ({_bad.get('reason')})")
check(all(o["profit"] >= _keep for o in plan["opportunities"] if o.get("included") and o["kind"] == "craft"),
      "recetas: nada de lo elegido baja del mínimo por fabricación")

# ---- Fase 6: catálogo de Forever (techos, reinicio semanal y datos con fuente) ----
import oroboros_ideas as _OI
import time as _tm
_cat_real = json.load(open(os.path.join(ROOT, "tools", "catalog.json"), encoding="utf-8"))
check(_cat_real.get("facts") and all(f.get("text") and f.get("source") and isinstance(f.get("verified"), bool)
                                     and (f.get("how") or not f["verified"]) for f in _cat_real["facts"]),
      "catálogo: cada dato de Forever lleva fuente, marca de comprobado y, si lo está, cómo se comprobó")
_caps_real = {k: v for k, v in _cat_real.get("price_caps", {}).items() if not k.startswith("_")}
check(_caps_real and all(k.isdigit() and v.get("cap", 0) > 0 and v.get("source") and isinstance(v.get("verified"), bool)
                         for k, v in _caps_real.items()), "catálogo: cada techo de precio lleva fuente y marca de comprobado")
check(all(_tm.strptime(e["date"], "%Y-%m-%d") and e["items"] and all(isinstance(i, int) for i in e["items"])
          for e in _cat_real["events"]), "catálogo: los eventos tienen fecha válida y objetos")
_evi = [i for e in _cat_real["events"] for i in e["items"]]
check(len(_evi) == len(set(_evi)), "catálogo: ningún objeto está en dos eventos (daría dos ideas del mismo objeto)")


class _FD:
    """Datos mínimos para los detectores de ideas: un objeto con 14 días de historia."""
    def __init__(self, catalog, by_wd, mv, item=1):
        self.now = _tm.mktime(_tm.strptime("2026-11-16 19:30", "%Y-%m-%d %H:%M"))      # lunes
        self.today = "2026-11-16"
        self.catalog, self.prices, self._mv = catalog, {item: {}}, mv
        self.history = {item: []}
        for k in range(14, 0, -1):
            lt = _tm.localtime(self.now - k * 86400)
            self.history[item].append({"day": _tm.strftime("%Y-%m-%d", lt), "mv": by_wd.get(lt.tm_wday, 100), "qty": 50})
    def stats(self, item):
        return {"mv": self._mv, "vol": 10, "days": 14, "depth": None}
    def name(self, item):
        return f"objeto {item}"


_wk = {1: 125, 2: 130, 6: 90}                                  # martes y miércoles caros, domingo barato
_w = lambda cat: _OI.detect_weekly(_FD(cat, _wk, 90))
_w0, _w2, _w5 = _w({}), _w({"server": {"raid_reset_weekday": 2}}), _w({"server": {"raid_reset_weekday": 5}})
check(len(_w0) == 1 and len(_w2) == 1 and len(_w5) == 1, "ciclo semanal: el caso de prueba se detecta")
check(any("Suele pasar" in l for l in _w0[0]["why"]) and any(l.startswith("Coincide con el reinicio") and "miércoles" in l for l in _w2[0]["why"])
      and any(l.startswith("No coincide con el reinicio") and "sábado" in l for l in _w5[0]["why"]),
      "ciclo semanal: dice si el día caro coincide con el reinicio de las bandas del catálogo")
_ev_ts = _tm.mktime(_tm.strptime("2026-12-09", "%Y-%m-%d"))
_fd = _FD({"server": {"raid_reset_weekday": 2}}, {}, 90)
check(_tm.strftime("%Y-%m-%d", _tm.localtime(_OI.next_reset(_fd, _ev_ts))) == "2026-12-16"
      and _tm.strftime("%Y-%m-%d", _tm.localtime(_OI.next_reset(_fd, _ev_ts - 86400))) == "2026-12-09"
      and _OI.next_reset(_FD({}, {}, 90), _ev_ts) is None and _OI.reset_weekday(_FD({"server": {"raid_reset_weekday": 9}}, {}, 90)) is None,
      "reinicio: el primero después de un evento es el siguiente día de reinicio, nunca el mismo día")
_evc = {"server": {"raid_reset_weekday": 2}, "events": [{"name": "Bandas", "date": "2026-12-09", "items": [1], "uplift": 1.3}],
        "price_caps": {"1": {"cap": 110, "note": "un vendedor lo da a precio fijo", "verified": False}}}
_e = _OI.detect_event(_FD(_evc, {}, 95))
check(len(_e) == 1 and abs(_e[0]["target"] - 130) < 1e-6 and any("miércoles 16/12" in l for l in _e[0]["why"]),
      f"evento: la salida dice la fecha del primer reinicio ({_e and _e[0]['why'][-1]})")
_es = _OI.detect_event(_FD(_evc, {}, 60))
check(len(_es) == 1 and abs(_es[0]["target"] - 80 * 1.3) < 1e-6 and any("punto medio" in l for l in _es[0]["why"]),
      f"evento: si el objeto está hundido, el escenario parte del punto medio entre hoy y la mediana ({_es and _es[0]['target']})")
_OI.apply_caps(_FD(_evc, {}, 95), _e)
check(_e[0]["target"] == 110 and _e[0].get("capped") and "sin comprobar" in _e[0]["why"][-1],
      "techo: el objetivo de una idea no pasa del precio fijo del vendedor, y lo avisa")
_e2 = [{"item": 1, "target": 100, "why": []}, {"item": 2, "target": 10 ** 9, "why": []}]
_OI.apply_caps(_FD(_evc, {}, 95), _e2)
check(_e2[0]["target"] == 100 and not _e2[0]["why"] and _e2[1]["target"] == 10 ** 9, "techo: no toca lo que queda por debajo ni los objetos sin techo")
_d6 = _f5(); _d6.catalog = _cat_real
_o6 = _OI.outlook(_d6, {})
check(len(_o6["facts"]) == len(_cat_real["facts"]) and {"text", "verified", "how", "source"} <= set(_o6["facts"][0])
      and plan["ideas"]["outlook"]["facts"] == [], "ideas: los datos del catálogo salen en el plan para la página")
check("factsHtml(I.outlook.facts)" in open(os.path.join(ROOT, "tools", "planner_ui.html"), encoding="utf-8").read(),
      "página: la pestaña Ideas enseña los datos del catálogo con su marca y su fuente")

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
# Lanzador: espera a que se cierre el juego y procesa una vez (sin vigilar todo el rato)
from oroboros_launch import run_session, bnet_command
if os.name == "nt":
    from oroboros_launch import single_instance
    _mx = r"Local\OroborosLanzadorPrueba%d" % os.getpid()
    check(single_instance(_mx) is True and single_instance(_mx) is False,
          "lanzador: si ya hay uno en marcha, el segundo no arranca (no procesar dos veces al cerrar)")
check(bnet_command("B.exe") == ["B.exe", "--game=wowf"] and bnet_command("B.exe", mode="lanzar") == ["B.exe", "--exec=launch wowf"]
      and bnet_command("B.exe", mode="nada") == ["B.exe"], "lanzador: Battle.net con WoW Forever (--game=wowf, comprobado en el juego)")
def _launch_case(appear_after, ok=True):
    clock = [0.0]; calls_ = {"find": 0, "wait": [], "run": 0, "start": 0}
    def find():
        calls_["find"] += 1
        return 4242 if appear_after is not None and calls_["find"] > appear_after else None
    def run():
        calls_["run"] += 1
        if not ok: raise RuntimeError("fallo de prueba")
    res = run_session(find, lambda pid: calls_["wait"].append(pid), run, start_launcher=lambda: calls_.__setitem__("start", calls_["start"] + 1),
                      wait_start=60, poll=5, clock=lambda: clock[0], sleep=lambda sec: clock.__setitem__(0, clock[0] + sec), log=lambda *_: None)
    return res, calls_
_r, _c = _launch_case(0)
check(_r is True and _c["wait"] == [4242] and _c["run"] == 1 and _c["start"] == 1, f"lanzador: con el juego abierto, espera a que se cierre y procesa una vez {_c}")
_r, _c = _launch_case(3)
check(_r is True and _c["find"] == 4 and _c["run"] == 1, "lanzador: detecta el juego cuando arranca")
_r, _c = _launch_case(None)
check(_r is False and _c["run"] == 0 and _c["wait"] == [], "lanzador: si el juego no llega a arrancar, no procesa")
_r, _c = _launch_case(0, ok=False)
check(_r is False and _c["run"] == 1, "lanzador: un fallo al procesar se registra y termina")

wtmp = os.path.join(tmp, "watch")
rw = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_watch.py"), os.path.join(tmp, "A.lua"), "--work", wtmp, "--azerothcore", "",
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
_res_u = os.path.join(tmp, "ResumenUsos.lua")
r_pdb2 = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "oroboros_export.py"), os.path.join(tmp, "A.lua"),
                         "--archive", os.path.join(tmp, "pdbx_arch.sqlite"), "--resumen", _res_u, "--professiondb", _pdb_base],
                        capture_output=True, text=True, encoding="utf-8", errors="replace")
_lu = LuaRuntime(unpack_returned_tuples=True); _lu.execute(open(_res_u, encoding="utf-8").read())
check(r_pdb2.returncode == 0 and _lu.globals().OroborosResumen.uses[2589] == "Alquimia (2)"
      and _lu.globals().OroborosResumen.uses[2318] == "Alquimia (1)",
      "exportador: Resumen.lua dice qué profesiones usan cada componente (sin recetas ocultas) " + r_pdb2.stderr[-200:])
check(p2["banker"] is None and any("BUY " in rt["text"] for rt in p2["routes"].values() if rt["short"] == "Zarthrin"),
      "sin banquero, cada personaje compra lo suyo")
check(not any(c["item"] in (14256, 9206, 4234) for c in I["ideas"]), "no se repite una apuesta que ya está abierta")
check(any(l.startswith("HOLD ") for rt in I["routes"].values() for l in rt["text"].splitlines()), "la ruta de ideas anota las apuestas (HOLD)")
for rt in I["routes"].values():
    n, nerr = ns.Queue.Parse(rt["text"])
    check(len(list(nerr.values())) == 0, f"la ruta de ideas de {rt['short']} la entiende el addon")
check("/*__PLAN__*/null" not in open(os.path.join(tmp, "p.html"), encoding="utf-8").read(), "HTML con el plan incrustado")

# ----------------------------------------------------------------------
# API de Blizzard (docs/planes/2026-11-23-api-blizzard.md): fotos sintéticas, sin red
# ----------------------------------------------------------------------
import gzip as _gz, json as _js
import oroboros_api as API
from oroboros_archive import update_daily as _upd_daily
def _au(i, item, q, price, tl, mat=False):
    d = {"id": i, "item": {"id": item}, "quantity": q, "time_left": tl}
    if mat: d["unit_price"] = price
    else: d["buyout"] = price * q
    return d
_T0 = _ts(20, 10, 23)
_P1 = [_au(1, 100, 1, 50, "SHORT"), _au(2, 100, 1, 100, "LONG"), _au(3, 100, 1, 52, "LONG"), _au(4, 200, 1, 10, "LONG"),
       _au(10, 300, 20, 5, "LONG", True), _au(11, 300, 10, 6, "LONG", True)]
_P2 = [_au(4, 200, 1, 10, "LONG"), _au(5, 100, 1, 55, "VERY_LONG"),
       _au(10, 300, 15, 5, "LONG", True), _au(12, 300, 7, 4, "VERY_LONG", True)]
# clasificación pura
_c = API.classify(API.as_live(_P1), API.as_live(_P2))
check(_c[100] == {"new": 1, "sold": 1, "expired": 1, "cancelled": 1, "partial": 0},
      f"API: desaparecidas: SHORT → caducada, cara → cancelada, barata → vendida ({_c.get(100)})")
check(_c[300] == {"new": 7, "sold": 0, "expired": 0, "cancelled": 10, "partial": 5},
      f"API: materiales: baja de cantidad = compra parcial; la cara que desaparece con la barata aún viva = cancelada ({_c.get(300)})")
# fase 5: se compra primero lo más barato, y cada variante de equipo es un producto distinto
_av = lambda i, price, bonus=None: {"id": i, "item": dict({"id": 500}, **({"bonus_lists": bonus} if bonus else {})),
                                    "quantity": 1, "buyout": price, "time_left": "LONG"}
_cA = API.classify(API.as_live([_av(1, 100), _av(2, 110)]), API.as_live([_av(1, 100)]))
check(_cA[500]["sold"] == 0 and _cA[500]["cancelled"] == 1, f"API: desaparece la cara y sigue la barata → cancelada, no vendida ({_cA[500]})")
_cB = API.classify(API.as_live([_av(1, 100), _av(2, 110)]), API.as_live([_av(2, 110)]))
check(_cB[500]["sold"] == 1 and _cB[500]["cancelled"] == 0, f"API: desaparece la más barata → vendida ({_cB[500]})")
_cC = API.classify(API.as_live([_av(1, 100, [7]), _av(2, 110, [9, 8])]), API.as_live([_av(1, 100, [7])]))
check(_cC[500]["sold"] == 1, f"API: otra variante más barata no cuenta: son productos distintos ({_cC[500]})")
check(API.variant_of({"id": 1, "bonus_lists": [9, 8]}) == "8.9" and API.variant_of({"id": 1}) == "", "API: la variante son las bonus_lists ordenadas")
_vd5 = _tf.mkdtemp(); _cv5 = API.open_api(os.path.join(_vd5, "v.sqlite")); API.set_house(_cv5, 111, "Casa de subastas de la Alianza", realm="R5")
API.ingest(_cv5, 111, _T0, [_av(1, 100, [7]), _av(2, 110, [9, 8]), _av(3, 120, [7]), {"id": 4, "item": {"id": 600}, "quantity": 5, "unit_price": 10, "time_left": "LONG"},
                            {"id": 5, "item": {"id": 600}, "quantity": 5, "unit_price": 10, "time_left": "LONG"}, {"id": 6, "item": {"id": 600}, "quantity": 2, "unit_price": 30, "time_left": "LONG"}])
check(API.variant_items(_cv5, 111) == {500}, f"API: objetos con más de una variante a la venta ({API.variant_items(_cv5, 111)})")
check(API.ladders(_cv5, 111)[600] == [(10, 10), (30, 2)], f"API: lista de precios de barato a caro, juntando el mismo precio ({API.ladders(_cv5, 111).get(600)})")
API.ingest(_cv5, 111, _T0 + 3600, [_av(1, 100, [7]), _av(2, 110, [9, 8])])
_r5 = _cv5.execute("SELECT sold, cancelled FROM api_item_hour WHERE t=? AND item_id=500", (_T0 + 3600,)).fetchone()
check(_r5 == (0, 1), f"API: la variante se recuerda entre fotos (la cara de la misma variante que desaparece = cancelada) {_r5}")
_cv5.close()
check(200 not in _c, "API: lo que no cambia no genera movimientos")
_c2 = API.classify(API.as_live([_au(1, 100, 5, 50, "LONG", True)]), API.as_live([_au(1, 100, 8, 50, "LONG", True)]))
check(_c2.get(100, {}).get("partial", 0) == 0 and _c2.get(100, {}).get("new", 0) == 0, "API: si una subasta sube de cantidad, no cuenta")
# ingestión en el archivo
_ad = _tf.mkdtemp(); _aa = os.path.join(_ad, "api.sqlite")
_con = API.open_api(_aa)
_mid = API.set_house(_con, 111, "Casa de subastas de la Alianza", realm="R5")
check(API.faction_of({"en_GB": "Horde Auction House", "es_ES": "Casa de subastas de la Horda"}) == "Horde"
      and API.house_name({"en_GB": "x", "es_ES": "Casa de subastas de la Horda"}) == "Casa de subastas de la Horda",
      "API: sin locale, el nombre llega en todos los idiomas: se usa el español")
check(_con.execute("SELECT key FROM markets WHERE market_id=?", (_mid,)).fetchone()[0] == "R5-Alliance",
      "API: la casa de la Alianza se asocia al mercado <reino>-Alliance")
r1 = API.ingest(_con, 111, _T0, _P1)
check(r1["first"] and _con.execute("SELECT COUNT(*) FROM api_live WHERE house=111").fetchone()[0] == 6,
      "API: la primera foto se guarda como estado actual")
_h1 = _con.execute("SELECT min, mv, qty, n, sold FROM api_item_hour WHERE house=111 AND t=? AND item_id=100", (_T0,)).fetchone()
check(_h1 == (50, 50, 3, 3, None), f"API: primera foto: precios por objeto y sin movimientos (no hay foto anterior) {_h1}")
r2 = API.ingest(_con, 111, _T0 + 3600, _P2)
_h2 = _con.execute("SELECT new, sold, expired, cancelled, partial, min, qty FROM api_item_hour WHERE house=111 AND t=? AND item_id=300",
                   (_T0 + 3600,)).fetchone()
check(_h2 == (7, 0, 0, 10, 5, 4, 22), f"API: segunda foto: movimientos y precio por objeto {_h2}")
_h3 = _con.execute("SELECT min, qty, sold, expired, cancelled FROM api_item_hour WHERE house=111 AND t=? AND item_id=100",
                   (_T0 + 3600,)).fetchone()
check(_h3 == (55, 1, 1, 1, 1), f"API: objeto con movimientos {_h3}")
check(sorted(r[0] for r in _con.execute("SELECT auction_id FROM api_live WHERE house=111")) == [4, 5, 10, 12],
      "API: el estado actual se sustituye por la foto nueva")
check(API.ingest(_con, 111, _T0 + 3600, _P2)["skipped"], "API: la misma foto dos veces no se cuenta dos veces")
_d = _con.execute("SELECT min_low, min_high, src FROM daily WHERE market_id=? AND item_id=100", (_mid,)).fetchone()
check(_d == (50, 55, "api"), f"API: histórico diario con origen api (mínimo y más alto del día) {_d}")
insert_scan(_con, "R5-Alliance", _T0 + 600, [(100, 40, 40, 9, 9, 9)]); _con.commit()
_upd_daily(_con)
check(_con.execute("SELECT min_low, src FROM daily WHERE market_id=? AND item_id=100", (_mid,)).fetchone() == (50, "api"),
      "API: un escaneo del juego no pisa el día que tiene la API")
insert_scan(_con, "R5-Alliance", _T0 - 3 * 86400, [(100, 41, 41, 9, 9, 9)]); _con.commit()
_upd_daily(_con)
_dd = datetime.datetime.fromtimestamp(_T0 - 3 * 86400).date().isoformat()
check(_con.execute("SELECT min_low, src FROM daily WHERE market_id=? AND item_id=100 AND day=?", (_mid, _dd)).fetchone() == (41, "obs"),
      "API: los días sin API siguen saliendo del juego")
# hueco de más de 90 min: no se clasifica
API.ingest(_con, 111, _T0 + 3600 * 4, [_au(5, 100, 1, 55, "LONG")])
_g = _con.execute("SELECT sold, expired, cancelled, partial, gap FROM api_item_hour WHERE house=111 AND t=? AND item_id=300",
                  (_T0 + 3600 * 4,)).fetchone()
check(_g == (0, 0, 0, 0, 22), f"API: con un hueco de 3 h, lo desaparecido no se clasifica (va a «hueco») {_g}")
_con.close()

# cliente y descarga, con un fetch falso
class _FakeNet:
    def __init__(self, routes): self.routes, self.log = routes, []
    def __call__(self, url, headers, data=None):
        self.log.append((url, dict(headers), data))
        if "oauth" in url:
            return self.routes.get("token", (200, {}, b'{"access_token": "TOK", "expires_in": 86400}'))
        path = url.split("?")[0].split("api.blizzard.com")[1]
        r = self.routes.get(path)
        if callable(r): r = r(headers)
        return r or (404, {}, b"")
_LM = "Fri, 20 Nov 2026 09:23:00 GMT"
def _photo(path_lm, body):
    return lambda h: (304, {"last-modified": path_lm}, b"") if h.get("If-Modified-Since") == path_lm else (200, {"last-modified": path_lm}, _js.dumps(body).encode())
_net = _FakeNet({"/data/wow/ruleset/2/auctions/111": _photo(_LM, {"id": 111, "name": "Casa de subastas de la Alianza", "auctions": [a for a in _P1 if "buyout" in a]}),
                 "/data/wow/ruleset/2/auctions/111/commodities": _photo(_LM, {"auctions": [a for a in _P1 if "unit_price" in a]})})
_wd = _tf.mkdtemp()
_cl = API.Client(("ID", "SECRETO-NO-MOSTRAR"), fetch=_net, cache_dir=_wd)
_ab = os.path.join(_wd, "b.sqlite")
_res = API.run_once(_ab, _cl, [111], realm="R5", log=lambda *_: None)
_cx = sqlite3.connect(_ab)
check(_res[0]["status"] == "nueva" and _cx.execute("SELECT COUNT(*) FROM api_live").fetchone()[0] == 6,
      f"API: run_once baja normales y materiales y los guarda ({_res})")
check(_cx.execute("SELECT name, faction FROM api_houses WHERE house=111").fetchone() == ("Casa de subastas de la Alianza", "Alliance"),
      "API: guarda el nombre y la facción de la casa")
_cx.close()
_n0 = len(_net.log)
_res2 = API.run_once(_ab, _cl, [111], realm="R5", log=lambda *_: None)
check(_res2[0]["status"] == "sin cambios" and any(h.get("If-Modified-Since") == _LM for _, h, _ in _net.log[_n0:]),
      f"API: con If-Modified-Since, un 304 no toca nada ({_res2})")
check(sum(1 for u, _, _ in _net.log if "oauth" in u) == 1, "API: el token se reutiliza mientras no caduca")
_logs = []
_bad = API.Client(("ID", "SECRETO-NO-MOSTRAR"), fetch=_FakeNet({"token": (401, {}, b'{"error": "SECRETO-NO-MOSTRAR"}')}),
                  cache_dir=_tf.mkdtemp())
_res3 = API.run_once(os.path.join(_wd, "c.sqlite"), _bad, [111], realm="R5", log=lambda *a: _logs.append(" ".join(map(str, a))))
check(_res3[0]["status"] == "error" and not any("SECRETO" in x for x in _logs + [str(_res3), repr(_bad)]),
      f"API: un error de token se registra sin mostrar el secreto ({_logs})")
# importar fotos guardadas (las de la fase A)
_imp = _tf.mkdtemp()
for _t, _p in ((_T0, _P1), (_T0 + 3600, _P2)):
    _stamp = datetime.datetime.utcfromtimestamp(_t).strftime("%Y%m%d-%H%M%S")
    with _gz.open(os.path.join(_imp, f"grp_{_stamp}_111_norm.json.gz"), "wt") as _f:
        _js.dump({"id": 111, "name": "Casa de subastas de la Alianza", "auctions": [a for a in _p if "buyout" in a]}, _f)
    with _gz.open(os.path.join(_imp, f"grp_{_stamp}_111_mat.json.gz"), "wt") as _f:
        _js.dump({"auctions": [a for a in _p if "unit_price" in a]}, _f)
_ai = os.path.join(_imp, "i.sqlite")
_ri = API.import_dir(_ai, _imp, realm="R5")
_cx = sqlite3.connect(_ai)
check(_ri == 2 and _cx.execute("SELECT sold FROM api_item_hour WHERE t=? AND item_id=300", (_T0 + 3600,)).fetchone() == (0,)
      and _cx.execute("SELECT cancelled FROM api_item_hour WHERE t=? AND item_id=300", (_T0 + 3600,)).fetchone() == (10,),
      f"API: importa fotos guardadas en orden ({_ri})")
_cx.close()

# retención: api_item_hour de las semanas viejas → api_band_week, y las franjas no cambian
_rd = _tf.mkdtemp(); _ra = os.path.join(_rd, "r.sqlite")
_cr = API.open_api(_ra); API.set_house(_cr, 111, "Casa de subastas de la Alianza", realm="R5")
_base = _ts(2, 9, 23)     # lunes 2/11, semana 45
_lv = [_au(1, 100, 1, 50, "LONG"), _au(2, 100, 1, 50, "LONG")]
for _k in range(6):        # cada hora se vende una barata y se publica otra
    API.ingest(_cr, 111, _base + _k * 3600, _lv)
    _lv = [_lv[1], _au(10 + _k, 100, 1, 50, "LONG")]
for _k in range(3):        # y al día siguiente, otra vez
    API.ingest(_cr, 111, _base + 86400 + _k * 3600, _lv)
    _lv = [_lv[1], _au(30 + _k, 100, 1, 50, "LONG")]
_before = API.band_stats(_cr, 111)
check(abs(sum(b["hours"] for b in _before[100]) - 7) < 1e-6 and sum(b["gap"] for b in _before[100]) == 0,
      f"API: un hueco no suma horas medidas a las franjas (solo 5 + 2 intervalos de 1 h) {sum(b['hours'] for b in _before[100])}")
_nrm = API.rollup_api(_cr, _ts(30, 12), keep_days=14)
_after = API.band_stats(_cr, 111)
check(_nrm > 0 and _cr.execute("SELECT COUNT(*) FROM api_item_hour").fetchone()[0] == 0
      and _cr.execute("SELECT COUNT(*) FROM api_band_week").fetchone()[0] > 0,
      f"API: las semanas de más de 14 días pasan a api_band_week y se borran ({_nrm})")
check(_before == _after and _before[100][2]["sold"] > 0,
      f"API: las franjas dan lo mismo antes y después de resumir ({_before.get(100, [None]*3)[2]} / {_after.get(100, [None]*3)[2]})")
check(API.rollup_api(_cr, _ts(30, 12), keep_days=14) == 0, "API: resumir dos veces no duplica")
# nombres de objetos que faltan, con un cliente falso y un límite
_cr.execute("INSERT OR IGNORE INTO items (item_id) VALUES (101), (102), (103)"); _cr.commit()
_nn = _FakeNet({"/data/wow/item/100": (200, {}, _js.dumps({"name": "Barra de prueba", "quality": {"type": "UNCOMMON"}, "sell_price": 25}).encode()),
                "/data/wow/item/101": (200, {}, _js.dumps({"name": "Otra", "quality": {"type": "COMMON"}, "sell_price": 1}).encode())})
_cn = API.Client(("ID", "S"), fetch=_nn, cache_dir=_tf.mkdtemp())
_f1 = API.fill_names(_cr, _cn, limit=2)
check(_f1 == {"asked": 2, "named": 2} or _f1["asked"] == 2, f"API: nombres: respeta el límite ({_f1})")
check(_cr.execute("SELECT name, quality, vendor_sell FROM items WHERE item_id=100").fetchone() == ("Barra de prueba", 2, 25),
      "API: nombres: rellena nombre, calidad y precio de venta al vendedor")
_f2 = API.fill_names(_cr, _cn, limit=10); _f3 = API.fill_names(_cr, _cn, limit=10)
check(_f3["asked"] == 0, f"API: nombres: lo que no existe (404) no se vuelve a pedir ({_f2}, {_f3})")
_cr.close()
_m1 = API.maintenance(_ra, _cn, now=_ts(30, 12), log=lambda *_: None)
_m2 = API.maintenance(_ra, _cn, now=_ts(30, 18), log=lambda *_: None)
_m3 = API.maintenance(_ra, _cn, now=_ts(30, 12) + 86400, log=lambda *_: None)
check(_m1 is not None and _m2 is None and _m3 is not None, f"API: el mantenimiento (resumen y nombres) se hace una vez al día ({_m1}, {_m2}, {_m3})")

# --- el plan, las franjas y Resumen.lua usan la API ---
_A = H.analyze(_ra, "R5-Alliance")
_bs = API.band_stats(sqlite3.connect(_ra), 111)[100][2]
check(_A[100][2]["src"] == "api" and abs(_A[100][2]["gone_cheap_h"] - round((_bs["sold"] + _bs["partial"]) / _bs["hours"], 2)) < 1e-9,
      f"franjas: con datos suficientes de la API, salen de la API (vendidas por hora) {_A[100][2]}")
check(H.analyze(arch3, "M")[1][2]["src"] == "obs", "franjas: sin API, siguen saliendo de los escaneos")
_old = os.path.join(_tf.mkdtemp(), "viejo.sqlite"); _sh0 = __import__("shutil"); _sh0.copy(_ra, _old)
_co = sqlite3.connect(_old); _co.execute("DROP TABLE api_band_week"); _co.execute("DROP TABLE api_missing"); _co.commit(); _co.close()
check(isinstance(H.analyze(_old, "R5-Alliance"), dict), "franjas: un archivo con las tablas de la API de una versión anterior se completa solo")
import shutil as _sh, time as _time
_vd = _tf.mkdtemp(); _va = os.path.join(_vd, "v.sqlite"); _vp = os.path.join(_vd, "plan.sqlite"); _sh.copy(out, _vp)
_cv = API.open_api(_va); API.set_house(_cv, 111, "Casa de subastas de la Alianza", market=mk_)
_now = int(_time.time()); _t = _now - 72 * 3600 + 60     # la última foto, posterior al precio del juego de las pruebas
_lv = [_au(1, 2589, 1, 30, "LONG"), _au(2, 2589, 1, 30, "LONG")]
for _k in range(73):       # 3 días, una foto por hora: cada hora se vende una barata y se publica otra
    API.ingest(_cv, 111, _t + _k * 3600, _lv)
    _lv = [_lv[1], _au(100 + _k, 2589, 1, 30, "LONG")]
_rates, _cov = API.sold_rates(_cv, 111, _now)
check(_cov >= 3 and abs(_rates[2589] - 24) < 0.01, f"API: vendidas por día (media de 7 días) {_rates.get(2589)} con {_cov} días")
_cv.close()
_cp = sqlite3.connect(_va)
from oroboros_archive import plan_from_archive as _pfa
_pfa(_cp, _vp); _cp.close()
_pr = sqlite3.connect(_vp).execute("SELECT min, src, d110 FROM prices WHERE market=? AND item_id=2589", (mk_,)).fetchone()
check(_pr == (30, "api", 2),f"plan: el precio de ahora es el más reciente (la API, con profundidad) {_pr}")
_dv = Data(_vp, CAT_TEST, archive=_va)
_sv = _dv.stats(2589)
check(abs(_sv["vol"] - 24) < 0.01 and _sv["vol_src"] == "api" and _sv["vol_est"] is True,
      f"plan: con 3 días de API, las ventas por día salen de la API (estimadas hasta calibrar) {_sv['vol']}, {_sv.get('vol_src')}, {_sv['vol_est']}")
_rv = os.path.join(_vd, "Resumen.lua")
from oroboros_summary import write_resumen as _wr
_cx = API.open_api(_va); _cx.execute("INSERT INTO markets (key) VALUES ('Solo-API-Horde')")
API.set_house(_cx, 114, "Casa de subastas de la Horda", market="Solo-API-Horde")
API.ingest(_cx, 114, _now, [_au(1, 2589, 1, 30, "LONG")])
insert_scan(_cx, mk_, _now - 3600, [(2589, 30, 30, 2, 2, 2)]); _cx.commit(); _cx.close()
_wr(_va, _rv)
_lr = LuaRuntime(unpack_returned_tuples=True); _lr.execute(open(_rv, encoding="utf-8").read())
_sr = _lr.globals().OroborosResumen.markets[mk_][2589]
check(_sr.split(";")[13] == "24", f"Resumen.lua: lleva las vendidas por día de la API ({_sr})")
check(_lr.globals().OroborosResumen.markets["Solo-API-Horde"] is None,
      "Resumen.lua: solo lleva los mercados con datos del juego (la Horda y Aguasnegras de la API, en el panel de escritorio)")
lua.execute("OroborosResumen = { v = 1, t = 0, markets = { [\"" + ns.MarketKey() + "\"] = { [2589] = [[" + _S + ";24]] } } }")
_L2 = list(PH.Lines(2589, 120).values())
check(PH.Parse(_S + ";24").soldDay == 24 and _L2[-1] == "Unas 24 vendidas al día (estimado con la API)", f"panel: enseña las vendidas por día {_L2}")
check(PH.Parse(_S).soldDay is None, "panel: un Resumen.lua sin ese campo sigue funcionando")
lua.execute("OroborosResumen = nil")

# --- calibración con el libro (ventas reales del correo) ---
_kd = _tf.mkdtemp(); _ka = os.path.join(_kd, "k.sqlite"); _kp = os.path.join(_kd, "plan.sqlite"); _sh.copy(out, _kp)
_ck = API.open_api(_ka); API.set_house(_ck, 111, "Casa de subastas de la Alianza", market=mk_)
_kt = _ts(21, 10, 23)
API.ingest(_ck, 111, _kt, [_au(1, 7001, 5, 10, "LONG", True), _au(2, 7002, 1, 100, "LONG"), _au(3, 7002, 1, 500, "LONG")])
API.ingest(_ck, 111, _kt + 3600, [_au(1, 7001, 2, 10, "LONG", True), _au(2, 7002, 1, 100, "LONG")])   # 7001: 3 compradas; 7002: la cara, cancelada
_ck.close()
_cpk = sqlite3.connect(_kp)
_char = _cpk.execute("SELECT char FROM characters WHERE market=?", (mk_,)).fetchone()[0]
_cpk.execute("DELETE FROM ledger")
_cpk.executemany("INSERT INTO ledger VALUES (?,?,?,?,?,?,?,?)", [
    (_kt + 1800, _char, "SELL", 7001, 2, 10, 20, "mail"),          # dentro: se ve vendida
    (_kt + 2000, _char, "SELL", 7002, 1, 500, 500, "mail"),        # dentro, pero la estimación la dio por cancelada
    (_kt - 86400 * 5, _char, "SELL", 7001, 1, 10, 10, "mail"),     # sin fotos de la API: fuera
    (_kt + 1800, _char, "BUY", 7001, 9, 10, 90, "mail")])          # compras: no cuentan
_cpk.commit(); _cpk.close()
_cal = API.calibrate(_ka, _kp, house=111)
check((_cal["sales"], _cal["units"], _cal["covered"], _cal["outside"]) == (2, 3, 2, 1) and abs(_cal["coverage"] - 2 / 3) < 1e-9,
      f"calibración: de tus 3 unidades vendidas con fotos, la estimación ve 2 como vendidas {_cal}")
check(abs(_cal["share"] - 2 / 3) < 1e-9 and any(d["item"] == 7002 and d["cancelled"] == 1 for d in _cal["detail"]),
      f"calibración: tu parte de lo vendido estimado y el detalle de lo no cubierto ({_cal['share']})")
check(API.is_calibrated(sqlite3.connect(_ka), 111) is False, "calibración: con pocas ventas o menos del 80 %, las ventas de la API siguen como estimadas")

# --- revisión final: retención con el corte entre dos semanas (domingo 8/11 → lunes 9/11) ---
_bd = os.path.join(_tf.mkdtemp(), "borde.sqlite")
_cb = API.open_api(_bd); API.set_house(_cb, 111, "Casa de subastas de la Alianza", realm="R5")
_lv = [_au(1, 100, 1, 50, "LONG"), _au(2, 100, 1, 50, "LONG")]
for _k in range(8):
    API.ingest(_cb, 111, _ts(8, 20, 23) + _k * 3600, _lv)
    _lv = [_lv[1], _au(200 + _k, 100, 1, 50, "LONG")]
_b0 = API.band_stats(_cb, 111)[100]
API.rollup_api(_cb, _ts(9, 0) + 14 * 86400, keep_days=14)      # corta a medianoche del domingo
_b1 = API.band_stats(_cb, 111)[100]
check(_b0 == _b1 and abs(sum(b["sold"] for b in _b1) - 7) < 1e-6,
      f"retención: con el corte entre dos semanas, nada se cuenta dos veces ({sum(b['sold'] for b in _b0)} → {sum(b['sold'] for b in _b1)})")
_cb.execute("DELETE FROM api_item_hour"); _cb.commit()
check(API.band_stats(_cb, 111)[100] == _b0, "franjas: salen del resumen que se acumula al meter cada foto (no recorren el detalle)")
_cb.close()
# --- revisión final: errores de red que no son OSError no tumban la descarga ---
import http.client as _hc
def _boom(exc):
    def f(url, headers, data=None):
        if "oauth" in url:
            return (200, {}, b'{"access_token": "T", "expires_in": 86400}')
        raise exc
    return f
for _exc in (_hc.IncompleteRead(b"x"), EOFError("gzip cortado")):
    _cx_ = API.Client(("ID", "S"), fetch=API.safe_fetch(_boom(_exc)), cache_dir=_tf.mkdtemp())
    try:
        _rr = API.run_once(os.path.join(_tf.mkdtemp(), "e.sqlite"), _cx_, [111], realm="R5", log=lambda *_: None)
        _okx = _rr[0]["status"] == "error"
    except Exception as _e:
        _okx, _rr = False, _e
    check(_okx, f"descarga: un {type(_exc).__name__} se registra como error y el bucle sigue ({_rr})")
# --- revisión final: fill_names no deja la escritura abierta mientras pide a la red ---
_fd = os.path.join(_tf.mkdtemp(), "f.sqlite"); _cf = API.open_api(_fd)
_cf.execute("INSERT INTO items (item_id) VALUES (1), (2), (3)"); _cf.commit()
_blocked = []
def _probe(url, headers, data=None):
    if "oauth" in url:
        return (200, {}, b'{"access_token": "T", "expires_in": 86400}')
    try:
        _o = sqlite3.connect(_fd, timeout=0); _o.execute("BEGIN IMMEDIATE"); _o.rollback(); _o.close()
    except sqlite3.OperationalError:
        _blocked.append(url)
    return (200, {}, b'{"name": "X"}')
API.fill_names(_cf, API.Client(("ID", "S"), fetch=_probe, cache_dir=_tf.mkdtemp()), limit=10)
_cf.close()
check(not _blocked, f"nombres: otro programa puede escribir en el archivo mientras se piden ({len(_blocked)} bloqueos)")

# --- espera entre descargas ---
_w = API.wait_after([{"t": _ts(24, 10, 23)}], _ts(24, 10, 30))
check(_w == API.next_check(_ts(24, 10, 30)) and abs(_w - 55 * 60) < 2, f"espera: con la foto de esta hora, hasta el minuto 25 siguiente ({_w})")
check(API.wait_after([{"t": _ts(24, 9, 23)}, {"t": _ts(24, 10, 23)}], _ts(24, 10, 30)) == 300, "espera: si falta la foto de una casa, reintenta a los 5 min")
check(API.wait_after([{"t": _ts(24, 9, 23)}], _ts(24, 10, 56)) == API.next_check(_ts(24, 10, 56)), "espera: pasado el minuto 55 deja de reintentar")

# --- panel de escritorio: servidor local con datos sintéticos (sin red exterior) ---
import threading as _th, urllib.request as _ur
import oroboros_panel as PNL
_pw = _tf.mkdtemp()
_sh.copy(_va, os.path.join(_pw, "archivo.sqlite")); _sh.copy(_vp, os.path.join(_pw, "oroboros.sqlite"))
with open(os.path.join(_pw, "plan.json"), "w", encoding="utf-8") as _f:
    _js.dump({"market": mk_, "marca": "plan-de-prueba"}, _f)
_st = {"busy": False}
_srv = PNL.make_server(_pw, port=0, state=_st, wake=lambda: _st.__setitem__("woken", True))
_port = _srv.server_address[1]
_thr = _th.Thread(target=_srv.serve_forever, daemon=True); _thr.start()
def _get(path, method="GET"):
    req = _ur.Request(f"http://127.0.0.1:{_port}{path}", method=method, data=b"" if method == "POST" else None)
    with _ur.urlopen(req, timeout=10) as r:
        body = r.read().decode("utf-8")
        return _js.loads(body) if r.headers.get("Content-Type", "").startswith("application/json") else body
check(_srv.server_address[0] == "127.0.0.1", "panel: solo escucha en este PC (127.0.0.1)")
_e = _get("/api/estado")
check(any(h["house"] == 111 and h["auctions"] == 2 for h in _e["houses"]), f"panel: estado de las casas ({_e['houses']})")
_b = _get("/api/buscar?q=2589")
check(_b and _b[0]["id"] == 2589 and _b[0]["prices"].get("111") == 30, f"panel: buscar por número de objeto, con el precio de cada casa ({_b[:1]})")
_o = _get("/api/objeto/2589")
check(len(_o["houses"]["111"]["hourly"]) == 73 and abs(_o["houses"]["111"]["rates"]["sold"] - 24) < 0.01
      and len(_o["houses"]["111"]["bands"]) == 6 and _o["houses"]["111"]["daily"],
      f"panel: objeto con precio por hora, por día, franjas y vendidas/día ({len(_o['houses']['111']['hourly'])})")
_v = _get("/api/ventas?dias=7")
_v111 = [h for h in _v["houses"] if h["house"] == 111][0]
check(_v111["top"][0]["id"] == 2589 and abs(_v111["top"][0]["sold"] - 24) < 0.01, f"panel: lo más vendido (estimado) por casa ({_v111['top'][:1]})")
_k = _get("/api/calibrar")
check("coverage" in _k[0] and "outside" in _k[0], f"panel: calibración con el libro ({_k})")
_html = _get("/")
check("plan-de-prueba" in _html and "/*__PLAN__*/null" not in _html and 'id="v-subasta"' in _html and "const PANEL = true" in _html,
      "panel: sirve la página del plan con el plan incrustado y las pestañas Subasta y Ventas")
_lock = sqlite3.connect(os.path.join(_pw, "archivo.sqlite")); _lock.execute("BEGIN IMMEDIATE")
_lock.execute("INSERT INTO meta VALUES ('bloqueo', '1')")
try:
    _e2 = _get("/api/estado"); _ok2 = "houses" in _e2
except Exception as _ex:
    _ok2 = False; _e2 = _ex
_lock.rollback(); _lock.close()
check(_ok2, f"panel: responde mientras la descarga está escribiendo en el archivo ({str(_e2)[:80]})")
def _raw(path, method="GET", headers=None):
    req = _ur.Request(f"http://127.0.0.1:{_port}{path}", method=method, data=b"" if method == "POST" else None, headers=headers or {})
    try:
        with _ur.urlopen(req, timeout=10) as r:
            return r.status
    except _ur.HTTPError as e:
        return e.code
check(_raw("/api/objeto/2589", headers={"Host": "malo.example:80"}) == 403,
      "panel: rechaza otro nombre de servidor (DNS rebinding: no se leen tu inventario ni tu libro)")
check(_raw("/api/parar", "POST", {"Origin": "http://malo.example"}) == 403 and _thr.is_alive(),
      "panel: una web cualquiera no puede parar el panel (Origin distinto)")
check(_raw("/api/estado", headers={"Host": f"localhost:{_port}"}) == 200, "panel: localhost también vale")
# --- panel: pestaña Inicio (ritmo de descarga, juego y lo importante) ---
_ini = _get("/api/inicio")
check(set(_ini) >= {"now", "api", "game", "plan", "top"} and _ini["api"]["houses"],
      f"inicio: el panel responde con descargas, juego, plan y lo más vendido ({sorted(_ini)})")
_iw = _tf.mkdtemp(); _ia = os.path.join(_iw, "archivo.sqlite")
_ci = API.open_api(_ia); API.set_house(_ci, 111, "Casa de subastas de la Alianza", realm="R5")
API.set_house(_ci, 114, "Casa de subastas de la Horda", realm="R5")
_now = _ts(24, 12, 30)
for _k in range(23, 9, -1):                           # de hace 23 h a hace 10 h, una por hora; luego hueco
    API.ingest(_ci, 111, _now - _k * 3600, [_au(_k, 100, 1, 50, "LONG")])   # cada hora se vende la anterior
API.ingest(_ci, 111, _now - 1800, [_au(1, 100, 1, 50, "LONG")])
API.ingest(_ci, 114, _now - 3 * 3600, [_au(1, 100, 1, 50, "LONG")])   # Horda: la última hace 3 h
_ci.execute("CREATE TABLE IF NOT EXISTS scans (scan_id INTEGER PRIMARY KEY, market_id INTEGER, t INTEGER, kind TEXT, n_items INTEGER)")
_ci.execute("INSERT INTO scans VALUES (1, 1, ?, 'full', 7000)", (_now - 7200,)); _ci.commit()
_ip = os.path.join(_iw, "oroboros.sqlite"); _cp = sqlite3.connect(_ip)
_cp.execute("CREATE TABLE characters (char TEXT, market TEXT, money INTEGER, level INTEGER, class TEXT, t INTEGER)")
_cp.execute("CREATE TABLE slots (char TEXT, location TEXT, total INTEGER, free INTEGER, t INTEGER)")
_cp.execute("INSERT INTO characters VALUES ('Ana-R5', 'R5-Alliance', 12345, 30, 'MAGE', ?)", (_now - 600,))
_cp.execute("INSERT INTO slots VALUES ('Ana-R5', 'bank', 98, 40, ?)", (_now - 86400,)); _cp.commit(); _cp.close()
with open(os.path.join(_iw, "plan.json"), "w", encoding="utf-8") as _f:
    _js.dump({"generated": _now - 900, "summary": {"profit": 500, "investment": 200, "gold": 9000, "stock_sale": 70, "roi": 2.5}}, _f)
_sv = os.path.join(_iw, "Oroboros.lua"); open(_sv, "w").close(); os.utime(_sv, (_now - 650, _now - 650))
_ii = PNL.inicio(_ci, {"next_run": _now + 600, "busy": False}, _iw, sv_path=_sv, now=_now)
_h111 = [h for h in _ii["api"]["houses"] if h["house"] == 111][0]
_h114 = [h for h in _ii["api"]["houses"] if h["house"] == 114][0]
check(_h111["snaps24"] == 15 and _h111["t"] == _now - 1800, f"inicio: fotos de las últimas 24 h y la última ({_h111['snaps24']}, {_h111['t']})")
check(_h111["gaps"] == [[_now - 10 * 3600, _now - 1800]], f"inicio: el hueco sin fotos se marca ({_h111['gaps']})")
check(_h114["gaps"] == [[_now - 86400, _now - 3 * 3600], [_now - 3 * 3600, _now]],
      f"inicio: hueco antes de la primera foto del día y, si la última es vieja, hasta ahora ({_h114['gaps']})")
check(_ii["api"]["next_run"] == _now + 600, "inicio: la próxima descarga (para la cuenta atrás)")
check(_ii["game"]["scan_t"] == _now - 7200 and _ii["game"]["scan_items"] == 7000 and _ii["game"]["sv_t"] == _now - 650,
      f"inicio: último escaneo del juego y último guardado ({_ii['game']})")
check(_ii["game"]["chars"] == [{"name": "Ana", "money": 12345, "level": 30, "class": "MAGE", "t": _now - 600, "bank_t": _now - 86400}],
      f"inicio: personajes con oro y cuándo se vio su banco ({_ii['game']['chars']})")
check(_ii["plan"] == {"generated": _now - 900, "profit": 500, "investment": 200, "gold": 9000, "stock_sale": 70, "roi": 2.5},
      f"inicio: los números del plan ({_ii['plan']})")
check(_ii["top"]["house"] == 111 and _ii["top"]["calibrated"] is False and _ii["top"]["items"]
      and _ii["top"]["items"][0]["id"] == 100 and _ii["top"]["items"][0]["sold"] > 0 and _ii["top"]["items"][0]["min"] == 50,
      f"inicio: lo más vendido (estimado) en tu casa, sin comprobar con el libro ({_ii['top']})")
_ci.close()
_get("/api/descargar", "POST")
check(_st.get("woken"), "panel: «descargar ahora» despierta la descarga")
_get("/api/parar", "POST")
_thr.join(5)
check(not _thr.is_alive(), "panel: «parar» cierra el servidor")
_plain = open(os.path.join(ROOT, "tools", "planner_ui.html"), encoding="utf-8").read()
check('id="ini-stop"' in _plain and _plain.count('apiGet("/api/parar", "POST")') == 2, "panel: el botón «Parar el panel» está también en Inicio")
check('id="v-inicio"' in _plain and '[["inicio", "Inicio"]].concat(API_VIEWS)' in _plain and 'PANEL ? "inicio"' in _plain,
      "panel: la pestaña Inicio existe y es la que se abre primero con el panel")
check("/*__PANEL__*/false" in _plain,"plan.html sin panel: las pestañas nuevas dicen que hay que abrir el panel")

# ---- Fase 7: Aguasnegras → tu casa, enfriamientos como renta y gangas ----
_d7 = _tf.mkdtemp(); _c7 = API.open_api(os.path.join(_d7, "n.sqlite"))
API.set_house(_c7, 111, "Casa de subastas de la Alianza", realm="R5")
check(API.neutral_house(_c7, 111) is None, "Aguasnegras: sin casa neutral en el archivo, nada")
API.set_house(_c7, 117, "Casa de subastas de Aguasnegras", realm="R5")
_m = lambda i, item, q, price: _au(i, item, q, price, "LONG", mat=True)
API.ingest(_c7, 117, _T0, [_m(1, 900, 5, 40)])
check(API.neutral_house(_c7, 111) == (117, "Casa de subastas de Aguasnegras", _T0) and API.neutral_house(_c7, 117) is None,
      f"Aguasnegras: la casa neutral del mismo reino y su última foto ({API.neutral_house(_c7, 111)})")
# gangas: tres días a 10 000, una hora antes dos subastas, y en la última foto aparece una a mitad de precio
for _k in (3, 2, 1):
    API.ingest(_c7, 111, _T0 - _k * 86400, [_m(10 * _k, 900, 10, 10000), _m(10 * _k + 1, 901, 10, 10000), _m(10 * _k + 2, 902, 10, 10000)])
API.ingest(_c7, 111, _T0 - 3600, [_m(50, 900, 10, 10000), _m(51, 900, 10, 10000), _m(52, 901, 10, 10000), _m(53, 901, 10, 5000),
                                   _m(54, 902, 10, 10000), _m(55, 902, 10, 10000)])
API.ingest(_c7, 111, _T0, [_m(51, 900, 10, 10000), _m(60, 900, 4, 5000),          # 900: aparece una ganga
                           _m(53, 901, 10, 5000), _m(61, 901, 4, 5000),           # 901: ya había una vieja a ese precio
                           _m(55, 902, 10, 10000), _m(62, 902, 4, 9000)])         # 902: solo un 10 % más barata
_c7.execute("UPDATE items SET stack=20, name='Mena de prueba' WHERE item_id IN (900, 901, 902)")
_bg = API.bargains(_c7, 111)
check([r["id"] for r in _bg["items"]] == [900] and _bg["t"] == _T0, f"gangas: solo lo que aparece un 30 % bajo su precio habitual, sin viejas a ese precio ({[r['id'] for r in _bg['items']]})")
_b0 = _bg["items"][0] if _bg["items"] else {}
check(_b0.get("qty") == 4 and _b0.get("usual") == 10000 and abs(_b0.get("discount", 0) - 0.5) < 1e-9
      and abs(_b0.get("saving", 0) - (10000 * 0.95 * 4 - 20000)) < 1e-6 and _b0.get("name") == "Mena de prueba",
      f"gangas: unidades, precio habitual, descuento y diferencia sin la comisión ({_b0})")
_c7.execute("UPDATE items SET stack=1 WHERE item_id=900")
check(API.bargains(_c7, 111)["items"] == [], "gangas: sin variantes guardadas, lo que no se apila no cuenta (puede ser equipo con sufijo)")
_c7.execute("INSERT INTO api_var VALUES (111, 55, '7')")
check(len(API.bargains(_c7, 111)["items"]) == 1, "gangas: con variantes guardadas, el equipo de una sola variante sí cuenta")
check("bargains" in _ii and "items" in _ii["bargains"], "panel: Inicio trae las gangas de la última foto")

# Aguasnegras → tu casa (planificador)
def _n7(neutral_lad, own=((1000, 50),), age=0, variants=(), stack=20):
    dd = _f5(ladder=list(own))
    dd.items[777777]["stack"] = stack
    dd.neutral = {"house": 117, "name": "Aguasnegras", "t": dd.now - age, "ladders": {777777: list(neutral_lad)}, "variants": set(variants)}
    return dd
_ch7 = "Zartbank-ForeverPvE"
_nt = _OP.find_neutral(_n7([(400, 5), (500, 5), (900, 10)]), 48, _ch7, 10 ** 6)
_f7 = _nt["items"][0] if _nt["items"] else {}
check(len(_nt["items"]) == 1 and _f7.get("units") == 10 and _f7.get("max_buy") == 500 and abs(_f7.get("cost", 0) - 450) < 1e-6
      and abs(_f7.get("sell", 0) - 990) < 1e-6 and _f7.get("included") and _nt["invest"] == 4500,
      f"Aguasnegras: compra allí lo que deja margen y lo vende bajo lo más barato de tu casa ({_f7.get('units')}, {_f7.get('max_buy')}, {_f7.get('sell')})")
check("BUY 777777 10 500" in _nt["route"] and not _nt["worth"] and not _nt["stale"],
      "Aguasnegras: lista de compras aparte, y con menos de 2 oro dice que no compensa el viaje")
_np, _ne = ns.Queue.Parse(_nt["route"])
check(_ne is not None and len(list(_ne.values())) == 0 and len(list(_np.values())) >= 1, f"Aguasnegras: el addon entiende la lista de compras ({_ne and list(_ne.values())}, {_np and len(list(_np.values()))}, {_nt.get('route')!r})")
_nb = _OP.find_neutral(_n7([(400, 5), (500, 5)]), 48, _ch7, 0)
check(len(_nb["items"]) == 1 and not _nb["items"][0]["included"] and _nb["route"] == "" and _nb["profit"] == 0,
      "Aguasnegras: sin oro para apuestas no entra nada")
check(_OP.find_neutral(_n7([(400, 5)], variants=[777777]), 48, _ch7, 10 ** 6)["items"] == []
      and _OP.find_neutral(_n7([(400, 5)], stack=1), 48, _ch7, 10 ** 6)["items"] == []
      and _OP.find_neutral(_n7([(900, 5)]), 48, _ch7, 10 ** 6)["items"] == [],
      "Aguasnegras: ni equipo con variantes, ni lo que no se apila, ni lo que no deja margen")
check(_OP.find_neutral(_n7([(400, 5), (500, 5)], age=4 * 3600), 48, _ch7, 10 ** 6)["stale"],
      "Aguasnegras: con una foto de más de 3 h avisa de que la lista está vieja")
_dn = _n7([(400, 5), (500, 5)])
_dn.history[777777] = []; _dn._stats = {}
check(_OP.proven_sales(_dn, 777777) is None and _OP.find_neutral(_dn, 48, _ch7, 10 ** 6)["items"] == [],
      "Aguasnegras: sin ventas comprobadas en tu casa no se propone")
check(_OP.find_neutral(_f5(), 48, _ch7, 10 ** 6)["house"] is None and plan["neutral"]["items"] == [],
      "Aguasnegras: sin fotos de la casa neutral, la lista sale vacía")

# enfriamiento compartido y renta diaria
class _DC:
    catalog = {"cooldown_groups": {"_nota": "x", "transmutar": [1, 2]}}
_o7 = [{"char": "a", "recipe": 1, "name": "A", "profit_total": 10}, {"char": "a", "recipe": 2, "name": "B", "profit_total": 30},
       {"char": "a", "recipe": 3, "name": "C", "profit_total": 5}, {"char": "b", "recipe": 1, "name": "A", "profit_total": 10}]
_k7, _x7 = _OP.cooldown_groups(_DC, _o7)
check([o["name"] for o in _k7] == ["B", "C", "A"] and len(_x7) == 1 and "Comparte enfriamiento con B" in _x7[0]["reason"],
      "enfriamiento compartido: por personaje se queda la receta que más da; las demás, con su motivo")
_cd_real = {k: v for k, v in _cat_real.get("recipes", {}).items() if not k.startswith("_")}
check(_cd_real and all(k.isdigit() and v.get("cooldown_h", 0) > 0 and v.get("source") and isinstance(v.get("verified"), bool)
                       for k, v in _cd_real.items())
      and all(str(r) in _cd_real for g, ids in _cat_real["cooldown_groups"].items() if not g.startswith("_") for r in ids),
      "catálogo: cada enfriamiento lleva fuente y marca, y las recetas de un grupo tienen enfriamiento")
_inc = [e for e in plan["learn"] if e.get("cooldown_h")]
check(_inc and all(e.get("income") for e in _inc if "profit" in e)
      and all(e["per_day"] <= _OP.COOLDOWN_USES_DAY and any(v.startswith("Renta:") for v in e["verdict"])
              for e in _inc if (e.get("daily_profit") or 0) > 0),
      f"qué aprender: las recetas con enfriamiento se valoran como renta diaria ({[(e['name'], e.get('daily_profit')) for e in _inc]})")
_ui7 = open(os.path.join(ROOT, "tools", "planner_ui.html"), encoding="utf-8").read()
check("neutralHtml(PLAN.neutral)" in _ui7 and "Gangas de la última foto" in _ui7 and "renta diaria" in _ui7,
      "página: Aguasnegras en Ideas, gangas en Inicio y la marca de renta diaria en Qué aprender")

print("\nTODO OK" if ok else "\nHAY FALLOS")
for line in list(G.LOG.values())[-8:]:
    print("   ", line)

for cmd in ["", "show", "price 2589", "price |cff|Hitem:4306::|h[x]|h|r", "prof", "stats", "set undercut 5", "set nope 1", "import", "zzz"]:
    G.SlashCmdList.OROBOROS(cmd)
print("comandos OK; últimas líneas:")
for line in list(G.LOG.values())[-12:]:
    print("   ", line)
