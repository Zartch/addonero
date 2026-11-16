-- Addonero: núcleo, utilidades, eventos y comandos
local ADDON, ns = ...
ns.name = ADDON
ns.version = "0.5.0"

local DEFAULTS = {
    historyDays   = 30,     -- días de histórico diario por objeto
    mvPercent     = 0.15,   -- % más barato de la cantidad usado para el "valor de mercado"
    postDuration  = 2,      -- 1 = 12h, 2 = 24h, 3 = 48h
    undercut      = 1,      -- cobre que se rebaja respecto al más barato ajeno
    ahCut         = 0.05,   -- comisión de la casa de subastas
}

----------------------------------------------------------------------
-- Utilidades
----------------------------------------------------------------------
function ns.Print(...)
    local msg = strjoin(" ", tostringall(...))
    DEFAULT_CHAT_FRAME:AddMessage("|cffe6b800Addonero|r: " .. msg)
end

function ns.Money(copper)
    if not copper then return "?" end
    copper = math.floor(copper + 0.5)
    local g = math.floor(copper / 10000)
    local s = math.floor((copper % 10000) / 100)
    local c = copper % 100
    if g > 0 then return string.format("%dg %02ds %02dc", g, s, c) end
    if s > 0 then return string.format("%ds %02dc", s, c) end
    return string.format("%dc", c)
end

function ns.Today()
    return date("%Y-%m-%d")
end

-- Clave de mercado: Forever no tiene reinos clásicos, pero la subasta va por
-- conjunto de reglas (ruleset) y facción. GetNormalizedRealmName devuelve el
-- identificador que use el cliente; lo combinamos con la facción.
function ns.MarketKey()
    local realm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName() or "?"
    local faction = UnitFactionGroup("player") or "Neutral"
    return realm .. "-" .. faction
end

function ns.CharKey()
    local name = UnitName("player") or "?"
    local realm = (GetNormalizedRealmName and GetNormalizedRealmName()) or GetRealmName() or "?"
    return name .. "-" .. realm
end

function ns.Cfg(key)
    local db = AddoneroDB
    if db and db.config and db.config[key] ~= nil then return db.config[key] end
    return DEFAULTS[key]
end

----------------------------------------------------------------------
-- Bus de eventos sencillo: cada módulo registra handlers
----------------------------------------------------------------------
local frame = CreateFrame("Frame")
ns.eventFrame = frame
local handlers = {}

function ns.On(event, fn)
    if not handlers[event] then
        -- pcall: si un evento no existe en esta versión del cliente, no rompemos la carga
        if not pcall(frame.RegisterEvent, frame, event) then return false end
        handlers[event] = {}
    end
    table.insert(handlers[event], fn)
end

frame:SetScript("OnEvent", function(_, event, ...)
    local list = handlers[event]
    if not list then return end
    for i = 1, #list do
        local ok, err = pcall(list[i], ...)
        if not ok then ns.Print("|cffff4040error|r en " .. event .. ": " .. tostring(err)) end
    end
end)

ns.On("ADDON_LOADED", function(name)
    if name ~= ADDON then return end
    ns.DB.Init(DEFAULTS)
    ns.Print("v" .. ns.version .. " cargado. /addonero para ayuda.")
end)

ns.On("PLAYER_LOGIN", function()
    ns.DB.SnapshotCharacter()
end)

ns.On("PLAYER_MONEY", function()
    ns.DB.SnapshotCharacter()
end)

ns.bankOpen = false
local function bankChanged() if ns.bankOpen then ns.DB.SnapshotBank() end end

ns.On("BAG_UPDATE_DELAYED", function()
    ns.DB.SnapshotBags()
    bankChanged()
end)

ns.On("BANKFRAME_OPENED", function() ns.bankOpen = true; ns.DB.SnapshotBank() end)
ns.On("BANKFRAME_CLOSED", function() ns.bankOpen = false end)
ns.On("PLAYERBANKSLOTS_CHANGED", bankChanged)
ns.On("PLAYERREAGENTBANKSLOTS_CHANGED", bankChanged)

