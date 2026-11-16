-- Oroboros: base de datos (SavedVariables OroborosDB)
local _, ns = ...
local DB = {}
ns.DB = DB

local SCHEMA = 1

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
    if not d then
        h[day] = { min = rec.min, mv = rec.mv, qty = rec.qty }
    else
        if rec.min and (not d.min or rec.min < d.min) then d.min = rec.min end
        d.mv, d.qty = rec.mv, rec.qty
    end
end

-- byItem: { [itemID] = { {unitPrice, qty}, ... } }
-- full = true si es un escaneo completo: lo que no aparezca queda con qty 0
function DB.RecordPrices(byItem, full, mk)
    local m = DB.Market(mk)
    local now, day = time(), ns.Today()
    local count = 0
    for itemID, listings in pairs(byItem) do
        local min, mv, qty, n, depth = DB.Aggregate(listings)
        if min then
            local rec = { min = min, mv = mv, qty = qty, n = n, t = now, d = depth }
            m.prices[itemID] = rec
            updateHistory(m, itemID, rec, day)
            count = count + 1
        end
    end
    if full then
        for itemID, rec in pairs(m.prices) do
            if not byItem[itemID] then rec.qty, rec.n, rec.t = 0, 0, now end
        end
        m.lastFull = now
    end
    return count
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
    end
    if nMk == 0 then ns.Print("  sin mercados escaneados") end
end
