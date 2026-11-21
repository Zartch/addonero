-- Oroboros: panel de historial de precios al estilo CamelCamelCamel (fase 2, docs/hoja-de-ruta.md)
-- Los datos vienen de Resumen.lua (OroborosResumen), generado fuera del juego por tools/oroboros_summary.py.
-- Solo se leen: el panel no escribe nada en Oroboros.lua.
local _, ns = ...
local PH = {}
ns.PriceHistory = PH

local WEEKS, DAYS = 13, 14

----------------------------------------------------------------------
-- Datos
----------------------------------------------------------------------
local function split(s, sep)
    local out, i = {}, 1
    while true do
        local j = string.find(s, sep, i, true)
        if not j then out[#out + 1] = string.sub(s, i); return out end
        out[#out + 1] = string.sub(s, i, j - 1)
        i = j + 1
    end
end

local function list(s, n)
    local out, parts = {}, split(s or "", ",")
    for k = 1, n do out[k] = tonumber(parts[k] or "") end
    return out
end

-- hoy;med7;med30;med90;min;diaMin;max;diaMax;franjaVenta;franjaBarata;semanas;dias;ultimoDia
function PH.Parse(s)
    if type(s) ~= "string" then return nil end
    local f = split(s, ";")
    return {
        today = tonumber(f[1] or ""), avg7 = tonumber(f[2] or ""), avg30 = tonumber(f[3] or ""), avg90 = tonumber(f[4] or ""),
        low = tonumber(f[5] or ""), lowDay = tonumber(f[6] or ""), high = tonumber(f[7] or ""), highDay = tonumber(f[8] or ""),
        sellBand = tonumber(f[9] or ""), cheapBand = tonumber(f[10] or ""),
        weeks = list(f[11], WEEKS), days = list(f[12], DAYS), lastDay = tonumber(f[13] or ""),
    }
end

function PH.Get(itemID)
    local r = OroborosResumen
    local m = type(r) == "table" and type(r.markets) == "table" and r.markets[ns.MarketKey()]
    if not m or not itemID then return nil end
    return PH.Parse(m[itemID])
end

local function ddmm(d)
    if not d then return "?" end
    return string.format("%02d/%02d", d % 100, math.floor(d / 100) % 100)
end

local function bandTxt(b)
    return string.format("de %d a %d h", b * 4, b * 4 + 4)
end

-- Textos del panel (sin dibujar): nombre, hoy, mínimo/máximo, medias y franjas
function PH.Lines(itemID, live)
    local L = { ns.DB.ItemName(itemID) }
    local s = PH.Get(itemID)
    local now = live or (s and s.today)
    if not s then
        if now then L[#L + 1] = "Hoy " .. ns.Money(now) end
        L[#L + 1] = "Sin historial: genera el plan."
        return L
    end
    local today = "Hoy " .. ns.Money(now)
    if now and s.avg30 and s.avg30 > 0 then
        local d = (now / s.avg30 - 1) * 100
        if math.abs(d) < 2 then
            today = today .. " · en su media de 30 días"
        else
            today = today .. string.format(" · un %d %% por %s de su media de 30 días",
                math.floor(math.abs(d) + 0.5), d < 0 and "debajo" or "encima")
        end
    end
    L[#L + 1] = today
    L[#L + 1] = string.format("Mínimo %s (%s) · Máximo %s (%s)", ns.Money(s.low), ddmm(s.lowDay), ns.Money(s.high), ddmm(s.highDay))
    L[#L + 1] = string.format("Media 7 d %s · 30 d %s · 90 d %s", ns.Money(s.avg7), ns.Money(s.avg30), ns.Money(s.avg90))
    local bands = {}
    if s.sellBand then bands[#bands + 1] = "Se vende más " .. bandTxt(s.sellBand) end
    if s.cheapBand then bands[#bands + 1] = (#bands > 0 and "más barato " or "Más barato ") .. bandTxt(s.cheapBand) end
    if #bands > 0 then L[#L + 1] = table.concat(bands, " · ") end
    return L
end

----------------------------------------------------------------------
-- Modelo del panel (lo que se dibuja, sin dibujarlo)
----------------------------------------------------------------------
local function dayTime(d)    -- AAAAMMDD → hora (mediodía) de ese día
    if not d then return nil end
    return time({ year = math.floor(d / 10000), month = math.floor(d / 100) % 100, day = d % 100, hour = 12 })
end

function PH.Model(itemID, live)
    local s = PH.Get(itemID)
    local it = OroborosDB and OroborosDB.items and OroborosDB.items[itemID] or {}
    local m = { name = ns.DB.ItemName(itemID), quality = it.q, hasHistory = s ~= nil }
    m.today = live or (s and s.today)
    if not s then return m end
    if m.today and s.avg30 and s.avg30 > 0 then
        local d = (m.today / s.avg30 - 1) * 100
        m.diffPct = d >= 0 and math.floor(d + 0.5) or -math.floor(-d + 0.5)
        m.tone = (m.diffPct <= -2 and "good") or (m.diffPct >= 2 and "bad") or "neutral"
    end
    m.stats = {
        { label = "MEDIA 7 D", value = ns.Coin(s.avg7) },
        { label = "MEDIA 30 D", value = ns.Coin(s.avg30) },
        { label = "MEDIA 90 D", value = ns.Coin(s.avg90) },
        { label = "MÍNIMO", value = ns.Coin(s.low), sub = ddmm(s.lowDay) },
        { label = "MÁXIMO", value = ns.Coin(s.high), sub = ddmm(s.highDay) },
    }
    local last = dayTime(s.lastDay)
    m.days, m.weeks = {}, {}
    for k = 1, DAYS do
        m.days[k] = { label = last and date("%d/%m", last - (DAYS - k) * 86400) or "", value = s.days[k] }
    end
    local monday = last and (last - ((tonumber(date("%w", last)) + 6) % 7) * 86400)
    for k = 1, WEEKS do
        m.weeks[k] = { label = monday and ("semana del " .. date("%d/%m", monday - (WEEKS - k) * 7 * 86400)) or "", value = s.weeks[k] }
    end
    local bands = {}
    if s.sellBand then bands[#bands + 1] = "Se vende más " .. bandTxt(s.sellBand) end
    if s.cheapBand then bands[#bands + 1] = (#bands > 0 and "más barato " or "Más barato ") .. bandTxt(s.cheapBand) end
    m.bandsText = #bands > 0 and table.concat(bands, " · ") or nil
    m.avg30 = s.avg30
    return m
end

----------------------------------------------------------------------
-- Ventana
----------------------------------------------------------------------
local W, PAD = 330, 12

local function build()
    if PH.frame then return PH.frame end
    local S = ns.Style
    local f = CreateFrame("Frame", "OroborosPriceFrame", UIParent, "BackdropTemplate")
    f:SetSize(W, 200)
    f:SetFrameStrata("HIGH")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosPriceFrame")   -- se cierra con Escape
    local h = S.Panel(f, "")
    f.icon = h:CreateTexture(nil, "ARTWORK")
    f.icon:SetSize(18, 18)
    f.icon:SetPoint("LEFT", 8, 0)
    h.title:ClearAllPoints()
    h.title:SetPoint("LEFT", f.icon, "RIGHT", 6, 0)
    h.title:SetPoint("RIGHT", -30, 0)

    f.todayLabel = S.Text(f, "label"); f.todayLabel:SetText("HOY")
    f.today = S.Text(f, "big")
    f.diff = S.Text(f, "small")
    f.stat = {}
    for k = 1, 5 do
        f.stat[k] = { label = S.Text(f, "label"), value = S.Text(f, "value"), sub = S.Text(f, "muted") }
    end
    f.div1 = S.Divider(f)
    f.dayTitle = S.Text(f, "label"); f.dayTitle:SetText("PRECIO · 14 DÍAS")
    f.legend = S.Text(f, "muted")
    f.legend:SetText(S.Hex("accent", "— precio") .. "   " .. S.Hex("label", "- - media 30 d"))
    f.legend:SetJustifyH("RIGHT")
    f.dayChart = ns.Chart.New(f, W - 2 * PAD, 96, "line")
    f.weekTitle = S.Text(f, "label"); f.weekTitle:SetText("PRECIO · 13 SEMANAS")
    f.weekChart = ns.Chart.New(f, W - 2 * PAD, 76, "bar")
    f.bands = S.Text(f, "small")
    f.noHistory = S.Text(f, "small")
    f.noHistory:SetText("Sin historial todavía: genera el plan (o deja que lo haga el vigilante) y haz /reload.")
    S.Color(f.noHistory, "label")
    PH.frame = f
    return f
end

-- Coloca un elemento debajo del anterior; devuelve la nueva posición vertical
local function place(f, region, y, x, h)
    region:ClearAllPoints()
    region:SetPoint("TOPLEFT", f, "TOPLEFT", x or PAD, y)
    if region.SetWidth and not region.SetData then region:SetWidth(W - 2 * PAD - (x and x - PAD or 0)) end
    region:Show()
    return y - (h or 16)
end

local function render(f, m)
    local S = ns.Style
    f.header.title:SetText(m.name or "")
    local r, g, b = 1, 1, 1
    if m.quality and C_Item and C_Item.GetItemQualityColor then
        local ok, qr, qg, qb = pcall(C_Item.GetItemQualityColor, m.quality)
        if ok and qr then r, g, b = qr, qg, qb end
    elseif m.quality and ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[m.quality] then
        local q = ITEM_QUALITY_COLORS[m.quality]; r, g, b = q.r, q.g, q.b
    end
    f.header.title:SetTextColor(r, g, b)
    local icon = C_Item and C_Item.GetItemIconByID and C_Item.GetItemIconByID(PH.current) or (GetItemIcon and GetItemIcon(PH.current))
    if icon then f.icon:SetTexture(icon); f.icon:Show() else f.icon:Hide() end

    local y = -38
    y = place(f, f.todayLabel, y, nil, 14)
    f.today:ClearAllPoints(); f.today:SetPoint("TOPLEFT", PAD, y)
    f.today:SetText(m.today and ns.Coin(m.today) or "sin precio")
    S.Color(f.today, m.tone == "good" and "good" or (m.tone == "bad" and "bad" or "value"))
    f.diff:ClearAllPoints(); f.diff:SetPoint("BOTTOMLEFT", f.today, "BOTTOMRIGHT", 10, 2)
    if m.diffPct then
        f.diff:SetText(string.format("%s%d %% frente a su media de 30 días", m.diffPct > 0 and "+" or "", m.diffPct))
        S.Color(f.diff, m.tone == "good" and "good" or (m.tone == "bad" and "bad" or "label"))
        f.diff:Show()
    else
        f.diff:Hide()
    end
    y = y - 32

    local parts = { f.div1, f.dayTitle, f.legend, f.dayChart, f.weekTitle, f.weekChart, f.bands }
    if not m.hasHistory then
        for _, s in ipairs(f.stat) do s.label:Hide(); s.value:Hide(); s.sub:Hide() end
        for _, p in ipairs(parts) do p:Hide() end
        y = place(f, f.noHistory, y - 4, nil, 34)
        f:SetHeight(-y + PAD)
        return
    end
    f.noHistory:Hide()

    -- Cifras: 3 columnas (medias) y 2 columnas (mínimo y máximo)
    local colW3, colW2 = (W - 2 * PAD) / 3, (W - 2 * PAD) / 2
    for k, st in ipairs(m.stats) do
        local cell = f.stat[k]
        local row, col, cw = (k <= 3) and 0 or 1, (k <= 3) and (k - 1) or (k - 4), (k <= 3) and colW3 or colW2
        local cx, cy = PAD + col * cw, y - row * 38
        cell.label:ClearAllPoints(); cell.label:SetPoint("TOPLEFT", f, "TOPLEFT", cx, cy); cell.label:SetText(st.label); cell.label:Show()
        cell.value:ClearAllPoints(); cell.value:SetPoint("TOPLEFT", f, "TOPLEFT", cx, cy - 13); cell.value:SetText(st.value); cell.value:Show()
        cell.sub:ClearAllPoints(); cell.sub:SetPoint("BOTTOMLEFT", cell.value, "BOTTOMRIGHT", 6, 1)
        cell.sub:SetText(st.sub or ""); cell.sub:Show()
    end
    y = y - 82

    f.div1:ClearAllPoints(); f.div1:SetPoint("TOPLEFT", PAD, y); f.div1:SetPoint("TOPRIGHT", -PAD, y); f.div1:Show()
    y = y - 10
    f.dayTitle:ClearAllPoints(); f.dayTitle:SetPoint("TOPLEFT", PAD, y); f.dayTitle:Show()
    f.legend:ClearAllPoints(); f.legend:SetPoint("TOPRIGHT", -PAD, y); f.legend:Show()
    y = y - 16
    local money = function(p) return p.label, p.value and ns.Coin(p.value) or "sin datos" end
    f.dayChart:ClearAllPoints(); f.dayChart:SetPoint("TOPLEFT", PAD, y); f.dayChart:Show()
    f.dayChart:SetData(m.days, m.avg30, money)
    y = y - 96 - 10
    f.weekTitle:ClearAllPoints(); f.weekTitle:SetPoint("TOPLEFT", PAD, y); f.weekTitle:Show()
    y = y - 16
    f.weekChart:ClearAllPoints(); f.weekChart:SetPoint("TOPLEFT", PAD, y); f.weekChart:Show()
    f.weekChart:SetData(m.weeks, m.avg30, money)
    y = y - 76 - 8
    if m.bandsText then
        y = place(f, f.bands, y, nil, 18)
        f.bands:SetText("Franjas: " .. m.bandsText)
    else
        f.bands:Hide()
    end
    f:SetHeight(-y + PAD)
end

-- Debajo de la ventana de Oroboros si está abierta (las dos van a la derecha de la subasta);
-- si no, a la derecha de la subasta; si tampoco, en el centro.
function PH.AnchorTarget()
    if ns.Inventory and ns.Inventory.frame and ns.Inventory.frame:IsShown() then return "OroborosInventoryFrame" end
    if ns.UI and ns.UI.frame and ns.UI.frame:IsShown() then return "OroborosFrame" end
    if AuctionHouseFrame and AuctionHouseFrame.IsShown and AuctionHouseFrame:IsShown() then return "AuctionHouseFrame" end
    return nil
end

local function anchor(f)
    f:ClearAllPoints()
    local target = PH.AnchorTarget()
    if target == "OroborosInventoryFrame" then
        f:SetPoint("TOPLEFT", ns.Inventory.frame, "TOPRIGHT", 4, 0)
    elseif target == "OroborosFrame" then
        f:SetPoint("TOPLEFT", ns.UI.frame, "BOTTOMLEFT", 0, -4)
    elseif target == "AuctionHouseFrame" then
        f:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 4, 0)
    else
        f:SetPoint("CENTER")
    end
end

function PH.Show(itemID, live)
    if not itemID then return end
    local f = build()
    PH.current, PH.live = itemID, live
    render(f, PH.Model(itemID, live))
    anchor(f)
    f:Show()
end

-- Qué profesiones usan el objeto como componente (de ProfessionDB, vía Resumen.lua): "Herrería (3), …"
function PH.Uses(itemID)
    local r = OroborosResumen
    return type(r) == "table" and type(r.uses) == "table" and r.uses[itemID] or nil
end

-- Líneas que Oroboros añade al tooltip. La primera, en corto: valor por unidad (compra directa de este objeto)
-- ±% frente a la media de 30 días y fecha; si es una pila (count > 1), lo que vale entera.
-- Ej.: «Oroboros c/u   38s 24c (1g) +161 %  21/11 · ×20 = 7g 64s». Después, «Lo usan: …». { {izq, der}, … }
function PH.TooltipLines(itemID, name, count)
    local L = {}
    local info = PH.TooltipInfo(itemID, name)
    local S = ns.Style
    if info then
        local right = info.price
        if info.buy and ns.Coin(info.buy) ~= info.price then right = right .. " (" .. ns.Coin(info.buy) .. ")" end
        if info.diffPct then
            right = right .. " " .. S.Hex(info.tone == "good" and "good" or (info.tone == "bad" and "bad" or "label"),
                string.format("%s%d %%", info.diffPct > 0 and "+" or "", info.diffPct))
        end
        if info.t then right = right .. " " .. S.Hex("muted", date("%d/%m", info.t)) end
        if count and count > 1 and info.value then
            right = right .. S.Hex("label", " · ×" .. count .. " = ") .. ns.Coin(info.value * count)
        end
        L[#L + 1] = { "Oroboros c/u", right }
    end
    local uses = PH.Uses(itemID)
    if uses then L[#L + 1] = { "Lo usan", uses } end
    return L
end

function PH.Hide()
    if PH.frame then PH.frame:Hide() end
end

-- Para el tooltip del objeto: precio guardado, diferencia con su media de 30 días y compra directa.
-- name: el nombre del objeto que se está viendo (con su sufijo); si hay precio de esa variante, manda.
function PH.TooltipInfo(itemID, name)
    local p = ns.DB.GetPrice(itemID)
    local s = PH.Get(itemID)
    local v = ns.DB.GetVariant(name, itemID)
    local live = p and (p.qty or 0) > 0
    local now = (live and (p.mv or p.min)) or (s and s.today) or (v and v.min)
    if not now then return nil end
    local info = { price = ns.Coin(now), value = now }
    if v then
        info.buy, info.bid, info.t, info.variant = v.min, v.bid, v.t, true
    elseif live then
        info.buy, info.bid, info.t = p.min, p.bid, p.t
    end
    if s and s.avg30 and s.avg30 > 0 then
        local d = (now / s.avg30 - 1) * 100
        info.diffPct = d >= 0 and math.floor(d + 0.5) or -math.floor(-d + 0.5)
        info.tone = (info.diffPct <= -2 and "good") or (info.diffPct >= 2 and "bad") or "neutral"
    end
    return info
end

-- Alt + clic en cualquier objeto (bolsas, banco, enlaces del chat…): su historial, sin estar en la subasta
if hooksecurefunc and HandleModifiedItemClick then
    hooksecurefunc("HandleModifiedItemClick", function(link)
        if not (IsAltKeyDown and IsAltKeyDown()) or type(link) ~= "string" then return end
        local id = tonumber(link:match("item:(%d+)"))
        if not id then return end
        local p = ns.DB.GetPrice(id)
        PH.Show(id, p and (p.qty or 0) > 0 and p.min or nil)
    end)
end

----------------------------------------------------------------------
-- Se abre al seleccionar un objeto en la subasta (la búsqueda que lanza el juego o Auctionator)
----------------------------------------------------------------------
-- Precio en vivo: el más barato de otros vendedores (la primera fila puede ser una subasta propia)
-- rows: { {unitPrice, qty, mine} }
function PH.LivePrice(rows)
    local best
    for _, r in ipairs(rows or {}) do
        if r[1] and r[1] > 0 and (r[2] or 0) > 0 and not r[3] and (not best or r[1] < best) then best = r[1] end
    end
    return best
end

local function remember(rows)
    PH.lastRows = {}
    for i = 1, math.min(5, #rows) do PH.lastRows[i] = rows[i] end
end

PH.lastRaw = nil

-- /oro precio debug: lo que devolvió el juego en la última búsqueda (con puja y compra directa de cada subasta)
function PH.Debug()
    if not PH.lastRows or #PH.lastRows == 0 then ns.Print("sin búsquedas todavía: selecciona un objeto en la subasta.") return end
    ns.Print(string.format("última búsqueda: %s (en vivo %s)", ns.DB.ItemName(PH.current or 0), ns.Money(PH.live)))
    for i, r in ipairs(PH.lastRows) do
        ns.Print(string.format("  %d. %s × %s%s", i, tostring(r[1]), tostring(r[2]), r[3] and " (propia)" or ""))
    end
    for i, r in ipairs(PH.lastRaw or {}) do
        ns.Print(string.format("  subasta %d: ×%s · puja mínima %s · puja actual %s · compra directa %s", i, tostring(r.quantity),
            tostring(r.minBid), tostring(r.bidAmount), tostring(r.buyoutAmount)))
    end
end

ns.On("COMMODITY_SEARCH_RESULTS_UPDATED", function(itemID)
    if not (ns.Scanner and ns.Scanner.ahOpen) or not itemID then return end
    local rows = {}
    for i = 1, C_AuctionHouse.GetNumCommoditySearchResults(itemID) do
        local r = C_AuctionHouse.GetCommoditySearchResultInfo(itemID, i)
        if r then
            rows[#rows + 1] = { r.unitPrice, r.quantity, (r.numOwnerItems or 0) > 0 and r.numOwnerItems == r.quantity }
        end
    end
    remember(rows)
    PH.Show(itemID, PH.LivePrice(rows))
end)

ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(itemKey)
    if not (ns.Scanner and ns.Scanner.ahOpen) or not itemKey or not itemKey.itemID then return end
    local rows, raw = {}, {}
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local r = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if r and #raw < 8 then
            raw[#raw + 1] = { quantity = r.quantity, minBid = r.minBid, bidAmount = r.bidAmount, buyoutAmount = r.buyoutAmount }
        end
        if r and r.buyoutAmount and r.buyoutAmount > 0 then
            rows[#rows + 1] = { r.buyoutAmount / (r.quantity or 1), r.quantity or 1, r.containsOwnerItem and true or false }
        end
    end
    PH.lastRaw = raw
    if OroborosDB then OroborosDB.searchSample = { t = time(), itemID = itemKey.itemID, rows = raw } end
    -- compra directa y puja más baratas de cada nombre (sufijo) que ha salido, sin contar las tuyas
    local byName = {}
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local r = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        local name = r and type(r.itemLink) == "string" and r.itemLink:match("%[(.-)%]")
        if name and not r.containsOwnerItem then
            local q = r.quantity or 1
            local v = byName[name] or { id = itemKey.itemID, n = 0 }
            byName[name] = v
            if r.buyoutAmount and r.buyoutAmount > 0 and (not v.min or r.buyoutAmount / q < v.min) then v.min = r.buyoutAmount / q end
            if r.minBid and r.minBid > 0 and (not v.bid or r.minBid / q < v.bid) then v.bid = r.minBid / q end
            v.n = v.n + q
        end
    end
    if OroborosDB then for name, v in pairs(byName) do ns.DB.SetVariant(name, v) end end
    table.sort(rows, function(a, b) return a[1] < b[1] end)
    remember(rows)
    PH.Show(itemKey.itemID, PH.LivePrice(rows))
end)

ns.On("AUCTION_HOUSE_CLOSED", PH.Hide)
