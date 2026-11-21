-- Oroboros: base de datos (SavedVariables OroborosDB)
local _, ns = ...
local DB = {}
ns.DB = DB

local SCHEMA = 1
local SCAN_BUFFER = 12     -- escaneos en bruto que se guardan (ver más abajo)

--[[ Estructura
OroborosDB = {
  schema = 1,
  config = { ... },
  items  = { [itemID] = { n = nombre, q = calidad, s = venta a vendedor, st = tamaño pila, c = commodity(bool) } },
  vendor = { [itemID] = precio de compra al vendedor por unidad (cobre) },
  markets = {
    [marketKey] = {
      lastFull = timestamp del último escaneo completo,
      prices  = { [itemID] = { min, mv, qty, n, t } },   -- foto actual
      history = { [itemID] = { ["YYYY-MM-DD"] = { min, mv, qty } } },
    }
  },
  chars = { [charKey] = { market, money, level, class, t,
                          bags = {[itemID]=n}, bagSlots = {total, free},
                          bank = {[itemID]=n}, bankSlots = {total, free}, bankT,
                          professions = {...} } },
  ledger = { { t, char, op = "BUY"|"SELL", item, qty, unit, total, src } },   -- compras y ventas reales
  positions = { [itemID] = { qty, entry, target, stop, due, t, char } },      -- apuestas abiertas (HOLD)
  seenMail = { [clave] = caducidad },
  warband = { items = {[itemID]=n}, slots = {total, free}, t },   -- banco de banda (si existe)
  routes = { [charKey] = { text = "...", t = timestamp, items = {...}, idx = n } },   -- ruta de cada personaje
  config.banker = charKey del personaje que compra y vende en la subasta (/oro banquero)
}
]]

function DB.Init(defaults)
    OroborosDB = OroborosDB or {}
    local db = OroborosDB
    db.schema  = db.schema or SCHEMA
    db.config  = db.config or {}
    db.items   = db.items or {}
    db.vendor  = db.vendor or {}
    db.markets = db.markets or {}
    db.chars   = db.chars or {}
    db.routes  = db.routes or {}        -- una ruta por personaje
    if db.route and db.route.items then  -- migración desde versiones con una sola ruta
        db.routes[ns.CharKey()] = db.routes[ns.CharKey()] or db.route
    end
    db.route = nil
    db.ledger  = db.ledger or {}
    db.positions = db.positions or {}
    db.seenMail = db.seenMail or {}
    db.population = nil       -- ya no se usa
    DB.PruneHistory()
end

----------------------------------------------------------------------
-- Reino vacío: mercados «-Facción» y personajes «Nombre-» que se guardaron cuando el juego dio el reino
-- vacío. Se fusionan con los buenos (mismo criterio que al guardar: gana el dato más reciente).
----------------------------------------------------------------------
local function knownRealm()
    local r = ns.Realm()
    if r ~= "?" then return r end
    local found
    for mk in pairs(OroborosDB.markets) do
        local realm = mk:match("^(.+)%-[^%-]+$")
        if realm and realm ~= "" and realm ~= "?" then
            if found and found ~= realm then return nil end      -- varios reinos: no se adivina
            found = realm
        end
    end
    if found then OroborosDB.realm = found end
    return found
end

local function mergeMarket(src, dst)
    for id, p in pairs(src.prices or {}) do
        local q = dst.prices[id]
        if not q or (p.t or 0) > (q.t or 0) then dst.prices[id] = p end
    end
    for id, days in pairs(src.history or {}) do
        local h = dst.history[id]
        if not h then h = {}; dst.history[id] = h end
        for day, d in pairs(days) do
            local e = h[day]
            if not e then
                h[day] = d
            else
                local lo = (d.min and e.min) and math.min(d.min, e.min) or (d.min or e.min)
                if (d.t or 0) > (e.t or 0) then e.mv, e.qty, e.t = d.mv, d.qty, d.t end
                e.min = lo
            end
        end
    end
    if src.scans and #src.scans > 0 then
        dst.scans = dst.scans or {}
        for _, s in ipairs(src.scans) do table.insert(dst.scans, s) end
        table.sort(dst.scans, function(a, b) return (a.t or 0) < (b.t or 0) end)
        while #dst.scans > SCAN_BUFFER do table.remove(dst.scans, 1) end
    end
    if (src.lastFull or 0) > (dst.lastFull or 0) then dst.lastFull = src.lastFull end
