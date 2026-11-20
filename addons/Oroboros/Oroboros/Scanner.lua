-- Oroboros: escaneo de la casa de subastas y de vendedores
local _, ns = ...
local Scanner = {}
ns.Scanner = Scanner

local REPLICATE_COOLDOWN = 15 * 60  -- Blizzard limita ReplicateItems a ~1 cada 15 min
local CHUNK = 1500                  -- subastas procesadas por frame para no congelar el cliente

Scanner.ahOpen = false
Scanner.state = "idle"              -- idle | waiting | reading
Scanner.lastReplicate = 0
Scanner.lastRead = 0                -- última vez que leímos un resultado de ReplicateItems (nuestro o ajeno)
local pending = {}                  -- [itemID] = { callbacks }

local function setStatus(text)
    if ns.UI and ns.UI.SetStatus then ns.UI.SetStatus(text) end
end

ns.On("AUCTION_HOUSE_SHOW", function()
    Scanner.ahOpen = true
    if ns.UI then ns.UI.OnAuctionHouse(true) end
    C_Timer.After(1, function() Scanner.TryAutoScan() end)
end)

ns.On("AUCTION_HOUSE_CLOSED", function()
    Scanner.ahOpen = false
    Scanner.state = "idle"
    wipe(pending)
    if ns.UI then ns.UI.OnAuctionHouse(false) end
end)

----------------------------------------------------------------------
-- Escaneo completo (ReplicateItems)
----------------------------------------------------------------------
----------------------------------------------------------------------
-- Auctionator: si está cargado y hace él el escaneo completo, no pedimos otro.
-- ReplicateItems tiene un límite de ~1 cada 15 min compartido entre addons, y su
-- resultado (REPLICATE_ITEM_LIST_UPDATE) llega a todos: lo leemos sin pedirlo.
----------------------------------------------------------------------
function Scanner.AuctionatorLoaded()
    return type(Auctionator) == "table" and type(Auctionator.API) == "table" and Auctionator.API.v1 ~= nil
end

-- true si Auctionator tiene activado su escaneo completo (opción «replicate_scan»)
function Scanner.AuctionatorReplicates()
    if not Scanner.AuctionatorLoaded() then return false end
    local cfg = Auctionator.Config
    if type(cfg) ~= "table" or type(cfg.Get) ~= "function" or type(cfg.Options) ~= "table" then return false end
    local ok, v = pcall(cfg.Get, cfg.Options.REPLICATE_SCAN)
    return ok and v == true
end

-- último ReplicateItems pedido por nosotros o por Auctionator
local function lastReplicateAny()
    local t = Scanner.lastReplicate
    -- el límite del servidor sobrevive a /reload: guardamos la hora en la BD
    if OroborosDB and type(OroborosDB.lastReplicate) == "number" and OroborosDB.lastReplicate > t then
        t = OroborosDB.lastReplicate
    end
    local sv = AUCTIONATOR_SAVEDVARS
    if type(sv) == "table" and type(sv.TimeOfLastReplicateScan) == "number" and sv.TimeOfLastReplicateScan > t then
        t = sv.TimeOfLastReplicateScan
    end
    return t
end

function Scanner.CanFullScan()
    local left = REPLICATE_COOLDOWN - (time() - lastReplicateAny())
    return left <= 0, math.max(0, left)
end

-- Escaneo automático al abrir la subasta (fase 3): solo si toca y si Auctionator no hace el suyo.
-- Se ve igual que si se hubiera pulsado el botón: botón pulsado, avance en la línea de estado y aviso en el chat.
function Scanner.TryAutoScan()
    if tonumber(ns.Cfg("autoscan")) == 0 then return false end
    if not Scanner.ahOpen or Scanner.state ~= "idle" then return false end
    if Scanner.AuctionatorReplicates() then return false end
    if not Scanner.CanFullScan() then return false end
    Scanner.FullScan(false, true)
    return Scanner.state == "waiting"
end

