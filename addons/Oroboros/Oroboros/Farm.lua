-- Oroboros: medición del farmeo (docs/farmeo.md, sección 5). Lo medido es la base de las propuestas.
-- Guarda sumas por criatura y subzona en OroborosDB.farm; fuera del juego se valora a precio de subasta.
-- Una muerte = un cadáver de criatura que despojas. No se usa el registro de combate
-- (COMBAT_LOG_EVENT_UNFILTERED): en la API de Midnight registrarlo es una acción reservada a Blizzard
-- y el juego bloquea el addon. Lo que no suelta nada no cuenta como muerte.
local _, ns = ...
local Farm = {}
ns.Farm = Farm

local ACTIVE_GAP = 120      -- huecos de menos de 2 min antes de una muerte cuentan como tiempo activo
local GATHER_GAP = 180      -- antes de un nodo, 3 min (entre nodos se va volando o corriendo)
local SESSION_GAP = 600     -- hasta 10 min es la misma sesión: descansar, moverse, buscar grupos (span)
local SEEN_MAX = 300        -- botines ya contados que se recuerdan (para no contar dos veces al reabrir)
local LOOT_MONEY = 2        -- tipo de hueco de botín: dinero

local lastActive            -- última muerte o último nodo: el tiempo se reparte sin contarlo dos veces
local seen, seenList = {}, {}

local function split(s)
    local out = {}
    for part in string.gmatch(s, "[^-]+") do out[#out + 1] = part end
    return out
end

-- En mazmorras y bandas la API de Midnight devuelve «valores secretos» (GUID, nombres…) y operar con ellos da
-- error («attempt to perform string conversion on a secret string value»). El farmeo es de mundo abierto:
-- dentro de una instancia no se mide nada, y fuera se comprueba cada valor antes de tocarlo.
local function secret(v) return issecretvalue and issecretvalue(v) or false end

function Farm.InInstance()
    if not IsInInstance then return false end
    local inside = IsInInstance()
    return inside and true or false
end

-- Creature-0-3110-0-12345-1234-0000ABCDEF → 1234
function Farm.NpcFromGUID(guid)
    if secret(guid) or type(guid) ~= "string" then return nil end
    local f = split(guid)
    if (f[1] == "Creature" or f[1] == "Vehicle") and f[6] then return tonumber(f[6]) end
    return nil
end

local function where()
    local zone = (GetZoneText and GetZoneText()) or ""
    local sub = (GetSubZoneText and GetSubZoneText()) or ""
    if sub == "" then sub = zone end
    local map = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player") or nil
    return zone, sub, map
end

local function data()
    local f = OroborosDB.farm
    if not f then f = { mobs = {}, gather = {}, npcs = {} }; OroborosDB.farm = f end
    return f
end

local function mob(npc)
    local zone, sub, map = where()
    local key = npc .. "@" .. sub
    local m = data().mobs[key]
    if not m then
        m = { npc = npc, zone = zone, sub = sub, map = map, kills = 0, copper = 0, secs = 0, span = 0, items = {} }
        data().mobs[key] = m
    end
    return m
end

local function gatherBucket()
    local zone, sub, map = where()
    local g = data().gather[sub]
    if not g then
        g = { zone = zone, sub = sub, map = map, nodes = 0, secs = 0, span = 0, items = {} }
        data().gather[sub] = g
    end
    return g
end

-- Reparte el hueco desde lo último (muerte o nodo): activo si es corto, sesión si es de menos de 10 min
local function clock(bucket, gap)
    local now = time()
    if lastActive then
        local d = now - lastActive
        if d < gap then bucket.secs = (bucket.secs or 0) + d end
        if d < SESSION_GAP then bucket.span = (bucket.span or 0) + d end
    end
    lastActive = now
end

local function firstTime(key)
    if seen[key] then return false end
    seen[key] = true
    seenList[#seenList + 1] = key
    if #seenList > SEEN_MAX then seen[table.remove(seenList, 1)] = nil end
    return true
end

function Farm.OnKill(destGUID)
    local npc = Farm.NpcFromGUID(destGUID)
    if not npc or not OroborosDB then return end
    local m = mob(npc)
    m.kills = m.kills + 1
    clock(m, ACTIVE_GAP)
end

-- Botín: cada objeto y cada moneda va a la criatura (o al nodo) de donde sale, según GetLootSourceInfo
ns.On("LOOT_OPENED", function()
    if not OroborosDB or not GetLootSourceInfo or Farm.InInstance() then return end
    for slot = 1, GetNumLootItems() do
        local money = GetLootSlotType and GetLootSlotType(slot) == LOOT_MONEY
        local id = not money and tonumber(((GetLootSlotLink(slot) or ""):match("item:(%d+)"))) or nil
        local src = { GetLootSourceInfo(slot) }
        for i = 1, #src, 2 do
            local guid, qty = src[i], src[i + 1] or 0
            if not secret(guid) and not secret(qty) and type(guid) == "string" and firstTime(guid .. ":" .. (id or "money")) then
                local npc = Farm.NpcFromGUID(guid)
                if npc then
                    if firstTime(guid .. ":kill") then Farm.OnKill(guid) end
                    local m = mob(npc)
                    if money then m.copper = m.copper + qty
                    elseif id then m.items[id] = (m.items[id] or 0) + qty end
                elseif guid:match("^GameObject") then
                    local g = gatherBucket()
                    if firstTime(guid .. ":node") then
                        g.nodes = g.nodes + 1
                        clock(g, GATHER_GAP)
                    end
                    if id then g.items[id] = (g.items[id] or 0) + qty end
                end
            end
        end
    end
end)

-- Nivel y clasificación (normal, elite, rare…) de las criaturas atacables que tienes como objetivo
ns.On("PLAYER_TARGET_CHANGED", function()
    if not OroborosDB or Farm.InInstance() then return end
    local npc = Farm.NpcFromGUID(UnitGUID("target"))
    if npc and UnitCanAttack("player", "target") then
        local name, lvl, cls = UnitName("target"), UnitLevel("target"), UnitClassification("target")
        if secret(name) or secret(lvl) or secret(cls) then return end
        data().npcs[npc] = { name = name, lvl = lvl, cls = cls }
    end
end)
