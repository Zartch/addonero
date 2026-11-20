-- Oroboros: medición del farmeo (docs/farmeo.md, sección 5). Lo medido es la base de las propuestas.
-- Guarda sumas por criatura y subzona en OroborosDB.farm; fuera del juego se valora a precio de subasta.
-- Una muerte = un cadáver de criatura que despojas. No se usa el registro de combate
-- (COMBAT_LOG_EVENT_UNFILTERED): en la API de Midnight registrarlo es una acción reservada a Blizzard
-- y el juego bloquea el addon. Lo que no suelta nada no cuenta como muerte.
local _, ns = ...
local Farm = {}
ns.Farm = Farm

local ACTIVE_GAP = 120      -- huecos entre muertes de menos de 2 min cuentan como tiempo activo
local SEEN_MAX = 300        -- botines ya contados que se recuerdan (para no contar dos veces al reabrir)
local LOOT_MONEY = 2        -- tipo de hueco de botín: dinero

local lastKill
local seen, seenList = {}, {}

local function split(s)
    local out = {}
    for part in string.gmatch(s, "[^-]+") do out[#out + 1] = part end
    return out
end

-- Creature-0-3110-0-12345-1234-0000ABCDEF → 1234
function Farm.NpcFromGUID(guid)
    if type(guid) ~= "string" then return nil end
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
        m = { npc = npc, zone = zone, sub = sub, map = map, kills = 0, copper = 0, secs = 0, items = {} }
        data().mobs[key] = m
    end
    return m
end

local function gatherBucket()
    local zone, sub, map = where()
    local g = data().gather[sub]
    if not g then
        g = { zone = zone, sub = sub, map = map, nodes = 0, items = {} }
        data().gather[sub] = g
    end
    return g
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
    local now = time()
    local m = mob(npc)
    m.kills = m.kills + 1
    if lastKill and now - lastKill < ACTIVE_GAP then m.secs = m.secs + (now - lastKill) end
    lastKill = now
end

-- Botín: cada objeto y cada moneda va a la criatura (o al nodo) de donde sale, según GetLootSourceInfo
ns.On("LOOT_OPENED", function()
    if not OroborosDB or not GetLootSourceInfo then return end
    for slot = 1, GetNumLootItems() do
        local money = GetLootSlotType and GetLootSlotType(slot) == LOOT_MONEY
        local id = not money and tonumber(((GetLootSlotLink(slot) or ""):match("item:(%d+)"))) or nil
        local src = { GetLootSourceInfo(slot) }
        for i = 1, #src, 2 do
            local guid, qty = src[i], src[i + 1] or 0
            if type(guid) == "string" and firstTime(guid .. ":" .. (id or "money")) then
                local npc = Farm.NpcFromGUID(guid)
                if npc then
                    if firstTime(guid .. ":kill") then Farm.OnKill(guid) end
                    local m = mob(npc)
                    if money then m.copper = m.copper + qty
                    elseif id then m.items[id] = (m.items[id] or 0) + qty end
                elseif guid:match("^GameObject") then
                    local g = gatherBucket()
                    if firstTime(guid .. ":node") then g.nodes = g.nodes + 1 end
                    if id then g.items[id] = (g.items[id] or 0) + qty end
                end
            end
        end
    end
end)

-- Nivel y clasificación (normal, elite, rare…) de las criaturas atacables que tienes como objetivo
ns.On("PLAYER_TARGET_CHANGED", function()
    if not OroborosDB then return end
    local npc = Farm.NpcFromGUID(UnitGUID("target"))
    if npc and UnitCanAttack("player", "target") then
        data().npcs[npc] = { name = UnitName("target"), lvl = UnitLevel("target"), cls = UnitClassification("target") }
    end
end)
