-- Entorno WoW simulado para probar la lógica del addon fuera del juego
LOG = {}
local function log(...) local t = {} for i = 1, select("#", ...) do t[#t+1] = tostring(select(i, ...)) end LOG[#LOG+1] = table.concat(t, " ") end
CALLS = {}
local function call(name, ...) CALLS[#CALLS+1] = { name, ... } end

date, time = os.date, os.time
function strjoin(sep, ...) return table.concat({...}, sep) end
function tostringall(...) local t = {} for i = 1, select("#", ...) do t[i] = tostring(select(i, ...)) end return unpack(t) end
function wipe(t) for k in pairs(t) do t[k] = nil end return t end
select = select
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) log("[chat] " .. m) end }
UISpecialFrames = {}
SlashCmdList = {}
NUM_BAG_SLOTS = 4
NUM_TOTAL_EQUIPPED_BAG_SLOTS = 5
Enum = { BagIndex = { Bank = -1, Reagentbank = -3, CharacterBankTab_1 = 6, AccountBankTab_1 = 12 }, AuctionHouseSortOrder = { Price = 0 }, CraftingReagentType = { Basic = 1, Modifying = 0 } }

-- Frames: cualquier método es un no-op salvo eventos y scripts
local frames = {}
local function newObj()
    local o = { scripts = {}, events = {} }
    return setmetatable(o, { __index = function(t, k)
        if k == "RegisterEvent" then return function(self, e) self.events[e] = true end end
        if k == "SetScript" then return function(self, n, fn) self.scripts[n] = fn end end
        if k == "IsShown" then return function(self) return self.shown end end
        if k == "Show" then return function(self) self.shown = true end end
        if k == "Hide" then return function(self) self.shown = false end end
        if k == "GetText" then return function(self) return self.text end end
        if k == "SetText" then return function(self, s) self.text = s end end
        if k:match("^Create") then return function() return newObj() end end
        return function() end
    end })
