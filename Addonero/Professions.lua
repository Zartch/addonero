-- Addonero: lectura de profesiones y recetas (aprendidas y no aprendidas)
local _, ns = ...
local Professions = {}
ns.Professions = Professions

local scheduled = false
local crafterIndex          -- [itemID] = { {char, prof, recipe, name}, ... } con las recetas de TODOS tus personajes

-- Las recetas se guardan por cuenta: cualquier personaje (p. ej. el banquero) sabe qué fabrican los demás.
function Professions.Crafters(itemID)
    if not crafterIndex then
        crafterIndex = {}
        for ck, c in pairs(AddoneroDB.chars) do
            for pname, p in pairs(c.professions or {}) do
                for rid, r in pairs(p.recipes or {}) do
                    if r.out and r.l == 1 then
                        crafterIndex[r.out] = crafterIndex[r.out] or {}
                        table.insert(crafterIndex[r.out], { char = ck, prof = pname, recipe = rid, name = r.n })
                    end
                end
            end
        end
    end
    return crafterIndex[itemID] or {}
end

local function stripCodes(s)
    if not s then return nil end
    s = s:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("|n", " / "):gsub("|T.-|t", "")
    return s
end

local function isOwnTradeSkill()
    local T = C_TradeSkillUI
    if T.IsTradeSkillLinked and T.IsTradeSkillLinked() then return false end
    if T.IsTradeSkillGuild and T.IsTradeSkillGuild() then return false end
    if T.IsNPCCrafting and T.IsNPCCrafting() then return false end
    return true
end

local function readSchematic(recipeID)
    local s = C_TradeSkillUI.GetRecipeSchematic(recipeID, false)
    if not s then return nil end
    local reagents = {}
    local basic = Enum.CraftingReagentType and Enum.CraftingReagentType.Basic
    for _, slot in ipairs(s.reagentSlotSchematics or {}) do
        local isBasic = (basic and slot.reagentType == basic) or (not basic and slot.required)
        if isBasic and slot.reagents and slot.reagents[1] and slot.reagents[1].itemID then
            local alts
            if #slot.reagents > 1 then
                alts = {}
                for k = 2, #slot.reagents do alts[#alts + 1] = slot.reagents[k].itemID end
            end
            reagents[#reagents + 1] = { slot.reagents[1].itemID, slot.quantityRequired or 1, alts }
            ns.DB.SetItemInfo(slot.reagents[1].itemID)
        end
    end
    if s.outputItemID then ns.DB.SetItemInfo(s.outputItemID) end
    return s.outputItemID, s.quantityMin, s.quantityMax, reagents
end

function Professions.Scan()
    scheduled = false
    if not C_TradeSkillUI or not isOwnTradeSkill() then return end
    if C_TradeSkillUI.IsTradeSkillReady and not C_TradeSkillUI.IsTradeSkillReady() then return end

    local info = C_TradeSkillUI.GetChildProfessionInfo and C_TradeSkillUI.GetChildProfessionInfo()
    if not info or not info.professionName or (info.maxSkillLevel or 0) == 0 then
        info = C_TradeSkillUI.GetBaseProfessionInfo()
    end
    if not info or not info.professionName then return end

    local key = info.professionName
    local prof = {
        id = info.professionID, skill = info.skillLevel, max = info.maxSkillLevel,
        t = time(), recipes = {},
    }
    local nLearned, nTotal = 0, 0
    for _, recipeID in ipairs(C_TradeSkillUI.GetAllRecipeIDs() or {}) do
        local r = C_TradeSkillUI.GetRecipeInfo(recipeID)
        if r and not r.isDummyRecipe and not r.isRecraft then
            local out, qmin, qmax, reagents = readSchematic(recipeID)
            local rec = {
                n = r.name, l = r.learned and 1 or 0, out = out, qmin = qmin, qmax = qmax,
                r = reagents, diff = r.relativeDifficulty, ups = r.numSkillUps,
                ench = r.isEnchantingRecipe or nil,
            }
            if not r.learned and C_TradeSkillUI.GetRecipeSourceText then
                rec.src = stripCodes(C_TradeSkillUI.GetRecipeSourceText(recipeID))
            end
            if r.learned and C_TradeSkillUI.GetRecipeCooldown then
                local cd = C_TradeSkillUI.GetRecipeCooldown(recipeID)
                if cd and cd > 0 then rec.cdUntil = time() + math.floor(cd) end
            end
            prof.recipes[recipeID] = rec
            nTotal = nTotal + 1
            if r.learned then nLearned = nLearned + 1 end
        end
    end
    prof.nLearned, prof.nTotal = nLearned, nTotal
    ns.DB.Char().professions[key] = prof
    crafterIndex = nil
    if ns.UI then
        ns.UI.SetStatus(string.format("%s %d/%d: %d recetas aprendidas de %d vistas.",
            key, prof.skill or 0, prof.max or 0, nLearned, nTotal))
    end
end

local function schedule()
    if scheduled then return end
    scheduled = true
    C_Timer.After(0.5, Professions.Scan)
end

ns.On("TRADE_SKILL_SHOW", schedule)
ns.On("TRADE_SKILL_LIST_UPDATE", schedule)
ns.On("TRADE_SKILL_DATA_SOURCE_CHANGED", schedule)

function Professions.PrintSummary()
    local any = false
    for ck, c in pairs(AddoneroDB.chars) do
        for name, p in pairs(c.professions or {}) do
            any = true
            ns.Print(string.format("%s – %s %d/%d: %d/%d recetas (%s)", ck, name, p.skill or 0, p.max or 0,
                p.nLearned or 0, p.nTotal or 0, date("%d/%m %H:%M", p.t or 0)))
        end
    end
    if not any then ns.Print("no hay profesiones guardadas: abre la ventana de cada profesión una vez.") end
end

-- Tooltip: precio guardado y qué personaje tuyo lo fabrica
if TooltipDataProcessor and Enum.TooltipDataType and Enum.TooltipDataType.Item then
    TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip, data)
        if not AddoneroDB or not data or not data.id or not tooltip.AddDoubleLine then return end
        local p = ns.DB.GetPrice(data.id)
        if p and p.mv then
            tooltip:AddDoubleLine("Addonero", ns.Money(p.mv) .. (p.qty and (" (" .. p.qty .. ")") or ""), 0.9, 0.72, 0, 1, 1, 1)
        end
        for _, c in ipairs(Professions.Crafters(data.id)) do
            tooltip:AddDoubleLine("Lo fabrica", c.char:match("^([^%-]+)") .. " (" .. c.prof .. ")", 0.9, 0.72, 0, 1, 1, 1)
        end
    end)
end