end

-- Devuelve cuántos mercados y personajes se han arreglado
function DB.FixEmptyRealm()
    local nm, nc = 0, 0
    local realm
    for mk, m in pairs(OroborosDB.markets) do
        local faction = mk:match("^%-([^%-]+)$")
        if faction then
            realm = realm or knownRealm()
            if not realm then return 0, 0 end
            mergeMarket(m, DB.Market(realm .. "-" .. faction))
            OroborosDB.markets[mk] = nil
            nm = nm + 1
        end
    end
    for ck, c in pairs(OroborosDB.chars) do
        local name = ck:match("^(.+)%-$")
        if name then
            realm = realm or knownRealm()
            if not realm then break end
            local good = name .. "-" .. realm
            local g = OroborosDB.chars[good]
            if not g or (c.t or 0) > (g.t or 0) then
                OroborosDB.chars[good] = c
                for k, v in pairs(g or {}) do if c[k] == nil then c[k] = v end end      -- lo que el duplicado no trae
                for k, v in pairs((g and g.professions) or {}) do
                    c.professions = c.professions or {}
                    if c.professions[k] == nil then c.professions[k] = v end
                end
            end
            OroborosDB.chars[ck] = nil
            nc = nc + 1
        end
    end
    for _, c in pairs(OroborosDB.chars) do
        local faction = type(c.market) == "string" and c.market:match("^%-([^%-]+)$")
        if faction and realm then c.market = realm .. "-" .. faction end
    end
    if nm + nc > 0 then
        ns.Print(string.format("arreglados %d mercados y %d personajes guardados sin reino (el juego dio el reino vacío).", nm, nc))
    end
    return nm, nc
end

function DB.Market(mk)
    mk = mk or ns.MarketKey()
    local m = OroborosDB.markets[mk]
    if not m then
        m = { lastFull = 0, prices = {}, history = {} }
        OroborosDB.markets[mk] = m
    end
    return m
end

----------------------------------------------------------------------
-- Información de objetos
----------------------------------------------------------------------
function DB.SetItemInfo(itemID, name, quality, isCommodity)
    if not itemID then return end
    local it = OroborosDB.items[itemID]
    if not it then it = {}; OroborosDB.items[itemID] = it end
    if name and name ~= "" then it.n = name end
    if quality then it.q = quality end
    if isCommodity ~= nil then it.c = isCommodity end
    if (not it.s or not it.n) and C_Item and C_Item.GetItemInfo then
        local nm, _, _, ilvl, _, _, _, stack, _, _, sell = C_Item.GetItemInfo(itemID)
        if nm and not it.n then it.n = nm end
        if ilvl then it.il = ilvl end
        if stack then it.st = stack end
        if sell then it.s = sell end
    end
end

function DB.ItemName(itemID)
    local it = OroborosDB.items[itemID]
    if it and it.n then return it.n end
    if C_Item and C_Item.GetItemInfo then
        local name = C_Item.GetItemInfo(itemID)
        if name then return name end
    end
    return "item:" .. tostring(itemID)
end

function DB.IsCommodity(itemID)
    local it = OroborosDB.items[itemID]
    if it and it.c ~= nil then return it.c end
    if C_AuctionHouse and C_AuctionHouse.GetItemKeyInfo then
        local info = C_AuctionHouse.GetItemKeyInfo(C_AuctionHouse.MakeItemKey(itemID))
        if info and info.isCommodity ~= nil then
            DB.SetItemInfo(itemID, info.itemName, info.quality, info.isCommodity)
            return info.isCommodity
        end
    end
    -- heurística: lo apilable suele ser commodity
    if C_Item and C_Item.GetItemInfo then
        local stack = select(8, C_Item.GetItemInfo(itemID))
        if stack then return stack > 1 end
    end
    return nil
end

