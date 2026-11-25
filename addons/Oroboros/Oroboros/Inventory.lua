-- Oroboros: ventana «Lo que tienes» (docs/planes/2026-11-20-inventario-y-alt-clic.md)
-- Todos los personajes: bolsas, banco (el último guardado) y banco de banda, con valor y tendencia.
local _, ns = ...
local Inv = {}
ns.Inventory = Inv

local LOC_TXT = { bags = "bolsas", bank = "banco", warband = "banda" }

-- Precio unitario: subasta si hay unidades publicadas; si no, el «hoy» del resumen; si no, el vendedor
function Inv.UnitValue(id)
    local p = ns.DB.GetPrice(id)
    if p and (p.qty or 0) > 0 and (p.mv or p.min) then return p.mv or p.min, "subasta" end
    local s = ns.PriceHistory and ns.PriceHistory.Get(id)
    if s and s.today then return s.today, "historial" end
    local it = OroborosDB.items[id]
    if it and it.s and it.s > 0 then return it.s, "vendedor" end
    return 0, nil
end

-- Modelo: filas { id, name, count, unit, src, value, where, places = { {sitio, uds} }, diffPct, tone, days } y el total.
-- loc: nil = todo; "bags", "bank" o "warband" = solo ese sitio (de todos los personajes).
function Inv.Rows(filter, loc)
    filter = type(filter) == "string" and filter:lower() or ""
    local agg = {}
    local function add(id, n, who, place)
        if not id or not n or n <= 0 or (loc and place ~= loc) then return end
        local a = agg[id]
        if not a then a = { count = 0, where = {} }; agg[id] = a end
        a.count = a.count + n
        local key = who and (who .. ": " .. LOC_TXT[place]) or LOC_TXT[place]
        a.where[key] = (a.where[key] or 0) + n
    end
    local nChars = 0
    for _ in pairs(OroborosDB.chars or {}) do nChars = nChars + 1 end
    for ck, c in pairs(OroborosDB.chars or {}) do
        local who = nChars > 1 and ck:match("^([^%-]+)") or nil
        for id, n in pairs(c.bags or {}) do add(id, n, who, "bags") end
        for id, n in pairs(c.bank or {}) do add(id, n, who, "bank") end
    end
    if OroborosDB.warband then
        for id, n in pairs(OroborosDB.warband.items or {}) do add(id, n, nil, "warband") end
    end
    local rows, total = {}, 0
    for id, a in pairs(agg) do
        local name = ns.DB.ItemName(id) or ("item:" .. id)
        if filter == "" or name:lower():find(filter, 1, true) then
            local unit, src = Inv.UnitValue(id)
            local where, places = {}, {}
            for k in pairs(a.where) do where[#where + 1] = k end
            table.sort(where)
            for i, k in ipairs(where) do places[i] = { k, a.where[k] } end
            local s = ns.PriceHistory and ns.PriceHistory.Get(id)
            local diff, tone
            if s and s.avg30 and s.avg30 > 0 and unit > 0 and src ~= "vendedor" then
                local d = (unit / s.avg30 - 1) * 100
                diff = d >= 0 and math.floor(d + 0.5) or -math.floor(-d + 0.5)
                tone = (diff <= -2 and "good") or (diff >= 2 and "bad") or "neutral"
            end
            local r = { id = id, name = name, count = a.count, unit = unit, src = src, value = unit * a.count,
                        where = table.concat(where, ", "), places = places, diffPct = diff, tone = tone, days = s and s.days or nil }
            rows[#rows + 1] = r
            total = total + r.value
        end
    end
    table.sort(rows, function(x, y)
        if x.value ~= y.value then return x.value > y.value end
        return x.name < y.name
    end)
    return rows, total
end


----------------------------------------------------------------------
-- Ventana: cuadrícula de iconos grandes, como las bolsas y el banco
----------------------------------------------------------------------
local COLS, ROWS_VIS, SLOT, GAP, PAD = 12, 8, 40, 4, 12
local TOP = -84                                     -- y de la primera fila de huecos
local GRID_W = COLS * (SLOT + GAP) - GAP
local TABS = { { nil, "Todo" }, { "bags", "Bolsas" }, { "bank", "Banco" }, { "warband", "Banda" } }
local QUESTION = "Interface\\Icons\\INV_Misc_QuestionMark"

-- Cantidad en la esquina del hueco: como mucho 4 cifras («12k» a partir de 10 000)
function Inv.CountText(n)
    if not n or n <= 1 then return "" end
    if n >= 10000 then return string.format("%dk", math.floor(n / 1000)) end
    return tostring(n)
end

-- Líneas de Oroboros bajo el tooltip del objeto: cuántas tienes, cuánto valen y dónde están.
-- El precio por unidad y «Lo usan» ya los pone el tooltip general (Professions.lua). { {izq, der}, … }
function Inv.TooltipLines(d)
    local S = ns.Style
    local L = {}
    local total = d.value > 0 and ns.Coin(d.value) or S.Hex("muted", "sin precio")
    if d.src == "vendedor" then total = total .. S.Hex("muted", " (vendedor)") end
    L[#L + 1] = { "Tienes " .. d.count, total }
    for _, p in ipairs(d.places or {}) do L[#L + 1] = { "   " .. p[1], tostring(p[2]) } end
    return L
end

local function qualityColor(id)
    local it = OroborosDB.items and OroborosDB.items[id]
    local q = it and it.q
    if not q and C_Item and C_Item.GetItemQualityByID then
        local ok, v = pcall(C_Item.GetItemQualityByID, id); if ok then q = v end
    end
    if not q or q < 2 then return nil end            -- gris y blanco: borde normal
    if C_Item and C_Item.GetItemQualityColor then
        local ok, r, g, b = pcall(C_Item.GetItemQualityColor, q)
        if ok and r then return { r, g, b, 1 } end
    end
    local c = ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[q]
    return c and { c.r, c.g, c.b, 1 } or nil
end

-- Borde del hueco: color de la calidad del objeto, o el normal
local function border(b, c)
    if b.SetBackdropBorderColor then b:SetBackdropBorderColor(unpack(c or ns.Style.C.border)) end
end

local function showTip(b)
    local d = b.data
    if not d or not GameTooltip then return end
    local S = ns.Style
    GameTooltip:SetOwner(b, "ANCHOR_RIGHT")
    if GameTooltip.SetItemByID then GameTooltip:SetItemByID(d.id) else GameTooltip:SetText(d.name, 1, 1, 1) end
    GameTooltip:AddLine(" ")
    for i, l in ipairs(Inv.TooltipLines(d)) do
        local c = i == 1 and S.C.accent or S.C.label
        GameTooltip:AddDoubleLine(l[1], l[2], c[1], c[2], c[3], 1, 1, 1)
    end
    GameTooltip:AddLine("Clic: historial de precios · Mayús+clic: enlazar", S.C.muted[1], S.C.muted[2], S.C.muted[3])
    GameTooltip:Show()
end

local function makeSlot(f, k)
    local S = ns.Style
    local col, row = (k - 1) % COLS, math.floor((k - 1) / COLS)
    local b = CreateFrame("Button", nil, f, "BackdropTemplate")
    b:SetSize(SLOT, SLOT)
    b:SetPoint("TOPLEFT", PAD + col * (SLOT + GAP), TOP - row * (SLOT + GAP))
    S.Backdrop(b, S.C.section, S.C.border)
    b.icon = b:CreateTexture(nil, "ARTWORK")
    b.icon:SetPoint("TOPLEFT", 2, -2); b.icon:SetPoint("BOTTOMRIGHT", -2, 2)
    b.icon:SetTexCoord(0.07, 0.93, 0.07, 0.93)       -- sin el marco gris del icono
    b.hl = b:CreateTexture(nil, "HIGHLIGHT")
    b.hl:SetAllPoints(b.icon); b.hl:SetColorTexture(1, 1, 1, 0.15)
    b.countText = b:CreateFontString(nil, "OVERLAY")
    if NumberFontNormal then b.countText:SetFontObject(NumberFontNormal)
    else b.countText:SetFont(STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF", 12, "OUTLINE") end
    b.countText:SetPoint("BOTTOMRIGHT", -3, 3); b.countText:SetJustifyH("RIGHT")
    b.trend = b:CreateTexture(nil, "OVERLAY")        -- punto: verde si está barato frente a 30 días, rojo si caro
    b.trend:SetSize(6, 6); b.trend:SetPoint("TOPRIGHT", -3, -3)
    if b.RegisterForClicks then b:RegisterForClicks("LeftButtonUp") end
    b:SetScript("OnEnter", showTip)
    b:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    b:SetScript("OnClick", function(self)
        if not self.data then return end
        local link = C_Item and C_Item.GetItemInfo and select(2, C_Item.GetItemInfo(self.data.id))
        local mod = IsModifiedClick and (IsModifiedClick("CHATLINK") or IsModifiedClick("DRESSUP"))
        if link and mod and HandleModifiedItemClick and HandleModifiedItemClick(link) then return end
        ns.PriceHistory.Show(self.data.id, nil)
    end)
    return b
end

local function paintTabs(f)
    local S = ns.Style
    for _, t in ipairs(f.tabs) do
        local on = t.loc == Inv.loc
        S.Color(t.fs, on and "value" or "label")
        if on then t.line:Show() else t.line:Hide() end
    end
end

local function build()
    if Inv.frame then return Inv.frame end
    local S = ns.Style
    local f = CreateFrame("Frame", "OroborosInventoryFrame", UIParent, "BackdropTemplate")
    f:SetSize(GRID_W + 2 * PAD, -TOP + ROWS_VIS * (SLOT + GAP) - GAP + 48)
    f:SetPoint("CENTER")
    f:SetFrameStrata("HIGH")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosInventoryFrame")
    S.Panel(f, "Lo que tienes  " .. S.Hex("muted", "todos tus personajes"))

    -- Pestañas por sitio
    f.tabs = {}
    local x = PAD
    for i, t in ipairs(TABS) do
        local b = CreateFrame("Button", nil, f)
        b.loc = t[1]
        b.fs = S.Text(b, "small"); b.fs:SetPoint("CENTER"); b.fs:SetText(t[2])
        local w = math.max(44, (b.fs.GetStringWidth and b.fs:GetStringWidth() or 40) + 16)
        b:SetSize(w, 22)
        b:SetPoint("TOPLEFT", x, -38)
        b.line = b:CreateTexture(nil, "ARTWORK")
        b.line:SetColorTexture(S.C.accent[1], S.C.accent[2], S.C.accent[3], 1)
        b.line:SetHeight(2); b.line:SetPoint("BOTTOMLEFT", 4, 0); b.line:SetPoint("BOTTOMRIGHT", -4, 0)
        b:SetScript("OnClick", function(self) Inv.loc = self.loc; Inv.offset = 0; paintTabs(f); Inv.Refresh(f.search:GetText()) end)
        f.tabs[i] = b
        x = x + w + 4
    end

    local box = CreateFrame("EditBox", nil, f, "BackdropTemplate")
    box:SetSize(170, 22)
    box:SetPoint("TOPRIGHT", -PAD, -38)
    box:SetAutoFocus(false)
    box:SetFontObject(ChatFontNormal)
    box:SetTextInsets(6, 6, 0, 0)
    S.Backdrop(box, S.C.section, S.C.border)
    box:SetScript("OnTextChanged", function(self) Inv.offset = 0; Inv.Refresh(self:GetText()) end)
    box:SetScript("OnEscapePressed", box.ClearFocus)
    f.search = box
    local hint = S.Text(f, "muted"); hint:SetPoint("RIGHT", box, "LEFT", -8, 0); hint:SetText("Buscar")
    local tip = S.Text(f, "muted"); tip:SetPoint("TOPLEFT", PAD, -66)
    tip:SetText("Ordenado por valor · clic: historial · punto verde/rojo: barato/caro frente a 30 días")

    f.slots = {}
    for k = 1, COLS * ROWS_VIS do f.slots[k] = makeSlot(f, k) end
    f.empty = S.Text(f, "muted"); f.empty:SetPoint("TOP", 0, TOP - 40)

    f.div = S.Divider(f)
    f.div:SetPoint("BOTTOMLEFT", PAD, 32); f.div:SetPoint("BOTTOMRIGHT", -PAD, 32)
    f.totalLabel = S.Text(f, "label"); f.totalLabel:SetPoint("BOTTOMLEFT", PAD, 12); f.totalLabel:SetText("TOTAL")
    f.total = S.Text(f, "value"); f.total:SetPoint("LEFT", f.totalLabel, "RIGHT", 8, 0)
    f.info = S.Text(f, "muted"); f.info:SetPoint("BOTTOMRIGHT", -PAD, 13); f.info:SetJustifyH("RIGHT")

    f:EnableMouseWheel(true)
    f:SetScript("OnMouseWheel", function(_, delta)
        local maxOff = math.max(0, math.ceil((Inv.count or 0) / COLS) - ROWS_VIS)
        Inv.offset = math.max(0, math.min(maxOff, (Inv.offset or 0) - delta))
        Inv.Refresh(f.search:GetText())
    end)
    Inv.frame = f
    paintTabs(f)
    return f
end

function Inv.Refresh(filter)
    local f = Inv.frame
    if not f then return end
    local S = ns.Style
    local rows, total = Inv.Rows(filter, Inv.loc)
    Inv.count = #rows
    local first = (Inv.offset or 0) * COLS
    for k, b in ipairs(f.slots) do
        local d = rows[first + k]
        b.data = d
        if d then
            local icon = C_Item and C_Item.GetItemIconByID and C_Item.GetItemIconByID(d.id) or (GetItemIcon and GetItemIcon(d.id))
            b.icon:SetTexture(icon or QUESTION)
            b.icon:Show()
            b.countText:SetText(Inv.CountText(d.count))
            border(b, qualityColor(d.id))
            if d.tone == "good" or d.tone == "bad" then
                local c = S.C[d.tone]; b.trend:SetColorTexture(c[1], c[2], c[3], 1); b.trend:Show()
            else
                b.trend:Hide()
            end
        else
            b.icon:Hide()
            b.countText:SetText("")
            b.trend:Hide()
            border(b, nil)
        end
        if GameTooltip and b.IsMouseOver and b:IsMouseOver() and GameTooltip:GetOwner() == b then
            if d then showTip(b) else GameTooltip:Hide() end
        end
    end
    f.empty:SetText(#rows == 0 and "Nada que mostrar. Abre las bolsas y el banco con cada personaje para que se guarden." or "")
    f.total:SetText(ns.Coin(total))
    local bankT
    for _, c in pairs(OroborosDB.chars or {}) do if c.bankT and (not bankT or c.bankT > bankT) then bankT = c.bankT end end
    local nRows = math.ceil(#rows / COLS)
    local scroll = nRows > ROWS_VIS and string.format(" · filas %d–%d de %d (rueda)", (Inv.offset or 0) + 1,
        math.min(nRows, (Inv.offset or 0) + ROWS_VIS), nRows) or ""
    f.info:SetText(string.format("%d objetos%s%s", #rows, scroll, bankT and (" · banco visto el " .. date("%d/%m", bankT)) or ""))
end

function Inv.Toggle()
    local f = build()
    if f:IsShown() then f:Hide() return end
    Inv.offset = 0
    f:Show()
    Inv.Refresh(f.search:GetText() or "")
end
