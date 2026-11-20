-- Oroboros: dónde farmear en el juego (docs/farmeo.md, sección 6). Lee Farmeo.lua (generado fuera del juego):
-- panel /oro farmear, aviso en el chat al entrar en un sitio de la lista y nombres de los sitios para la página.
local _, ns = ...
local FP = {}
ns.FarmPanel = FP

local W, PAD, ROW_H, VISIBLE, TOP = 560, 12, 34, 12, 40
local HERB = { "botán", "botan", "herbor", "herbal" }
local MINE = { "miner", "mining" }
local CONTINENT = { [0] = "Reinos del Este", [1] = "Kalimdor" }
local SRC = { estimado = "estimado", mixto = "medido en parte", medido = "medido" }
local alerted = {}

local function data() return OroborosFarmeo end     -- global de Farmeo.lua; nil si no está

function FP.Key(m, cx, cy) return m .. ":" .. cx .. ":" .. cy end

-- Filas del tramo de 5 niveles del personaje (el más alto que haya si te pasas)
function FP.Band(level)
    local d = data()
    if not d or not d.bands then return nil end
    local b = math.floor((level or 1) / 5) * 5
    while b > 0 and not d.bands[b] do b = b - 5 end
    return d.bands[b], b
end

-- Cuadrícula donde está el jugador, con la misma cuenta que tools/oroboros_farm.py (x // 400, y // 400)
function FP.PlayerCell()
    if not UnitPosition then return nil end
    local x, y, _, inst = UnitPosition("player")
    if not x or (inst ~= 0 and inst ~= 1) then return nil end
    local cell = (data() and data().cell) or 400
    return FP.Key(inst, math.floor(x / cell), math.floor(y / cell))
end

----------------------------------------------------------------------
-- Aviso: una línea en el chat la primera vez que entras en un sitio de la lista
----------------------------------------------------------------------
function FP.CheckHere()
    local d = data()
    if not d or not OroborosDB then return end
    local rows = FP.Band(UnitLevel("player"))
    local key = FP.PlayerCell()
    if rows and key and not alerted[key] then
        for _, r in ipairs(rows) do
            if FP.Key(r.m, r.cx, r.cy) == key then
                alerted[key] = true
                ns.Print(string.format("Farmeo aquí: ≈ %s/h (%s) · %s", ns.Coin(r.g), SRC[r.src] or r.src, r.mobs or ""))
                return
            end
        end
    end
    local sub = GetSubZoneText and GetSubZoneText() or ""
    if sub ~= "" and not alerted["sub:" .. sub] then
        for _, r in ipairs(d.measured or {}) do
            if r.sub == sub and r.g then
                alerted["sub:" .. sub] = true
                ns.Print(string.format("Farmeo aquí: %s/h (medido, %d muertes)", ns.Coin(r.g), r.kills or 0))
                return
            end
        end
    end
end

----------------------------------------------------------------------
-- Nombres: el juego traduce las coordenadas del mundo a zona y coordenadas del mapa, en español.
-- Se guardan en OroborosDB.farmPlaces / farmMaps y el exportador los lleva a la página.
----------------------------------------------------------------------
local function near(p, q)
    return p and q and p.x and q.x and math.abs(p.x - q.x) < 0.01 and math.abs(p.y - q.y) < 0.01
end

-- En qué orden espera el juego (x, y) del mundo: se comprueba con la posición del jugador
function FP.Calibrate()
    if OroborosDB.farmAxis then return OroborosDB.farmAxis end
    if not (UnitPosition and CreateVector2D and C_Map and C_Map.GetMapPosFromWorldPos and C_Map.GetPlayerMapPosition) then return nil end
    local a, b, _, inst = UnitPosition("player")
    local mapID = C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
    if not a or not mapID then return nil end
    local real = C_Map.GetPlayerMapPosition(mapID, "player")
    if not real then return nil end
    for _, order in ipairs({ "ab", "ba" }) do
        local v = order == "ab" and CreateVector2D(a, b) or CreateVector2D(b, a)
        local ok, _, pos = pcall(C_Map.GetMapPosFromWorldPos, inst, v, mapID)
        if ok and near(pos, real) then
            OroborosDB.farmAxis = order
            return order
        end
    end
    return nil
end

local function resolve(m, x, y, order)
    local v = order == "ab" and CreateVector2D(x, y) or CreateVector2D(y, x)
    local ok, uiMap, pos = pcall(C_Map.GetMapPosFromWorldPos, m, v)
    if not ok or not uiMap or not pos then return nil end
    local zoneID = uiMap
    if C_Map.GetMapInfoAtPosition then
        local info = C_Map.GetMapInfoAtPosition(uiMap, pos.x, pos.y)
        if info and info.mapID then zoneID = info.mapID end
    end
    local info = C_Map.GetMapInfo and C_Map.GetMapInfo(zoneID)
    if not info or not info.name then return nil end
    local out = { zone = info.name }
    local ok2, _, zp = pcall(C_Map.GetMapPosFromWorldPos, m, v, zoneID)
    if ok2 and zp then
        out.x = math.floor(zp.x * 1000 + 0.5) / 10
        out.y = math.floor(zp.y * 1000 + 0.5) / 10
    end
    return out
end

function FP.ResolveAll()
    local d = data()
    if not d or not OroborosDB then return 0 end
    OroborosDB.farmPlaces = OroborosDB.farmPlaces or {}
    OroborosDB.farmMaps = OroborosDB.farmMaps or {}
    local n = 0
    if C_Map and C_Map.GetMapInfo then
        for _, bySkill in pairs(d.gather or {}) do
            for _, rows in pairs(bySkill) do
                for _, g in ipairs(rows) do
                    if not OroborosDB.farmMaps[g.map] then
                        local info = C_Map.GetMapInfo(g.map)
                        if info and info.name then OroborosDB.farmMaps[g.map] = info.name; n = n + 1 end
                    end
                end
            end
        end
    end
    local order = FP.Calibrate()
    if not order then return n end
    for _, rows in pairs(d.bands or {}) do
        for _, r in ipairs(rows) do
            local k = FP.Key(r.m, r.cx, r.cy)
            if not OroborosDB.farmPlaces[k] and r.x then
                local p = resolve(r.m, r.x, r.y, order)
                if p then OroborosDB.farmPlaces[k] = p; n = n + 1 end
            end
        end
    end
    return n
end

local function onArea()
    pcall(FP.ResolveAll)
    FP.CheckHere()
end
for _, ev in ipairs({ "ZONE_CHANGED", "ZONE_CHANGED_NEW_AREA", "ZONE_CHANGED_INDOORS" }) do ns.On(ev, onArea) end
ns.On("PLAYER_ENTERING_WORLD", function() pcall(FP.ResolveAll) end)

----------------------------------------------------------------------
-- Contenido del panel: lo medido, lo que puedes explorar y la recolección (para tu nivel y profesiones)
----------------------------------------------------------------------
local function placeName(r)
    local p = OroborosDB.farmPlaces and OroborosDB.farmPlaces[FP.Key(r.m, r.cx, r.cy)]
    if p then return p.x and string.format("%s (%.0f, %.0f)", p.zone, p.x, p.y) or p.zone end
    return (CONTINENT[r.m] or ("mapa " .. r.m)) .. (r.x and string.format(" (x %d, y %d)", r.x, r.y) or "")
end

local function itemList(ids)
    local out = {}
    for i, id in ipairs(ids or {}) do
        if i > 3 then break end
        out[#out + 1] = ns.DB.ItemName(id)
    end
    return table.concat(out, ", ")
end

-- Minúsculas solo de A-Z: string.lower puede tocar los bytes de «á» según la configuración regional y romper el UTF-8
local function asciiLower(s)
    return (string.gsub(s or "", "[A-Z]", function(c) return string.char(string.byte(c) + 32) end))
end

local function hasWord(name, words)
    local low = asciiLower(name)
    for _, w in ipairs(words) do if string.find(low, w, 1, true) then return true end end
    return false
end

-- Niveles de las profesiones de recolección del personaje: { herb = 192, mine = nil }
function FP.GatherSkills()
    local out = {}
    local c = ns.DB.Char and ns.DB.Char()
    for name, p in pairs((c and c.professions) or {}) do
        local skill = type(p) == "table" and p.skill or 0
        if hasWord(name, HERB) then out.herb = skill end
        if hasWord(name, MINE) then out.mine = skill end
    end
    return out
end

function FP.Entries(level)
    local d = data()
    local e = {}
    if not d then
        e[1] = { head = "Sin Farmeo.lua: genera el plan fuera del juego (con AzerothCore descargado) y haz /reload." }
        return e
    end
    e[#e + 1] = { head = "DONDE YA HAS FARMEADO" }
    if #(d.measured or {}) == 0 then
        e[#e + 1] = { t1 = "Aún nada medido", t2 = "Mata y despoja con Oroboros activo; al salir o /reload se recoge." }
    end
    for _, r in ipairs(d.measured or {}) do
        e[#e + 1] = { t1 = r.sub .. (r.zone ~= r.sub and ("  " .. ns.Style.Hex("muted", r.zone)) or ""),
                      t2 = string.format("%d muertes · %d min · %s", r.kills or 0, math.floor((r.secs or 0) / 60), itemList(r.it)),
                      g = r.g, tag = "medido" }
    end
    local rows, b = FP.Band(level)
    e[#e + 1] = { head = string.format("POR EXPLORAR  ·  niveles %d–%d", b or 0, (b or 0) + 4) }
    for _, r in ipairs(rows or {}) do
        e[#e + 1] = { t1 = placeName(r), t2 = string.format("%s · niv. %s · %s", r.mobs or "", r.lv or "?", itemList(r.it)),
                      g = r.g, tag = SRC[r.src] or r.src, sat = r.sat }
    end
    local skills = FP.GatherSkills()
    for _, kind in ipairs({ "herb", "mine" }) do
        local skill = skills[kind]
        local bySkill = d.gather and d.gather[kind]
        if skill and bySkill then
            local s = math.floor(skill / 25) * 25
            while s > 0 and not bySkill[s] do s = s - 25 end
            e[#e + 1] = { head = string.format("RECOLECCIÓN  ·  %s %d", kind == "herb" and "Botánica" or "Minería", skill) }
            for _, g in ipairs(bySkill[s] or {}) do
                local name = (OroborosDB.farmMaps and OroborosDB.farmMaps[g.map]) or ("mapa " .. g.map)
                e[#e + 1] = { t1 = name, t2 = string.format("≈ %d nodos/h · %s", g.nph or 0, itemList(g.it)), g = g.g, tag = "estimado" }
            end
        end
    end
    return e
end

----------------------------------------------------------------------
-- Ventana
----------------------------------------------------------------------
local function makeRow(f, k)
    local S = ns.Style
    local r = CreateFrame("Frame", nil, f)
    r:SetSize(W - 2 * PAD, ROW_H)
    r:SetPoint("TOPLEFT", PAD, -TOP - (k - 1) * ROW_H)
    r.bg = r:CreateTexture(nil, "BACKGROUND")
    r.bg:SetAllPoints()
    r.t1 = S.Text(r, "small"); r.t1:SetPoint("TOPLEFT", 4, -3); r.t1:SetWidth(W - 2 * PAD - 150)
    r.t2 = S.Text(r, "muted"); r.t2:SetPoint("TOPLEFT", 4, -18); r.t2:SetWidth(W - 2 * PAD - 12)
    r.g = S.Text(r, "small"); r.g:SetPoint("TOPRIGHT", -4, -3); r.g:SetJustifyH("RIGHT")
    for _, fs in ipairs({ r.t1, r.t2 }) do if fs.SetWordWrap then fs:SetWordWrap(false) end end
    return r
end

local function build()
    if FP.frame then return FP.frame end
    local S = ns.Style
    local f = CreateFrame("Frame", "OroborosFarmFrame", UIParent, "BackdropTemplate")
    f:SetSize(W, TOP + VISIBLE * ROW_H + 30)
    f:SetPoint("CENTER")
    f:SetFrameStrata("HIGH")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosFarmFrame")
    S.Panel(f, "Dónde farmear")
    f.rows = {}
    for k = 1, VISIBLE do f.rows[k] = makeRow(f, k) end
    f.info = S.Text(f, "muted"); f.info:SetPoint("BOTTOMLEFT", PAD, 10)
    f:EnableMouseWheel(true)
    f:SetScript("OnMouseWheel", function(_, delta)
        FP.offset = math.max(0, math.min((FP.count or 0) - VISIBLE, (FP.offset or 0) - delta * 3))
        FP.Refresh()
    end)
    FP.frame = f
    return f
end

function FP.Refresh()
    local f = FP.frame
    if not f then return end
    local S = ns.Style
    local level = UnitLevel("player")
    local entries = FP.Entries(level)
    FP.entries, FP.count = entries, #entries
    f.header.title:SetText("Dónde farmear  " .. S.Hex("muted", "nivel " .. tostring(level)))
    local off = FP.offset or 0
    for k = 1, VISIBLE do
        local r, d = f.rows[k], entries[off + k]
        if d then
            if d.head then
                r.bg:SetColorTexture(S.C.section[1], S.C.section[2], S.C.section[3], 0.9)
                r.t1:SetText(S.Hex("accent", d.head)); r.t2:SetText(""); r.g:SetText("")
            else
                r.bg:SetColorTexture(1, 1, 1, (off + k) % 2 == 0 and 0.03 or 0)
                r.t1:SetText(d.t1 or "")
                r.t2:SetText(d.t2 or "")
                r.g:SetText(d.g and (ns.Coin(d.g) .. S.Hex("muted", "/h  " .. (d.tag or "")) .. (d.sat and S.Hex("bad", " satura") or "")) or "")
            end
            r:Show()
        else
            r:Hide()
        end
    end
    local d = data()
    f.info:SetText(d and ("Farmeo.lua del " .. date("%d/%m %H:%M", d.t or 0) .. " · rueda del ratón para ver más") or "")
end

function FP.Toggle()
    local f = build()
    if f:IsShown() then f:Hide() return end
    FP.offset = 0
    pcall(FP.ResolveAll)
    f:Show()
    FP.Refresh()
end