end
function CreateFrame() local f = newObj(); frames[#frames+1] = f; return f end
function FireEvent(e, ...)
    for _, f in ipairs(frames) do
        if f.events[e] and f.scripts.OnEvent then f.scripts.OnEvent(f, e, ...) end
    end
end
-- C_Timer: cola que se vacía manualmente
TIMERS = {}
C_Timer = { After = function(_, fn) TIMERS[#TIMERS+1] = fn end }
function RunTimers() while #TIMERS > 0 do local fn = table.remove(TIMERS, 1); fn() end end

MONEY = 5000000
function GetMoney() return MONEY end
function UnitName() return "Zartch" end
function GetRealmName() return "Forever Normal" end
function GetNormalizedRealmName() return "ForeverNormal" end
function UnitFactionGroup() return "Horde" end
function UnitLevel() return 60 end
function hooksecurefunc(tbl, name, hook)
    if type(tbl) == "string" then tbl, name, hook = _G, tbl, name end   -- forma global: hooksecurefunc("Nombre", f)
    local orig = tbl[name]
    tbl[name] = function(...) local r = { orig(...) }; hook(...); return unpack(r) end
end
ALT_DOWN = false
function IsAltKeyDown() return ALT_DOWN end
function HandleModifiedItemClick(link) return false end
MAIL = { { "seller", "Bolt of Linen Cloth", "x", 5388, 0, 0, 270, 0, 0, 0, 12 }, { nil } }
function GetInboxNumItems() return #MAIL end
function GetInboxInvoiceInfo(i) return unpack(MAIL[i]) end
function GetInboxHeaderInfo(i) return nil, nil, "Auction House", "x", 0, 0, 29.5 end
function UnitClass() return "Mago", "MAGE" end

-- Objetos
ITEMS = { [14047] = { "Runecloth", 1, 20 }, [2589] = { "Linen Cloth", 1, 20 }, [2996] = { "Bolt of Linen Cloth", 1, 20 },
          [2318] = { "Light Leather", 1, 20 }, [2320] = { "Coarse Thread", 1, 20 },
          [4306] = { "Silk Cloth", 1, 20 }, [6070] = { "Wolfshead Helm", 3, 1 } }
C_Item = { GetItemInfo = function(id)
    local it = ITEMS[id]; if not it then return nil end
    return it[1], nil, it[2], it[4] or 25, nil, nil, nil, it[3], nil, nil, 5
end, RequestLoadItemDataByID = function(id) call("RequestLoadItemDataByID", id) end }

-- Bolsas
BAGS = { [-1] = { [1] = { itemID = 14047, stackCount = 20 }, [2] = { itemID = 14047, stackCount = 20 } },
         [6] = { [1] = { itemID = 4306, stackCount = 7 } },
         [12] = { [1] = { itemID = 2589, stackCount = 99 } },
         [0] = { [1] = { itemID = 2996, stackCount = 12 }, [2] = { itemID = 6070, stackCount = 1 }, [3] = { itemID = 6070, stackCount = 1 } } }
C_Container = {
    GetContainerNumSlots = function(b) return BAGS[b] and 16 or 0 end,
    GetContainerItemInfo = function(b, s) return BAGS[b] and BAGS[b][s] end,
    GetContainerItemID = function(b, s) return BAGS[b] and BAGS[b][s] and BAGS[b][s].itemID end,
    UseContainerItem = function(b, s) call("UseContainerItem", b, s) end,
}
-- Ventana de una misión (QUEST_DETAIL): lo que enseña la recompensa
QUEST = { id = 0, title = "", money = 0, xp = 0, rewards = {}, choices = {}, obj = "" }
function GetQuestID() return QUEST.id end
function GetTitleText() return QUEST.title end
function GetRewardMoney() return QUEST.money end
function GetRewardXP() return QUEST.xp end
function GetObjectiveText() return QUEST.obj end
function GetNumQuestRewards() return #QUEST.rewards end
function GetNumQuestChoices() return #QUEST.choices end
local function qlist(kind) return kind == "choice" and QUEST.choices or QUEST.rewards end
function GetQuestItemLink(kind, i) local r = qlist(kind)[i]; return r and ("|Hitem:" .. r[1] .. ":::|h[x]|h") end
function GetQuestItemInfo(kind, i) local r = qlist(kind)[i]; return "x", nil, r and r[2] end
ItemLocation = { CreateFromBagAndSlot = function(_, b, s) return { bag = b, slot = s } end }

-- Subasta
REPLICATE = {
    { "Linen Cloth", 20, 2589, 600 }, { "Linen Cloth", 20, 2589, 700 }, { "Linen Cloth", 200, 2589, 10000 },
    { "Silk Cloth", 20, 4306, 4000 }, { "Wolfshead Helm", 1, 6070, 250000 },
}
COMMODITY = { [2589] = { { unitPrice = 30, quantity = 20, auctionID = 1, numOwnerItems = 0 },
                         { unitPrice = 35, quantity = 20, auctionID = 2, numOwnerItems = 0 },
                         { unitPrice = 50, quantity = 200, auctionID = 3, numOwnerItems = 0 } },
              [2996] = { { unitPrice = 400, quantity = 10, auctionID = 4, numOwnerItems = 10 },
                         { unitPrice = 450, quantity = 30, auctionID = 5, numOwnerItems = 0 } } }
ITEMRES = { [6070] = { { buyoutAmount = 250000, quantity = 1, auctionID = 9, containsOwnerItem = false } } }

C_AuctionHouse = {
    ReplicateItems = function() call("ReplicateItems") end,
    GetNumReplicateItems = function() return #REPLICATE end,
    GetReplicateItemInfo = function(i)
        local r = REPLICATE[i + 1]
        return r[1], nil, r[2], r[6] or 1, true, 1, 0, r[5] or 0, 0, r[4], 0, false, nil, "x", "x", 0, r[3], true
    end,
    MakeItemKey = function(id) return { itemID = id } end,
    GetItemKeyInfo = function(k) return { itemName = ITEMS[k.itemID][1], isCommodity = ITEMS[k.itemID][3] > 1, quality = 1 } end,
    SendSearchQuery = function(k) call("SendSearchQuery", k.itemID) end,
    GetNumCommoditySearchResults = function(id) return #(COMMODITY[id] or {}) end,
    GetCommoditySearchResultInfo = function(id, i) return COMMODITY[id][i] end,
    GetNumItemSearchResults = function(k) return #(ITEMRES[k.itemID] or {}) end,
    GetItemSearchResultInfo = function(k, i) return ITEMRES[k.itemID][i] end,
    StartCommoditiesPurchase = function(id, n) call("StartCommoditiesPurchase", id, n) end,
    ConfirmCommoditiesPurchase = function(id, n) call("ConfirmCommoditiesPurchase", id, n) end,
    CancelCommoditiesPurchase = function() call("CancelCommoditiesPurchase") end,
    PlaceBid = function(a, b) call("PlaceBid", a, b) end,
    PostCommodity = function(loc, d, n, p) call("PostCommodity", loc.slot, d, n, p) end,
    PostItem = function(loc, d, n, bid, p) call("PostItem", loc.slot, d, n, p) end,
    CalculateCommodityDeposit = function(id, d, n) return 3 * n end,
    CalculateItemDeposit = function(loc, d, n) return 60 end,
}

-- Profesiones
RECIPES = {
    [2963] = { info = { name = "Bolt of Linen Cloth", learned = true, relativeDifficulty = 3, numSkillUps = 0 },
               s = { outputItemID = 2996, quantityMin = 1, quantityMax = 1,
                     reagentSlotSchematics = { { reagentType = 1, quantityRequired = 2, reagents = { { itemID = 2589 } } } } } },
    [3914] = { info = { name = "Brown Linen Pants", learned = false, relativeDifficulty = 0, numSkillUps = 1 },
               s = { outputItemID = 4343, quantityMin = 1, quantityMax = 1,
                     reagentSlotSchematics = { { reagentType = 1, quantityRequired = 2, reagents = { { itemID = 2996 } } },
                                               { reagentType = 1, quantityRequired = 1, reagents = { { itemID = 2320 } } } } } },
}
C_TradeSkillUI = {
    IsTradeSkillLinked = function() return false end, IsTradeSkillGuild = function() return false end,
    IsNPCCrafting = function() return false end, IsTradeSkillReady = function() return true end,
    GetChildProfessionInfo = function() return { professionName = "Sastrería", professionID = 197, skillLevel = 75, maxSkillLevel = 150 } end,
    GetBaseProfessionInfo = function() return nil end,
    GetAllRecipeIDs = function() local t = {} for id in pairs(RECIPES) do t[#t+1] = id end table.sort(t) return t end,
    GetRecipeInfo = function(id) return RECIPES[id] and RECIPES[id].info end,
    GetRecipeSchematic = function(id) return RECIPES[id].s end,
    GetRecipeSourceText = function() return "|cffffd100Instructor:|r Josef |nCoste: 1s" end,
    GetRecipeCooldown = function() return 0 end,
    CraftRecipe = function(id, n) call("CraftRecipe", id, n) end,
}

-- Vendedor
MERCHANT = { { 2320, 10, 1 } }   -- itemID, price, stack
function GetMerchantNumItems() return #MERCHANT end
function GetMerchantItemID(i) return MERCHANT[i][1] end
function GetMerchantItemInfo(i) return "x", nil, MERCHANT[i][2], MERCHANT[i][3], -1, true, true, false end

-- Serializa OroborosDB al formato de SavedVariables de WoW
function Serialize(v, indent)
    indent = indent or ""
    if type(v) == "table" then
        local keys = {}
        for k in pairs(v) do keys[#keys+1] = k end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        local out = { "{\n" }
        for _, k in ipairs(keys) do
            local ks = type(k) == "number" and ("[" .. k .. "]") or ('["' .. k .. '"]')
            out[#out+1] = indent .. "\t" .. ks .. " = " .. Serialize(v[k], indent .. "\t") .. ",\n"
        end
        out[#out+1] = indent .. "}"
        return table.concat(out)
    elseif type(v) == "string" then
        return string.format("%q", v)
    else
        return tostring(v)
    end
end


-- Farmeo: registro de combate, botín con su origen, subzona y objetivo
CLEU = {}
function CombatLogGetCurrentEventInfo() return unpack(CLEU) end
PLAYER_GUID, PET_GUID = "Player-1-000A1B2C", nil
TARGET = nil            -- { guid, name, lvl, cls, attack }
function UnitGUID(u)
    if u == "player" then return PLAYER_GUID elseif u == "pet" then return PET_GUID
    elseif u == "target" then return TARGET and TARGET.guid end
end
SUBZONE, ZONE, MAPID = "Bosque X", "Elwynn", 1429
function GetSubZoneText() return SUBZONE end
function GetZoneText() return ZONE end
C_Map = C_Map or {}
C_Map.GetBestMapForUnit = function() return MAPID end
LOOT = {}               -- { { type = 1|2, link = , qty = , sources = { guid, qty, guid, qty } } }
function GetNumLootItems() return #LOOT end
function GetLootSlotType(i) return LOOT[i].type end
function GetLootSlotLink(i) return LOOT[i].link end
function GetLootSlotInfo(i) return nil, "x", LOOT[i].qty end
function GetLootSourceInfo(i) return unpack(LOOT[i].sources) end
function UnitCanAttack() return TARGET and TARGET.attack or false end
-- Midnight: dentro de instancias, valores secretos. En la simulación, los que estén en SECRETS.
IN_INSTANCE = false
function IsInInstance() return IN_INSTANCE, IN_INSTANCE and "party" or "none" end
SECRETS = {}
function issecretvalue(v) return SECRETS[v] == true end
function UnitClassification() return TARGET and TARGET.cls end
local _UnitLevel, _UnitName = UnitLevel, UnitName
function UnitLevel(u) if u == "target" and TARGET then return TARGET.lvl end return _UnitLevel(u) end
function UnitName(u) if u == "target" and TARGET then return TARGET.name end return _UnitName(u) end


-- Farmeo en el juego: posición en el mundo (X, Y como en AzerothCore) y mapas.
-- El juego de esta simulación espera el vector al revés (x = Y, y = X): la calibración debe elegir "ba".
WORLD = { X = 105, Y = 300, inst = 0 }
function UnitPosition() return WORLD.X, WORLD.Y, 0, WORLD.inst end
function CreateVector2D(x, y) return { x = x, y = y } end
local MAPNAMES = { [1415] = "Reinos del Este", [1429] = "Bosque del Mock", [1411] = "Durotar" }
local function inZone(X, Y) return X >= 0 and X < 1000 and Y >= 0 and Y < 1000 end
C_Map.GetMapInfo = function(id) return MAPNAMES[id] and { mapID = id, name = MAPNAMES[id] } or nil end
C_Map.GetMapPosFromWorldPos = function(inst, v, override)
    local X, Y = v.y, v.x
    if override == 1429 or (not override and false) then return 1429, { x = X / 1000, y = Y / 1000 } end
    if override == 1415 or not override then return 1415, { x = X / 10000, y = Y / 10000 } end
    return nil
end
C_Map.GetMapInfoAtPosition = function(id, px, py)
    if id == 1415 and inZone(px * 10000, py * 10000) then return { mapID = 1429, name = MAPNAMES[1429] } end
    return { mapID = id, name = MAPNAMES[id] }
end
C_Map.GetPlayerMapPosition = function(id)
    if id == 1429 then return { x = WORLD.X / 1000, y = WORLD.Y / 1000 } end
    return { x = WORLD.X / 10000, y = WORLD.Y / 10000 }
end