----------------------------------------------------------------------
-- Precios
----------------------------------------------------------------------
-- listings: lista de { unitPrice, qty }. Devuelve min, mv, qtyTotal, nAuctions
function DB.Aggregate(listings)
    if #listings == 0 then return nil end
    table.sort(listings, function(a, b) return a[1] < b[1] end)
    local total = 0
    for i = 1, #listings do total = total + listings[i][2] end
    local target = math.max(1, math.ceil(total * ns.Cfg("mvPercent")))
    local acc, sum = 0, 0
    for i = 1, #listings do
        local price, q = listings[i][1], listings[i][2]
        local take = math.min(q, target - acc)
        sum = sum + price * take
        acc = acc + take
        if acc >= target then break end
    end
    -- profundidad: cantidad disponible a ≤ min × 1.10 / 1.25 / 1.5 / 2.0
    local min = listings[1][1]
    local tiers, depth = { 1.10, 1.25, 1.5, 2.0 }, { 0, 0, 0, 0 }
    for i = 1, #listings do
        local price, q = listings[i][1], listings[i][2]
        for t = 1, 4 do
            if price <= min * tiers[t] then depth[t] = depth[t] + q end
        end
    end
    return min, math.floor(sum / acc + 0.5), total, #listings, depth
end

local function updateHistory(m, itemID, rec, day)
    local h = m.history[itemID]
    if not h then h = {}; m.history[itemID] = h end
    local d = h[day]
    -- t: hora del último escaneo del día (las ventas por día se miden con el tiempo real)
    if not d then
        h[day] = { min = rec.min, mv = rec.mv, qty = rec.qty, t = rec.t }
    else
        if rec.min and (not d.min or rec.min < d.min) then d.min = rec.min end
        d.mv, d.qty, d.t = rec.mv, rec.qty, rec.t
    end
end

-- Escaneos en bruto para analizar franjas horarias fuera del juego (docs/franjas-horarias.md).
-- Se guardan los últimos SCAN_BUFFER; el exportador (--archive) los pasa a un SQLite permanente.
local CHEAP = 1.25        -- barato = a ≤ mínimo × 1,25

function DB.ScanCount(mk)
    local scans = DB.Market(mk).scans
    return scans and #scans or 0, SCAN_BUFFER
end

-- Escaneos aún sin exportar: los posteriores al último archivado, según Resumen.lua (lo escribe el
-- exportador). Sin esa información cuentan todos. Se pierde uno solo si hay más de 12 sin exportar.
function DB.PendingScans(mk)
    mk = mk or ns.MarketKey()
    local scans = DB.Market(mk).scans or {}
    local r = OroborosResumen
    local upTo = type(r) == "table" and type(r.archived) == "table" and r.archived[mk] or nil
    local n = 0
    for _, s in ipairs(scans) do
        if not upTo or (s.t or 0) > upTo then n = n + 1 end
    end
    return n, SCAN_BUFFER
end

local function fmt(x) return x and string.format("%.0f", x) or "" end