-- force = true lanza nuestro ReplicateItems aunque Auctionator escanee (/oro scan forzar)
-- auto = true si lo lanza TryAutoScan
function Scanner.FullScan(force, auto)
    if not Scanner.ahOpen then ns.Print("abre la casa de subastas primero.") return end
    if Scanner.state ~= "idle" then ns.Print("ya hay un escaneo en curso.") return end
    if not force and Scanner.AuctionatorReplicates() then
        ns.Print("el escaneo completo lo hace Auctionator y Oroboros lee el mismo resultado: usa su botón de escaneo " ..
                 "(o espera su autoescaneo). Para lanzarlo desde aquí: /oro scan forzar.")
        return
    end
    local ok, left = Scanner.CanFullScan()
    if not ok then
        ns.Print(string.format("escaneo completo disponible en %d:%02d.", math.floor(left / 60), left % 60))
        return
    end
    Scanner.state = "waiting"
    Scanner.auto = auto and true or false
    Scanner.lastReplicate = time()
    OroborosDB.lastReplicate = Scanner.lastReplicate
    if ns.UI then ns.UI.SetScanning(true) end
    if auto then
        ns.Print("escaneo automático: empieza (han pasado 15 min desde el último). Se apaga con /oro set autoscan 0.")
        setStatus("Escaneo automático: esperando datos del servidor…")
    else
        setStatus("Escaneo completo: esperando datos del servidor…")
    end
    C_AuctionHouse.ReplicateItems()
end

-- Una fila del escaneo completo. Además de la compra directa (lo que valora el addon), guarda la puja mínima
-- más baja y las subastas que solo admiten puja. En Forever, el equipo verde sale con puja ≈ precio de
-- vendedor y compra directa mucho más alta, y el «mínimo» no cuadraba con el juego (20/11): las primeras
-- filas raras se guardan tal cual en OroborosDB.replicateSample (sin nombres de jugadores) para revisarlas.
local SAMPLE_MAX = 40
function Scanner.NewReplicateAcc() return { byItem = {}, bids = {}, bidOnly = {}, sample = {}, seenInfo = {} } end

function Scanner.ReadReplicateRow(i, acc)
    local name, _, count, quality, usable, level, levelType, minBid, minIncrement, buyout, bidAmount,
          _, _, _, _, saleStatus, itemID, hasAllInfo = C_AuctionHouse.GetReplicateItemInfo(i)
    if not itemID or not count or count <= 0 then return end
    if minBid and minBid > 0 then
        local unit = minBid / count
        if not acc.bids[itemID] or unit < acc.bids[itemID] then acc.bids[itemID] = unit end
    end
    if not buyout or buyout <= 0 then acc.bidOnly[itemID] = (acc.bidOnly[itemID] or 0) + 1 end
    if #acc.sample < SAMPLE_MAX and (not buyout or buyout <= 0 or (minBid and minBid > 0 and minBid ~= buyout)) then
        acc.sample[#acc.sample + 1] = { itemID = itemID, count = count, quality = quality, usable = usable, level = level,
            levelType = levelType, minBid = minBid, minIncrement = minIncrement, buyout = buyout, bidAmount = bidAmount,
            saleStatus = saleStatus, hasAllInfo = hasAllInfo }
    end
    if buyout and buyout > 0 then
        local list = acc.byItem[itemID]
        if not list then list = {}; acc.byItem[itemID] = list end
        list[#list + 1] = { buyout / count, count }
        if name and not acc.seenInfo[itemID] then
            acc.seenInfo[itemID] = true
            ns.DB.SetItemInfo(itemID, name, quality)
        end
    end
end

-- passive = true cuando el escaneo lo pidió otro addon (Auctionator)
local function readReplicate(passive)
    Scanner.state = "reading"
    Scanner.lastRead = time()
    local label = passive and "Escaneo de Auctionator" or (Scanner.auto and "Escaneo automático" or "Escaneo completo")
    if ns.UI then ns.UI.SetScanning(true) end
    local total = C_AuctionHouse.GetNumReplicateItems()
    local acc, idx = Scanner.NewReplicateAcc(), 0

    local function step()
        if not Scanner.ahOpen then
            Scanner.state, Scanner.auto = "idle", false
            if ns.UI then ns.UI.SetScanning(false) end
            return
        end
        local last = math.min(idx + CHUNK, total)
        for i = idx, last - 1 do                      -- índices base 0
            Scanner.ReadReplicateRow(i, acc)
        end
        idx = last
        setStatus(string.format("%s: %d / %d", label, idx, total))
        if idx < total then
            C_Timer.After(0, step)
        else
            local n = ns.DB.RecordPrices(acc.byItem, true, nil, acc)
            OroborosDB.replicateSample = { t = time(), rows = acc.sample }
            ns.DB.QueueMissingNames()
            Scanner.state, Scanner.auto = "idle", false
            if ns.UI then ns.UI.SetScanning(false) end
            setStatus(string.format("%s leído: %d objetos, %d subastas.", label, n, total))
            ns.Print(string.format("%s: %d objetos (%d subastas). Haz /reload para guardar a disco.", label:lower(), n, total))
            if ns.UI then ns.UI.Refresh() end
        end
    end
    step()
end

local PASSIVE_GAP = 5 * 60          -- el evento puede repetirse: un escaneo ajeno se lee una vez

ns.On("REPLICATE_ITEM_LIST_UPDATE", function()
    if Scanner.state == "waiting" then
        readReplicate(false)
    elseif Scanner.state == "idle" and Scanner.ahOpen and time() - Scanner.lastRead > PASSIVE_GAP then
        -- ReplicateItems pedido por otro addon: leemos el mismo resultado sin pedir otro
        Scanner.lastReplicate = math.max(Scanner.lastReplicate, time())
        OroborosDB.lastReplicate = Scanner.lastReplicate
        readReplicate(true)
    end
end)

----------------------------------------------------------------------
-- Búsqueda puntual de un objeto (para comprar/vender con precio fresco)
----------------------------------------------------------------------
local SORT = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }

