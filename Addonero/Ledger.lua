-- Addonero: libro de compras y ventas reales.
-- Registra cualquier compra en subasta (hecha con la ruta o a mano) y las ventas
-- que llegan por correo, para que el planificador sepa qué tienes y a cuánto lo compraste.
local _, ns = ...
local Ledger = {}
ns.Ledger = Ledger

local quote            -- último precio que dio el servidor para una compra de commodities
local pendingCommodity -- { item, qty, unit, total }
local auctions = {}    -- [auctionID] = { item, qty }   (resultados de búsqueda vistos)
local pendingBids = {} -- [auctionID] = { item, qty, total }

ns.On("COMMODITY_PRICE_UPDATED", function(unitPrice, totalPrice)
    quote = { unit = unitPrice, total = totalPrice }
end)

if C_AuctionHouse and hooksecurefunc then
    hooksecurefunc(C_AuctionHouse, "ConfirmCommoditiesPurchase", function(itemID, quantity)
        pendingCommodity = { item = itemID, qty = quantity, unit = quote and quote.unit, total = quote and quote.total }
    end)
    hooksecurefunc(C_AuctionHouse, "PlaceBid", function(auctionID, amount)
        local a = auctions[auctionID]
        if a then pendingBids[auctionID] = { item = a.item, qty = a.qty, total = amount } end
    end)
end

ns.On("COMMODITY_PURCHASE_SUCCEEDED", function()
    local p = pendingCommodity
    pendingCommodity = nil
    if p then ns.DB.AddLedger("BUY", p.item, p.qty, p.unit or (p.total and p.total / p.qty), p.total, "subasta") end
end)
ns.On("COMMODITY_PURCHASE_FAILED", function() pendingCommodity = nil end)

ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(itemKey)
    if not itemKey or not itemKey.itemID then return end
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local r = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if r and r.auctionID then auctions[r.auctionID] = { item = itemKey.itemID, qty = r.quantity or 1 } end
    end
end)

ns.On("AUCTION_HOUSE_PURCHASE_COMPLETED", function(auctionID)
    local p = pendingBids[auctionID]
    pendingBids[auctionID] = nil
    if p then ns.DB.AddLedger("BUY", p.item, p.qty, p.total / p.qty, p.total, "subasta") end
end)

ns.On("AUCTION_HOUSE_CLOSED", function() wipe(auctions); wipe(pendingBids); pendingCommodity = nil end)

-- Ventas: facturas de la subasta en el correo. El correo solo da el nombre del objeto.
local function itemByName(name)
    for id, it in pairs(AddoneroDB.items) do
        if it.n == name then return id end
    end
end

ns.On("MAIL_INBOX_UPDATE", function()
    if not GetInboxNumItems or not GetInboxInvoiceInfo then return end
    local seen, now = AddoneroDB.seenMail, time()
    for k, exp in pairs(seen) do if exp < now then seen[k] = nil end end
    for i = 1, GetInboxNumItems() do
        local kind, name, _, bid, _, _, consignment, _, _, _, count = GetInboxInvoiceInfo(i)
        if kind == "seller" and name and bid and bid > 0 then
            local _, _, _, _, _, _, daysLeft = GetInboxHeaderInfo(i)
            local expiry = now + (daysLeft or 30) * 86400
            local bucket = math.floor(expiry / 600)
            local base = name .. "|" .. bid .. "|" .. (count or 1) .. "|"
            if not (seen[base .. bucket] or seen[base .. (bucket - 1)] or seen[base .. (bucket + 1)]) then
                seen[base .. bucket] = expiry
                local id = itemByName(name)
                if id then
                    local qty = (count and count > 0) and count or 1
                    ns.DB.AddLedger("SELL", id, qty, bid / qty, bid - (consignment or 0), "correo")
                end
            end
        end
    end
end)
