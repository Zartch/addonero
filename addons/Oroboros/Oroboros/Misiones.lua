-- Oroboros: recompensa de las misiones que empiezan con un objeto (libranzas del artesano…).
-- Al abrir la ventana de la misión se apunta lo que da en OroborosDB.questItems[objeto]; fuera del juego el
-- plan compara cumplirla con vender el objeto. Solo lee lo que la ventana ya enseña: no acepta nada.
local _, ns = ...
local M = {}
ns.Misiones = M

local RECENT = 15           -- segundos: el objeto usado de la bolsa que abre la ventana de la misión

local lastUsed              -- { id, t } del último objeto usado desde la bolsa

local function onUse(bag, slot)
    local get = C_Container and C_Container.GetContainerItemID
    local id = get and get(bag, slot)
    if id then lastUsed = { id = id, t = time() } end
end
-- Solo mira (post-hook): usar el objeto sigue siendo tu clic
if C_Container and C_Container.UseContainerItem then hooksecurefunc(C_Container, "UseContainerItem", onUse) end

local function itemList(kind, n)
    local out = {}
    for i = 1, n or 0 do
        local link = GetQuestItemLink and GetQuestItemLink(kind, i)
        local id = link and tonumber(link:match("item:(%d+)"))
        local _, _, count = GetQuestItemInfo(kind, i)
        if id then
            out[#out + 1] = { id, count or 1 }
            ns.DB.SetItemInfo(id)
        end
    end
    return out
end

local function call(fn, ...)
    if not fn then return nil end
    local ok, v = pcall(fn, ...)
    if ok then return v end
end

function M.OnDetail(startItem)
    if not OroborosDB then return end
    local src = tonumber(startItem)
    if (not src or src == 0) and lastUsed and time() - lastUsed.t <= RECENT then src = lastUsed.id end
    if not src or src == 0 then return end         -- misión de un PNJ: no es de un objeto
    lastUsed = nil
    OroborosDB.questItems = OroborosDB.questItems or {}
    OroborosDB.questItems[src] = {
        q = call(GetQuestID), title = call(GetTitleText),
        money = call(GetRewardMoney) or 0, xp = call(GetRewardXP) or 0,
        items = itemList("reward", call(GetNumQuestRewards)),
        choices = itemList("choice", call(GetNumQuestChoices)),
        obj = call(GetObjectiveText), t = time(),
    }
    ns.DB.SetItemInfo(src)
end

ns.On("QUEST_DETAIL", function(startItem) M.OnDetail(startItem) end)
