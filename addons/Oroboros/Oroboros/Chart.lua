-- Oroboros: gráficas pequeñas con escala, fechas, línea de referencia y detalle al pasar el ratón
local _, ns = ...
local Chart = {}
ns.Chart = Chart

local L, R, T, B = 46, 6, 6, 14      -- márgenes: escala a la izquierda, fechas abajo

-- Dinero corto para la escala, con el icono de la moneda: 1.2 oro, 15 plata, 87 cobre
function Chart.ShortMoney(c)
    if not c then return "" end
    local icon = ns.COIN_ICON or { g = "g", s = "s", c = "c" }
    local function num(x) return (string.format("%.1f", x):gsub("%.0$", "")) end
    if c >= 10000 then return num(c / 10000) .. icon.g end
    if c >= 100 then return num(c / 100) .. icon.s end
    return string.format("%d", math.floor(c + 0.5)) .. icon.c
end

local function tex(parent, layer, color)
    local t = parent:CreateTexture(nil, layer or "ARTWORK")
    t:SetColorTexture(unpack(color))
    return t
end

local function pool(c, key, make)
    local pools = rawget(c, "_pools")                 -- rawget: sin pasar por los métodos del marco
    if not pools then pools = {}; rawset(c, "_pools", pools) end
    pools[key] = pools[key] or {}
    local list = pools[key]
    list.used = 0
    return function()
        list.used = list.used + 1
        local o = list[list.used]
        if not o then o = make(); list[list.used] = o end
        o:Show()
        return o
    end, function()
        for i = list.used + 1, #list do list[i]:Hide() end
    end
end

-- kind: "line" (puntos unidos) o "bar"
function Chart.New(parent, w, h, kind)
    local S = ns.Style
    local c = CreateFrame("Frame", nil, parent)
    c:SetSize(w, h)
    c.kind, c.w, c.h = kind, w, h
    c.top = tex(c, "BACKGROUND", S.C.grid); c.top:SetHeight(1)
    c.top:SetPoint("TOPLEFT", L, -T); c.top:SetPoint("TOPRIGHT", -R, -T)
    c.bottom = tex(c, "BACKGROUND", S.C.border); c.bottom:SetHeight(1)
    c.bottom:SetPoint("BOTTOMLEFT", L, B); c.bottom:SetPoint("BOTTOMRIGHT", -R, B)
    c.yMax = S.Text(c, "muted"); c.yMax:SetPoint("TOPRIGHT", c, "TOPLEFT", L - 4, -T + 5); c.yMax:SetJustifyH("RIGHT")
    c.yMin = S.Text(c, "muted"); c.yMin:SetPoint("BOTTOMRIGHT", c, "BOTTOMLEFT", L - 4, B - 5); c.yMin:SetJustifyH("RIGHT")
    c.xFirst = S.Text(c, "muted"); c.xFirst:SetPoint("BOTTOMLEFT", L, 0)
    c.xLast = S.Text(c, "muted"); c.xLast:SetPoint("BOTTOMRIGHT", -R, 0); c.xLast:SetJustifyH("RIGHT")
    c.empty = S.Text(c, "muted"); c.empty:SetPoint("CENTER", L / 2, 0)
    c.empty:SetText("Sin datos suficientes todavía")
    c.hair = tex(c, "OVERLAY", { 1, 1, 1, 0.25 }); c.hair:SetWidth(1); c.hair:Hide()
    c.SetData = Chart.SetData
    return c
end

