-- Oroboros: ventana «Lo que tienes» (docs/planes/2026-11-20-inventario-y-alt-clic.md)
-- Todos los personajes: bolsas, banco (el último guardado) y banco de banda, con valor y tendencia.
local _, ns = ...
local Inv = {}
ns.Inventory = Inv

local W, PAD, ROW_H, VISIBLE = 520, 12, 22, 14
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

-- Modelo: filas { id, name, count, unit, src, value, where, diffPct, tone, days } y el total
function Inv.Rows(filter)
    filter = type(filter) == "string" and filter:lower() or ""
    local agg = {}
    local function add(id, n, who, loc)
        if not id or not n or n <= 0 then return end
        local a = agg[id]
        if not a then a = { count = 0, where = {} }; agg[id] = a end
        a.count = a.count + n
        local key = who and (who .. ": " .. LOC_TXT[loc]) or LOC_TXT[loc]
        a.where[key] = true
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
            local where = {}
            for k in pairs(a.where) do where[#where + 1] = k end
            table.sort(where)
            local s = ns.PriceHistory and ns.PriceHistory.Get(id)
            local diff, tone
            if s and s.avg30 and s.avg30 > 0 and unit > 0 and src ~= "vendedor" then
                local d = (unit / s.avg30 - 1) * 100
                diff = d >= 0 and math.floor(d + 0.5) or -math.floor(-d + 0.5)
                tone = (diff <= -2 and "good") or (diff >= 2 and "bad") or "neutral"
            end
            local r = { id = id, name = name, count = a.count, unit = unit, src = src, value = unit * a.count,
                        where = table.concat(where, ", "), diffPct = diff, tone = tone, days = s and s.days or nil }
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
-- Ventana
----------------------------------------------------------------------
local COLS = { { "OBJETO", 0 }, { "DÓNDE", 196 }, { "UDS", 300 }, { "VALOR", 340 }, { "14 DÍAS", 420 } }

local function makeRow(f, k)
    local S = ns.Style
    local r = CreateFrame("Button", nil, f)
    r:SetSize(W - 2 * PAD, ROW_H)
    r:SetPoint("TOPLEFT", PAD, -86 - (k - 1) * ROW_H)
    r.bg = r:CreateTexture(nil, "BACKGROUND")
    r.bg:SetAllPoints()
    r.bg:SetColorTexture(1, 1, 1, k % 2 == 0 and 0.03 or 0)
    r.hl = r:CreateTexture(nil, "HIGHLIGHT")
    r.hl:SetAllPoints()
    r.hl:SetColorTexture(S.C.accent[1], S.C.accent[2], S.C.accent[3], 0.12)
    r.icon = r:CreateTexture(nil, "ARTWORK"); r.icon:SetSize(16, 16); r.icon:SetPoint("LEFT", 2, 0)
    r.name = S.Text(r, "small"); r.name:SetPoint("LEFT", 22, 0); r.name:SetWidth(170)
    if r.name.SetWordWrap then r.name:SetWordWrap(false) end
    r.where = S.Text(r, "muted"); r.where:SetPoint("LEFT", COLS[2][2], 0); r.where:SetWidth(100)
    if r.where.SetWordWrap then r.where:SetWordWrap(false) end
    r.count = S.Text(r, "small"); r.count:SetPoint("LEFT", COLS[3][2], 0)
    r.value = S.Text(r, "small"); r.value:SetPoint("LEFT", COLS[4][2], 0)
    r.diff = S.Text(r, "muted"); r.diff:SetPoint("RIGHT", -2, 0); r.diff:SetJustifyH("RIGHT")
    r.bars = {}
    for d = 1, 14 do
        local b = r:CreateTexture(nil, "ARTWORK")
        b:SetColorTexture(S.C.label[1], S.C.label[2], S.C.label[3], 0.7)
        b:SetWidth(3)
        b:SetPoint("BOTTOMLEFT", r, "BOTTOMLEFT", COLS[5][2] + (d - 1) * 4, 4)
        r.bars[d] = b
    end
    r:SetScript("OnClick", function(self) if self.id then ns.PriceHistory.Show(self.id, nil) end end)
    return r
end

local function build()
    if Inv.frame then return Inv.frame end
    local S = ns.Style
    local f = CreateFrame("Frame", "OroborosInventoryFrame", UIParent, "BackdropTemplate")
    f:SetSize(W, 86 + VISIBLE * ROW_H + 36)
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

    local box = CreateFrame("EditBox", nil, f, "BackdropTemplate")
    box:SetSize(200, 22)
    box:SetPoint("TOPRIGHT", -PAD, -36)
    box:SetAutoFocus(false)
    box:SetFontObject(ChatFontNormal)
    box:SetTextInsets(6, 6, 0, 0)
    S.Backdrop(box, S.C.section, S.C.border)
    box:SetScript("OnTextChanged", function(self) Inv.offset = 0; Inv.Refresh(self:GetText()) end)
    box:SetScript("OnEscapePressed", box.ClearFocus)
    f.search = box
    local hint = S.Text(f, "muted"); hint:SetPoint("RIGHT", box, "LEFT", -8, 0); hint:SetText("Buscar")
    local tip = S.Text(f, "muted"); tip:SetPoint("TOPLEFT", PAD, -40)
    tip:SetText("Clic en una fila: historial de precios")

    for _, c in ipairs(COLS) do
        local h = S.Text(f, "label"); h:SetPoint("TOPLEFT", PAD + c[2] + (c[1] == "OBJETO" and 22 or 0), -68); h:SetText(c[1])
    end
    f.rows = {}
    for k = 1, VISIBLE do f.rows[k] = makeRow(f, k) end
    f.div = S.Divider(f)
    f.div:SetPoint("BOTTOMLEFT", PAD, 32); f.div:SetPoint("BOTTOMRIGHT", -PAD, 32)
    f.totalLabel = S.Text(f, "label"); f.totalLabel:SetPoint("BOTTOMLEFT", PAD, 12); f.totalLabel:SetText("TOTAL")
    f.total = S.Text(f, "value"); f.total:SetPoint("LEFT", f.totalLabel, "RIGHT", 8, 0)
    f.info = S.Text(f, "muted"); f.info:SetPoint("BOTTOMRIGHT", -PAD, 13); f.info:SetJustifyH("RIGHT")

    f:EnableMouseWheel(true)
    f:SetScript("OnMouseWheel", function(_, delta)
        Inv.offset = math.max(0, math.min((Inv.count or 0) - VISIBLE, (Inv.offset or 0) - delta * 3))
        Inv.Refresh(f.search:GetText())
    end)
    Inv.frame = f
    return f
end

function Inv.Refresh(filter)
    local f = Inv.frame
    if not f then return end
    local S = ns.Style
    local rows, total = Inv.Rows(filter)
    Inv.count = #rows
    local off = Inv.offset or 0
    for k = 1, VISIBLE do
        local r, d = f.rows[k], rows[off + k]
        if d then
            r.id = d.id
            local icon = C_Item and C_Item.GetItemIconByID and C_Item.GetItemIconByID(d.id) or (GetItemIcon and GetItemIcon(d.id))
            if icon then r.icon:SetTexture(icon) end
            r.name:SetText(d.name)
            r.where:SetText(d.where)
            r.count:SetText(tostring(d.count))
            r.value:SetText(d.value > 0 and (ns.Coin(d.value) .. (d.src == "vendedor" and S.Hex("muted", " v") or "")) or S.Hex("muted", "—"))
            if d.diffPct then
                r.diff:SetText(string.format("%s%d %%", d.diffPct > 0 and "+" or "", d.diffPct))
                S.Color(r.diff, d.tone == "good" and "good" or (d.tone == "bad" and "bad" or "label"))
            else
                r.diff:SetText("")
            end
            local hi = 0
            for _, v in ipairs(d.days or {}) do if v and v > hi then hi = v end end
            for i = 1, 14 do
                local v = d.days and d.days[i]
                if v and hi > 0 then r.bars[i]:SetHeight(math.max(1, 14 * v / hi)); r.bars[i]:Show() else r.bars[i]:Hide() end
            end
            r:Show()
        else
            r.id = nil
            r:Hide()
        end
    end
    f.total:SetText(ns.Coin(total))
    local bankT
    for _, c in pairs(OroborosDB.chars or {}) do if c.bankT and (not bankT or c.bankT > bankT) then bankT = c.bankT end end
    f.info:SetText(string.format("%d objetos%s", #rows, bankT and (" · banco visto el " .. date("%d/%m", bankT)) or ""))
end

function Inv.Toggle()
    local f = build()
    if f:IsShown() then f:Hide() return end
    Inv.offset = 0
    f:Show()
    Inv.Refresh(f.search:GetText() or "")
end