-- byItem: { [itemID] = { {unitPrice, qty}, ... } }
-- full = true si es un escaneo completo: lo que no aparezca queda con qty 0
-- bids (opcional, del escaneo completo): { bids = {[itemID] = puja mínima por unidad}, bidOnly = {[itemID] = n} }
function DB.RecordPrices(byItem, full, mk, bids)
    local m = DB.Market(mk)
    local now, day = time(), ns.Today()
    local count = 0
    local lines = full and {} or nil
    for itemID, listings in pairs(byItem) do
        local prev = m.prices[itemID]
        local min, mv, qty, n, depth = DB.Aggregate(listings)
        if min then
            if lines then
                -- bp: unidades a ≤ el umbral barato del escaneo anterior (mismo umbral en los dos)
                local ref = ((prev and prev.min and prev.qty and prev.qty > 0) and prev.min or min) * CHEAP
                local bp = 0
                for i = 1, #listings do
                    if listings[i][1] <= ref then bp = bp + listings[i][2] end
                end
                lines[#lines + 1] = string.format("%d,%s,%s,%d,%d,%d", itemID, fmt(min), fmt(mv), qty, depth[2], bp)
            end
            local rec = { min = min, mv = mv, qty = qty, n = n, t = now, d = depth }
            if bids then rec.bid, rec.nb = bids.bids[itemID], bids.bidOnly[itemID] end
            m.prices[itemID] = rec
            updateHistory(m, itemID, rec, day)
            count = count + 1
        end
    end
    if full then
        for itemID, rec in pairs(m.prices) do
            if not byItem[itemID] then
                if rec.qty and rec.qty > 0 then     -- se ha agotado desde el último escaneo
                    lines[#lines + 1] = string.format("%d,,,0,0,0", itemID)
                end
                rec.qty, rec.n, rec.t = 0, 0, now
            end
        end
        m.lastFull = now
        m.scans = m.scans or {}
        table.insert(m.scans, { t = now, data = table.concat(lines, ";") })
        while #m.scans > SCAN_BUFFER do table.remove(m.scans, 1) end
    end
    return count
end

-- Variantes (mismo itemID, distinto nombre por el sufijo): { [nombre] = { id, min, bid, n, t } }.
-- El escaneo completo las rehace; una búsqueda en la subasta actualiza la de ese nombre.
function DB.RecordVariants(names, mk)
    local m = DB.Market(mk)
    local now, out = time(), {}
    for id, byName in pairs(names or {}) do
        local k = 0
        for _ in pairs(byName) do k = k + 1 end
        if k >= 2 then
            for name, v in pairs(byName) do out[name] = { id = id, min = v.min, bid = v.bid, n = v.n, t = now } end
        end
    end
    m.variants = out
end

function DB.SetVariant(name, v, mk)
    if not name or name == "" then return end
    local m = DB.Market(mk)
    m.variants = m.variants or {}
    v.t = v.t or time()
    m.variants[name] = v
end

function DB.GetVariant(name, itemID, mk)
    local m = DB.Market(mk)
    local v = name and m.variants and m.variants[name]
    if v and (not itemID or v.id == itemID) then return v end
    return nil
end

function DB.GetPrice(itemID, mk)
    return DB.Market(mk).prices[itemID]
end

function DB.PruneHistory()
    local cutoff = date("%Y-%m-%d", time() - ns.Cfg("historyDays") * 86400)
    for _, m in pairs(OroborosDB.markets) do
        for itemID, h in pairs(m.history) do
            local any = false
            for day in pairs(h) do
                if day < cutoff then h[day] = nil else any = true end
            end
            if not any then m.history[itemID] = nil end
        end
    end
end

function DB.SetVendorPrice(itemID, unitPrice)
    if itemID and unitPrice and unitPrice > 0 then
        OroborosDB.vendor[itemID] = unitPrice
    end
end

----------------------------------------------------------------------
-- Personaje
----------------------------------------------------------------------
function DB.Char()
    local ck = ns.CharKey()
    local c = OroborosDB.chars[ck]
    if not c then c = { bags = {}, professions = {} }; OroborosDB.chars[ck] = c end
    return c
end

function DB.SnapshotCharacter()
    if not OroborosDB then return end
    local c = DB.Char()
    c.market = ns.MarketKey()
    c.money = GetMoney()
    c.level = UnitLevel("player")
    c.class = select(2, UnitClass("player"))
    c.t = time()
end

-- Contenedores de cada zona. Forever usa la interfaz moderna: el banco puede ser
-- clásico (-1 + bolsas 6-12, -3 materiales) o por pestañas; probamos lo que exista.
local function bankContainers()
    local B, list, seen = Enum and Enum.BagIndex or {}, {}, {}
    local function add(id) if id and not seen[id] then seen[id] = true; list[#list + 1] = id end end
    add(B.Bank or -1)
    add(B.Reagentbank or -3)
    for i = 1, 7 do add(B["BankBag_" .. i]) end
    for i = 1, 6 do add(B["CharacterBankTab_" .. i]) end
    if not B.BankBag_1 and not B.CharacterBankTab_1 then
        for id = (NUM_TOTAL_EQUIPPED_BAG_SLOTS or 5) + 1, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or 5) + 7 do add(id) end
    end
    return list
end

local function warbandContainers()
    local B, list = Enum and Enum.BagIndex or {}, {}
    for i = 1, 5 do
        if B["AccountBankTab_" .. i] then list[#list + 1] = B["AccountBankTab_" .. i] end
    end
    return list
end

local function bagContainers()
    local list = {}
    for bag = 0, (NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do list[#list + 1] = bag end
    return list
end

-- Lee contenedores: devuelve { [itemID] = cantidad }, { total = huecos, free = libres }
function DB.ReadContainers(ids)
    local items, total, free = {}, 0, 0
    for _, bag in ipairs(ids) do
        local n = C_Container.GetContainerNumSlots(bag) or 0
        total = total + n
        for slot = 1, n do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info and info.itemID then
                items[info.itemID] = (items[info.itemID] or 0) + (info.stackCount or 1)
                DB.SetItemInfo(info.itemID)
            else
                free = free + 1
            end
        end
    end
    return items, { total = total, free = free }
end

function DB.SnapshotBags()
    if not OroborosDB or not C_Container then return end
    local c = DB.Char()
    c.bags, c.bagSlots = DB.ReadContainers(bagContainers())
end

-- Solo se puede leer con el banco abierto
function DB.SnapshotBank()
    if not OroborosDB or not C_Container then return end
    local c = DB.Char()
    local items, slots = DB.ReadContainers(bankContainers())
    if slots.total > 0 then
        c.bank, c.bankSlots, c.bankT = items, slots, time()
    end
    local wb = warbandContainers()
    if #wb > 0 then
        local witems, wslots = DB.ReadContainers(wb)
        if wslots.total > 0 then
            OroborosDB.warband = { items = witems, slots = wslots, t = time() }
        end
    end
    if ns.UI then
        ns.UI.SetStatus(string.format("Banco leído: %d/%d huecos libres.", slots.free, slots.total))
    end
end

-- Libro de compras y ventas: qué, cuánto y a cuánto (lo rellena Ledger.lua)
function DB.AddLedger(op, itemID, qty, unit, total, src)
    if not OroborosDB or not itemID or not qty or qty <= 0 then return end
    local L = OroborosDB.ledger
    L[#L + 1] = { t = time(), char = ns.CharKey(), op = op, item = itemID, qty = qty,
                  unit = unit and math.floor(unit + 0.5) or nil, total = total, src = src }
    while #L > 2000 do table.remove(L, 1) end
    DB.SetItemInfo(itemID)
end

-- Apuesta abierta: lo que el planificador te dijo que guardaras, con su objetivo y su stop
function DB.SetPosition(a)
    local P = OroborosDB.positions
    local p = P[a.itemID]
    if p and p.qty and p.entry and a.entry then
        p.entry = math.floor((p.entry * p.qty + a.entry * a.qty) / (p.qty + a.qty) + 0.5)
        p.qty = p.qty + a.qty
    else
        p = { qty = a.qty, entry = a.entry, t = time() }
        P[a.itemID] = p
    end
    p.target, p.stop, p.due, p.char = a.price, a.stop, a.due, ns.CharKey()
    DB.SetItemInfo(a.itemID)
end

function DB.PrintStats()
    local nItems, nMk = 0, 0
    for _ in pairs(OroborosDB.items) do nItems = nItems + 1 end
    ns.Print("objetos conocidos: " .. nItems)
    for mk, m in pairs(OroborosDB.markets) do
        nMk = nMk + 1
        local n = 0
        for _ in pairs(m.prices) do n = n + 1 end
        ns.Print(string.format("  mercado %s: %d precios, último completo %s", mk, n,
            m.lastFull > 0 and date("%d/%m %H:%M", m.lastFull) or "nunca"))
        local pend, cap = DB.PendingScans(mk)
        ns.Print(string.format("  escaneos sin exportar: %d/%d%s", pend, cap,
            pend >= cap and " (exporta antes del siguiente escaneo o se perderá el más antiguo)"
            or (pend >= cap - 2 and " (exporta pronto)" or "")))
    end
    if nMk == 0 then ns.Print("  sin mercados escaneados") end
end

----------------------------------------------------------------------
-- Nombres que faltan: el escaneo completo no trae el nombre de los objetos que el cliente
-- aún no tiene cargados. Se piden en tandas para no congelar el juego y se guardan al llegar.
----------------------------------------------------------------------
local NAME_BATCH, NAME_DELAY = 100, 0.2
local nameQueue, nameBusy = {}, false

local function nameStep()
    local n = 0
    while n < NAME_BATCH and #nameQueue > 0 do
        local id = table.remove(nameQueue)
        local it = OroborosDB.items[id]
        if it and not it.n and C_Item and C_Item.RequestLoadItemDataByID then
            C_Item.RequestLoadItemDataByID(id)
            n = n + 1
        end
    end
    if #nameQueue > 0 then C_Timer.After(NAME_DELAY, nameStep) else nameBusy = false end
end

function DB.QueueMissingNames()
    if not OroborosDB then return end
    wipe(nameQueue)
    for id, it in pairs(OroborosDB.items) do
        if not it.n then nameQueue[#nameQueue + 1] = id end
    end
    if #nameQueue > 0 and not nameBusy then
        nameBusy = true
        nameStep()
    end
end

ns.On("GET_ITEM_INFO_RECEIVED", function(itemID, ok)
    if ok and itemID and OroborosDB and OroborosDB.items[itemID] then DB.SetItemInfo(itemID) end
end)