----------------------------------------------------------------------
-- Comandos
----------------------------------------------------------------------
SLASH_ADDONERO1 = "/addonero"
SLASH_ADDONERO2 = "/adn"
SlashCmdList.ADDONERO = function(msg)
    local cmd, rest = (msg or ""):match("^%s*(%S*)%s*(.-)%s*$")
    cmd = (cmd or ""):lower()
    if cmd == "" or cmd == "help" then
        ns.Print("comandos:")
        ns.Print("  /adn show     – mostrar/ocultar la ventana")
        ns.Print("  /adn scan     – escaneo completo (con la subasta abierta)")
        ns.Print("  /adn price <itemID|link> – ver precio guardado")
        ns.Print("  /adn prof     – profesiones de todos tus personajes")
        ns.Print("  /adn quien <itemID|link> – qué personaje lo fabrica")
        ns.Print("  /adn banquero – marcar este personaje como el que compra y vende")
        ns.Print("  /adn import   – pegar una ruta generada fuera del juego")
        ns.Print("  /adn compras  – últimas compras y ventas registradas")
        ns.Print("  /adn stats    – tamaño de la base de datos")
        ns.Print("  /adn set <clave> <valor> – cambiar configuración")
        ns.Print("Los datos se escriben a disco al hacer /reload o salir.")
    elseif cmd == "show" then
        ns.UI.Toggle()
    elseif cmd == "scan" then
        ns.Scanner.FullScan()
    elseif cmd == "price" then
        local id = tonumber(rest) or tonumber((rest or ""):match("item:(%d+)"))
        if not id then ns.Print("uso: /adn price <itemID|link>") return end
        local p = ns.DB.GetPrice(id)
        if not p then ns.Print("sin datos para " .. id) return end
        ns.Print(string.format("%s  min %s  valor %s  cantidad %d  (%s)",
            ns.DB.ItemName(id), ns.Money(p.min), ns.Money(p.mv), p.qty or 0,
            date("%d/%m %H:%M", p.t or 0)))
    elseif cmd == "quien" then
        local id = tonumber(rest) or tonumber((rest or ""):match("item:(%d+)"))
        if not id then ns.Print("uso: /adn quien <itemID|link>") return end
        local list = ns.Professions.Crafters(id)
        if #list == 0 then ns.Print("ningún personaje tuyo sabe fabricar " .. ns.DB.ItemName(id) .. ".") end
        for _, c in ipairs(list) do
            ns.Print(string.format("%s lo fabrica %s (%s)", ns.DB.ItemName(id), c.char:match("^([^%-]+)"), c.prof))
        end
    elseif cmd == "banquero" then
        if AddoneroDB.config.banker == ns.CharKey() then
            AddoneroDB.config.banker = nil
            ns.Print("este personaje ya no es el banquero.")
        else
            AddoneroDB.config.banker = ns.CharKey()
            ns.Print("banquero: " .. ns.CharKey() .. ". El planificador le dará todas las compras y ventas.")
        end
    elseif cmd == "prof" then
        ns.Professions.PrintSummary()
    elseif cmd == "import" then
        ns.UI.ShowImport()
    elseif cmd == "compras" then
        local L = AddoneroDB.ledger
        if #L == 0 then ns.Print("todavía no hay compras ni ventas registradas.") end
        for i = math.max(1, #L - 9), #L do
            local e = L[i]
            ns.Print(string.format("%s %s %d× %s a %s", date("%d/%m %H:%M", e.t), e.op == "BUY" and "compra" or "venta",
                e.qty, ns.DB.ItemName(e.item), ns.Money(e.unit)))
        end
    elseif cmd == "stats" then
        ns.DB.PrintStats()
    elseif cmd == "set" then
        local k, v = rest:match("^(%S+)%s+(%S+)$")
        if not k or DEFAULTS[k] == nil then
            ns.Print("claves: historyDays, mvPercent, postDuration, undercut, ahCut")
            return
        end
        AddoneroDB.config[k] = tonumber(v) or v
        ns.Print(k .. " = " .. tostring(AddoneroDB.config[k]))
    else
        ns.Print("comando desconocido. /addonero help")
    end
end
