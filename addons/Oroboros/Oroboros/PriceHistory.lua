-- Oroboros: panel de historial de precios al estilo CamelCamelCamel (fase 2, docs/hoja-de-ruta.md)
-- Los datos vienen de Resumen.lua (OroborosResumen), generado fuera del juego por tools/oroboros_summary.py.
-- Solo se leen: el panel no escribe nada en Oroboros.lua.
local _, ns = ...
local PH = {}
ns.PriceHistory = PH

local WEEKS, DAYS = 13, 14
local BAR = { 0.84, 0.67, 0.24, 0.9 }

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
-- Ventana
----------------------------------------------------------------------
local W, H = 300, 230

local function bars(f, n, x0, y0, w, gap, hmax)
    local t = { hmax = hmax }
    for k = 1, n do
        local b = f:CreateTexture(nil, "ARTWORK")
        b:SetColorTexture(BAR[1], BAR[2], BAR[3], BAR[4])
        b:SetPoint("BOTTOMLEFT", f, "BOTTOMLEFT", x0 + (k - 1) * (w + gap), y0)
        b:SetWidth(w)
        t[k] = b
    end
    return t
end

local function fill(t, values)
    local hi = 0
    for k = 1, #t do if values[k] and values[k] > hi then hi = values[k] end end
    for k = 1, #t do
        local v = values[k]
        if v and hi > 0 then
            t[k]:SetHeight(math.max(2, t.hmax * v / hi))
            t[k]:Show()
        else
            t[k]:Hide()
        end
    end
end

local function build()
    if PH.frame then return PH.frame end
    local f = CreateFrame("Frame", "OroborosPriceFrame", UIParent, "BasicFrameTemplateWithInset")
    f:SetSize(W, H)
    f:SetFrameStrata("HIGH")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosPriceFrame")   -- se cierra con Escape
    f.title = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    f.title:SetPoint("TOP", 0, -5)
    f.lines = {}
    for k = 1, 4 do
        local fs = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        fs:SetPoint("TOPLEFT", 12, -30 - (k - 1) * 16)
        fs:SetWidth(W - 24)
        fs:SetJustifyH("LEFT")
        f.lines[k] = fs
    end
    f.weekLabel = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    f.weekLabel:SetPoint("BOTTOMLEFT", 12, 92)
    f.weekLabel:SetText("13 semanas")
    f.weekBars = bars(f, WEEKS, 12, 50, 18, 3, 40)
    f.dayLabel = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    f.dayLabel:SetPoint("BOTTOMLEFT", 12, 38)
    f.dayLabel:SetText("14 días")
    f.dayBars = bars(f, DAYS, 12, 10, 16, 3, 24)
    PH.frame = f
    return f
end

-- Debajo de la ventana de Oroboros si está abierta (las dos van a la derecha de la subasta);
-- si no, a la derecha de la subasta; si tampoco, en el centro.
function PH.AnchorTarget()
    if ns.UI and ns.UI.frame and ns.UI.frame:IsShown() then return "OroborosFrame" end
    if AuctionHouseFrame and AuctionHouseFrame.IsShown and AuctionHouseFrame:IsShown() then return "AuctionHouseFrame" end
    return nil
end

local function anchor(f)
    f:ClearAllPoints()
    local target = PH.AnchorTarget()
    if target == "OroborosFrame" then
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
    local L = PH.Lines(itemID, live)
    f.title:SetText(L[1] or ("item:" .. itemID))
    for k = 1, 4 do f.lines[k]:SetText(L[k + 1] or "") end
    local s = PH.Get(itemID)
    fill(f.weekBars, s and s.weeks or {})
    fill(f.dayBars, s and s.days or {})
    anchor(f)
    f:Show()
end

function PH.Hide()
    if PH.frame then PH.frame:Hide() end
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

-- /oro precio debug: lo que devolvió el juego en la última búsqueda
function PH.Debug()
    if not PH.lastRows or #PH.lastRows == 0 then ns.Print("sin búsquedas todavía: selecciona un objeto en la subasta.") return end
    ns.Print(string.format("última búsqueda: %s (en vivo %s)", ns.DB.ItemName(PH.current or 0), ns.Money(PH.live)))
    for i, r in ipairs(PH.lastRows) do
        ns.Print(string.format("  %d. %s × %s%s", i, tostring(r[1]), tostring(r[2]), r[3] and " (propia)" or ""))
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
    local rows = {}
    for i = 1, C_AuctionHouse.GetNumItemSearchResults(itemKey) do
        local r = C_AuctionHouse.GetItemSearchResultInfo(itemKey, i)
        if r and r.buyoutAmount and r.buyoutAmount > 0 then
            rows[#rows + 1] = { r.buyoutAmount / (r.quantity or 1), r.quantity or 1, r.containsOwnerItem and true or false }
        end
    end
    table.sort(rows, function(a, b) return a[1] < b[1] end)
    remember(rows)
    PH.Show(itemKey.itemID, PH.LivePrice(rows))
end)

ns.On("AUCTION_HOUSE_CLOSED", PH.Hide)