-- pts: { {label=, value=} } (value nil = hueco); ref: valor de la línea discontinua (o nil)
-- tip(pt) -> título, línea: textos del detalle al pasar el ratón
function Chart.SetData(c, pts, ref, tip)
    local S = ns.Style
    local n, vals = #pts, {}
    for i = 1, n do if pts[i].value then vals[#vals + 1] = pts[i].value end end
    local newLine, endLines = pool(c, "lines", function()
        if c.CreateLine then local l = c:CreateLine(nil, "ARTWORK"); l:SetThickness(2); l:SetColorTexture(unpack(S.C.accent)); return l end
        return tex(c, "ARTWORK", S.C.accent)
    end)
    local newDot, endDots = pool(c, "dots", function() local d = tex(c, "OVERLAY", S.C.accent); d:SetSize(5, 5); return d end)
    local newBar, endBars = pool(c, "bars", function() return tex(c, "ARTWORK", S.C.accent) end)
    local newDash, endDashes = pool(c, "dashes", function() local d = tex(c, "ARTWORK", S.C.ref); d:SetHeight(1); d:SetWidth(4); return d end)
    local newHit, endHits = pool(c, "hits", function()
        local hb = CreateFrame("Button", nil, c)
        hb:SetScript("OnEnter", function(self)
            c.hair:ClearAllPoints()
            c.hair:SetPoint("TOP", c, "TOPLEFT", self.cx, -T)
            c.hair:SetPoint("BOTTOM", c, "BOTTOMLEFT", self.cx, B)
            c.hair:Show()
            if GameTooltip and self.title then
                GameTooltip:SetOwner(self, "ANCHOR_TOP")
                GameTooltip:SetText(self.title, 1, 1, 1)
                GameTooltip:AddLine(self.line, S.C.accent[1], S.C.accent[2], S.C.accent[3])
                GameTooltip:Show()
            end
        end)
        hb:SetScript("OnLeave", function() c.hair:Hide(); if GameTooltip then GameTooltip:Hide() end end)
        return hb
    end)
    if #vals < 2 then
        endLines(); endDots(); endBars(); endDashes(); endHits()
        for _, fs in ipairs({ c.yMax, c.yMin, c.xFirst, c.xLast }) do fs:SetText("") end
        c.empty:Show()
        return
    end
    c.empty:Hide()
    local lo, hi = math.min(unpack(vals)), math.max(unpack(vals))
    if ref then lo, hi = math.min(lo, ref), math.max(hi, ref) end
    if hi <= lo then lo, hi = lo * 0.9, hi * 1.1 + 1 end
    local pw, ph = c.w - L - R, c.h - T - B
    local y = function(v) return B + (v - lo) / (hi - lo) * ph end
    local slot = pw / n
    local x = c.kind == "bar" and function(i) return L + (i - 0.5) * slot end
        or function(i) return L + (i - 1) * pw / math.max(1, n - 1) end
    c.yMax:SetText(Chart.ShortMoney(hi)); c.yMin:SetText(Chart.ShortMoney(lo))
    c.xFirst:SetText(pts[1].label or ""); c.xLast:SetText(pts[n].label or "")
    local prev
    for i = 1, n do
        local v = pts[i].value
        if v then
            if c.kind == "bar" then
                local b = newBar()
                b:ClearAllPoints()
                b:SetPoint("BOTTOMLEFT", c, "BOTTOMLEFT", x(i) - slot * 0.35, B)
                b:SetSize(math.max(2, slot * 0.7), math.max(2, y(v) - B))
            else
                local d = newDot()
                d:ClearAllPoints()
                d:SetPoint("CENTER", c, "BOTTOMLEFT", x(i), y(v))
                if prev then
                    local l = newLine()
                    if l.SetStartPoint then
                        l:SetStartPoint("BOTTOMLEFT", c, x(prev), y(pts[prev].value))
                        l:SetEndPoint("BOTTOMLEFT", c, x(i), y(v))
                    else                                   -- sin CreateLine: barra fina en el punto
                        l:ClearAllPoints(); l:SetPoint("BOTTOM", c, "BOTTOMLEFT", x(i), B); l:SetSize(2, y(v) - B)
                    end
                end
                prev = i
            end
        else
            prev = nil                                     -- hueco: la línea se corta
        end
        local hb = newHit()
        hb:ClearAllPoints()
        hb:SetPoint("BOTTOMLEFT", c, "BOTTOMLEFT", x(i) - slot / 2, B)
        hb:SetSize(math.max(4, slot), ph)
        hb.cx = x(i)
        if tip then hb.title, hb.line = tip(pts[i]) end
    end
    if ref then
        local k = 0
        for px = L, L + pw - 4, 8 do
            k = k + 1
            local d = newDash()
            d:ClearAllPoints()
            d:SetPoint("LEFT", c, "BOTTOMLEFT", px, y(ref))
        end
    end
    endLines(); endDots(); endBars(); endDashes(); endHits()
end