-- callback(result) con result = { itemID, commodity = bool, rows = { {unitPrice, qty, auctionID, mine} } }
function Scanner.Search(itemID, callback)
    if not Scanner.ahOpen then ns.Print("abre la casa de subastas primero.") return end
    pending[itemID] = pending[itemID] or {}
    table.insert(pending[itemID], callback)
    C_AuctionHouse.SendSearchQuery(C_AuctionHouse.MakeItemKey(itemID), SORT, true)
end

local function deliver(itemID, result)
    local cbs = pending[itemID]
    pending[itemID] = nil
    -- guardar en la BD como actualización parcial
    local listings = {}
    for _, r in ipairs(result.rows) do
        if not r.mine then listings[#listings + 1] = { r.unitPrice, r.qty } end
    end
    if #listings > 0 then ns.DB.RecordPrices({ [itemID] = listings }, false) end
    ns.DB.SetItemInfo(itemID, nil, nil, result.commodity)
    if cbs then for _, cb in ipairs(cbs) do cb(result) end end
end

ns.On("COMMODITY_SEARCH_RESULTS_UPDATED", function(itemID)
    if not pending[itemID] then return end
    local rows = {}
    for i = 1, C_AuctionHouse.GetNumCommoditySearchResults(itemID) do
        local r = C_AuctionHouse.GetCommoditySearchResultInfo(itemID, i)
        if r then
            rows[#rows + 1] = {
                unitPrice = r.unitPrice, qty = r.quantity, auctionID = r.auctionID,
                mine = (r.numOwnerItems or 0) > 0 and (r.numOwnerItems == r.quantity),
            }
        end
    end
    deliver(itemID, { itemID = itemID, commodity = true, rows = rows })
end)

ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(itemKey)
    local itemID = itemKey and itemKey.itemID
    if not itemID or not pending[itemID] then return end
    local rows = {}
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local r = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if r and r.buyoutAmount and r.buyoutAmount > 0 then
            local q = r.quantity or 1
            rows[#rows + 1] = {
                unitPrice = r.buyoutAmount / q, qty = q, auctionID = r.auctionID,
                buyout = r.buyoutAmount, mine = r.containsOwnerItem,
            }
        end
    end
    table.sort(rows, function(a, b) return a.unitPrice < b.unitPrice end)
    deliver(itemID, { itemID = itemID, commodity = false, rows = rows })
end)

----------------------------------------------------------------------
-- Vendedores: guarda el precio de compra de reactivos (hilo, viales…)
----------------------------------------------------------------------
local function merchantInfo(i)
    if C_MerchantFrame and C_MerchantFrame.GetItemInfo then
        local info = C_MerchantFrame.GetItemInfo(i)
        if info then return info.price, info.stackCount, info.numAvailable, info.hasExtendedCost end
        return nil
    end
    local _, _, price, quantity, numAvailable, _, _, extendedCost = GetMerchantItemInfo(i)
    return price, quantity, numAvailable, extendedCost
end

ns.On("MERCHANT_SHOW", function()
    local n = 0
    for i = 1, GetMerchantNumItems() do
        local itemID = GetMerchantItemID(i)
        local price, stack, available, extended = merchantInfo(i)
        if itemID and price and price > 0 and not extended and available == -1 then
            ns.DB.SetVendorPrice(itemID, price / math.max(1, stack or 1))
            ns.DB.SetItemInfo(itemID)
            n = n + 1
        end
    end
    if n > 0 and ns.UI then ns.UI.SetStatus(string.format("Vendedor: %d precios guardados.", n)) end
end)
