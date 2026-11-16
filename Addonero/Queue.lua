-- Addonero: ruta importada y cola de acciones.
-- Cada acción protegida (comprar, publicar, fabricar) se ejecuta desde un clic tuyo:
-- Blizzard exige un evento de hardware y automatizarlo del todo no está permitido.
local _, ns = ...
local Queue = {}
ns.Queue = Queue

--[[ Formato de ruta (una acción por línea, '#' para comentarios):
  BUY   <itemID> <cantidad> <precioMaxUnidad>
  SELL  <itemID> <cantidad> <precioMinUnidad>
  CRAFT <recipeID> <veces>
  NOTE  <texto libre>
  CHAR  <Nombre>     (lo que sigue es para ese personaje; pegas una vez y cada uno ve su parte al entrar)
  HOLD  <itemID> <cantidad> <objetivo> <stop> <AAAA-MM-DD> [entrada]   (apuesta: se guarda para avisarte)
Los precios aceptan cobre (12345) o formato 1g23s45c.
]]

local step = { phase = "idle" }   -- estado de la acción actual

local function setStatus(t) if ns.UI then ns.UI.SetStatus(t) end end
local function refresh() if ns.UI then ns.UI.Refresh() end end

function Queue.ParseMoney(s)
    if not s then return nil end
    local n = tonumber(s)
    if n then return math.floor(n) end
    local g = tonumber(s:match("(%d+)g")) or 0
    local sv = tonumber(s:match("(%d+)s")) or 0
    local c = tonumber(s:match("(%d+)c")) or 0
    if g + sv + c == 0 and not s:match("0[gsc]") then return nil end
    return g * 10000 + sv * 100 + c
end

-- Devuelve items, errores
function Queue.Parse(text)
    local items, errors = {}, {}
    local lineNo = 0
    for line in (text .. "\n"):gmatch("(.-)\r?\n") do
        lineNo = lineNo + 1
        line = line:gsub("#.*$", ""):match("^%s*(.-)%s*$")
        if line ~= "" then
            local op, a, b, c = line:match("^(%a+)%s*(%S*)%s*(%S*)%s*(.-)$")
            op = op and op:upper()
            if op == "BUY" or op == "SELL" then
                local id, qty, price = tonumber(a), tonumber(b), Queue.ParseMoney(c)
                if id and qty and qty > 0 and price then
                    items[#items + 1] = { op = op, itemID = id, qty = qty, price = price, done = 0 }
                else
                    errors[#errors + 1] = string.format("línea %d: %s", lineNo, line)
                end
            elseif op == "CRAFT" then
                local id, times = tonumber(a), tonumber(b)
                if id and times and times > 0 then
                    items[#items + 1] = { op = op, recipeID = id, qty = times, done = 0 }
                else
                    errors[#errors + 1] = string.format("línea %d: %s", lineNo, line)
                end
            elseif op == "HOLD" then
                local id, qty = tonumber(a), tonumber(b)
                local t, s, d, e = c:match("^(%S+)%s+(%S+)%s+(%d%d%d%d%-%d%d%-%d%d)%s*(%S*)$")
                local target, stop = Queue.ParseMoney(t), Queue.ParseMoney(s)
                if id and qty and qty > 0 and target and stop then
                    items[#items + 1] = { op = op, itemID = id, qty = qty, price = target, stop = stop, due = d,
                                          entry = Queue.ParseMoney(e), done = 0 }
                else
                    errors[#errors + 1] = string.format("línea %d: %s", lineNo, line)
                end
            elseif op == "NOTE" then
                items[#items + 1] = { op = op, text = line:match("^%a+%s+(.*)$") or "", qty = 1, done = 0 }
            else
                errors[#errors + 1] = string.format("línea %d: %s", lineNo, line)
            end
        end
    end
    return items, errors
end

local function myRoute()
    return AddoneroDB.routes[ns.CharKey()]
end

function Queue.ResolveChar(name)
    for ck in pairs(AddoneroDB.chars) do
        if ck:match("^([^%-]+)") == name then return ck end
    end
    return name .. "-" .. (ns.CharKey():match("%-(.+)$") or "")
end

-- Divide un texto con líneas "CHAR Nombre" en { { char = charKey, text = "..." }, ... }
function Queue.Split(text)
    local order, byChar, cur = {}, {}, nil
    for line in (text .. "\n"):gmatch("(.-)\r?\n") do
        local name = line:match("^%s*[Cc][Hh][Aa][Rr]%s+(%S+)")
        if name then
            cur = Queue.ResolveChar(name)
        else
            cur = cur or ns.CharKey()
            if not byChar[cur] then byChar[cur] = {}; order[#order + 1] = cur end
            table.insert(byChar[cur], line)
        end
    end
    local out = {}
    for _, ck in ipairs(order) do out[#out + 1] = { char = ck, text = table.concat(byChar[ck], "\n") } end
    return out
end

-- append = true añade a la ruta que ya hubiera en vez de sustituirla
function Queue.Import(text, append)
    local mine, nItems, nErr = ns.CharKey(), 0, 0
    local parts, summary = Queue.Split(text), {}
    for _, s in ipairs(parts) do
        local items, errors = Queue.Parse(s.text)
        local short = s.char:match("^([^%-]+)")
        for _, e in ipairs(errors) do ns.Print("|cffff8040ignorada|r (" .. short .. ") " .. e) end
        if #items > 0 or #parts == 1 then
            local r = AddoneroDB.routes[s.char]
            if append and r and r.items then
                for _, it in ipairs(items) do table.insert(r.items, it) end
                r.text = (r.text or "") .. "\n" .. s.text
            else
                AddoneroDB.routes[s.char] = { text = s.text, t = time(), items = items, idx = 1 }
            end
            summary[#summary + 1] = short .. " " .. #items
            if s.char == mine then nItems, nErr = #items, #errors end
        end
    end
    step = { phase = "idle" }
    ns.Print("ruta cargada: " .. (#summary > 0 and table.concat(summary, ", ") or "0") .. " acciones."
        .. (#summary > 1 and " Cada personaje verá su parte al entrar." or ""))
    refresh()
    return nItems, nErr
end

function Queue.Items()
    local r = myRoute()
    return (r and r.items) or {}
end

-- Otros personajes con acciones pendientes: { {name, left}, ... }
function Queue.Pending()
    local out = {}
    for ck, r in pairs(AddoneroDB.routes) do
        if ck ~= ns.CharKey() and r.items then
            local left = 0
            for _, a in ipairs(r.items) do if a.done < a.qty then left = left + 1 end end
            if left > 0 then out[#out + 1] = { name = ck:match("^([^%-]+)"), left = left } end
        end
    end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

function Queue.Current()
    local r = myRoute()
    if not r or not r.items then return nil end
    while r.items[r.idx] and r.items[r.idx].done >= r.items[r.idx].qty do r.idx = r.idx + 1 end
    return r.items[r.idx], r.idx
end

function Queue.Skip()
    local r = myRoute()
    if r and r.items and r.items[r.idx] then r.idx = r.idx + 1 end
    step = { phase = "idle" }
    refresh()
end

function Queue.Describe(a)
    if not a then return "—" end
    local left = a.qty - a.done
    if a.op == "BUY" then
        return string.format("Comprar %d× %s máx %s", left, ns.DB.ItemName(a.itemID), ns.Money(a.price))
    elseif a.op == "SELL" then
        return string.format("Vender %d× %s mín %s", left, ns.DB.ItemName(a.itemID), ns.Money(a.price))
    elseif a.op == "CRAFT" then
        local info = C_TradeSkillUI and C_TradeSkillUI.GetRecipeInfo and C_TradeSkillUI.GetRecipeInfo(a.recipeID)
        return string.format("Fabricar %d× %s", left, (info and info.name) or ("receta " .. a.recipeID))
    elseif a.op == "HOLD" then
        return string.format("Apuesta: guardar %d× %s hasta %s (objetivo %s)", a.qty, ns.DB.ItemName(a.itemID),
            a.due or "?", ns.Money(a.price))
    else
        return "Nota: " .. (a.text or "")
    end
end

----------------------------------------------------------------------
-- Bolsas
----------------------------------------------------------------------
local function findInBags(itemID)
    local total, loc = 0, nil
    local last = NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4
    for bag = 0, last do
        for slot = 1, (C_Container.GetContainerNumSlots(bag) or 0) do
            local info = C_Container.GetContainerItemInfo(bag, slot)
            if info and info.itemID == itemID then
                total = total + (info.stackCount or 1)
                if not loc and not info.isLocked then loc = ItemLocation:CreateFromBagAndSlot(bag, slot) end
            end
        end
    end
    return total, loc
end
Queue.findInBags = findInBags

----------------------------------------------------------------------
-- Planificación de cada paso tras la búsqueda
----------------------------------------------------------------------
local function planBuy(a, result)
    local left = a.qty - a.done
    if result.commodity then
        local n, cost = 0, 0
        for _, r in ipairs(result.rows) do
            if not r.mine then
                if r.unitPrice > a.price then break end
                local take = math.min(r.qty, left - n)
                n, cost = n + take, cost + take * r.unitPrice
                if n >= left then break end
            end
        end
        if n == 0 then
            step = { phase = "idle" }
            local best = result.rows[1] and result.rows[1].unitPrice
            setStatus(string.format("Nada por debajo de %s (más barato: %s). Salta o espera.",
                ns.Money(a.price), ns.Money(best)))
            return
        end
        step = { phase = "buy_commodity", n = n, est = cost }
        setStatus(string.format("Comprar %d× por ~%s (%s/u). Pulsa Siguiente.", n, ns.Money(cost), ns.Money(cost / n)))
    else
        for _, r in ipairs(result.rows) do
            if not r.mine and r.unitPrice <= a.price then
                step = { phase = "buy_item", auctionID = r.auctionID, buyout = r.buyout, n = r.qty }
                setStatus(string.format("Comprar subasta de %d por %s. Pulsa Siguiente.", r.qty, ns.Money(r.buyout)))
                return
            end
        end
        step = { phase = "idle" }
        setStatus("No hay subastas por debajo de " .. ns.Money(a.price) .. ".")
    end
end

local function planSell(a, result)
    local inBags = findInBags(a.itemID)
    local n = math.min(a.qty - a.done, inBags)
    if n <= 0 then
        step = { phase = "idle" }
        setStatus("No tienes " .. ns.DB.ItemName(a.itemID) .. " en las bolsas.")
        return
    end
    local cheapest
    for _, r in ipairs(result.rows) do
        if not r.mine then cheapest = r.unitPrice break end
    end
    local price
    if cheapest then
        price = math.floor(cheapest) - ns.Cfg("undercut")
    else
        local p = ns.DB.GetPrice(a.itemID)
        price = (p and p.mv) or a.price
    end
    if price < a.price then
        step = { phase = "idle" }
        setStatus(string.format("El mercado está en %s, por debajo de tu mínimo %s. No publico.",
            ns.Money(cheapest), ns.Money(a.price)))
        return
    end
    if not result.commodity then n = 1 end      -- equipo: una subasta por clic
    step = { phase = "post", commodity = result.commodity, n = n, price = price }
    setStatus(string.format("Publicar %d× a %s/u (neto ~%s). Pulsa Siguiente.",
        n, ns.Money(price), ns.Money(price * n * (1 - ns.Cfg("ahCut")))))
end

----------------------------------------------------------------------
-- Botón "Siguiente": SIEMPRE se llama desde OnClick (evento de hardware)
----------------------------------------------------------------------
function Queue.Next()
    local a = Queue.Current()
    if not a then
        local pend = Queue.Pending()
        if #pend > 0 then
            setStatus("Ruta de este personaje terminada. Ahora entra con " .. pend[1].name .. ".")
        else
            setStatus("Ruta terminada.")
        end
        refresh()
        return
    end

    if a.op == "NOTE" or a.op == "HOLD" then
        if a.op == "HOLD" then
            ns.DB.SetPosition(a)
            setStatus("Apuesta anotada: " .. ns.DB.ItemName(a.itemID) .. ". El planificador te avisará de cuándo vender.")
        end
        a.done = a.qty
        step = { phase = "idle" }
        refresh()
        return
    end

    if a.op == "CRAFT" then
        if not (C_TradeSkillUI and C_TradeSkillUI.CraftRecipe) then return end
        local ok, err = pcall(C_TradeSkillUI.CraftRecipe, a.recipeID, a.qty - a.done)
        if ok then
            a.done = a.qty
            setStatus("Fabricando… (si no empieza, abre la ventana de esa profesión)")
        else
            setStatus("No se pudo fabricar: abre la profesión correcta. " .. tostring(err))
        end
        refresh()
        return
    end

    if not ns.Scanner.ahOpen then setStatus("Abre la casa de subastas.") return end

    if step.phase == "idle" then
        step = { phase = "searching" }
        setStatus("Buscando " .. ns.DB.ItemName(a.itemID) .. "…")
        ns.Scanner.Search(a.itemID, function(result)
            if a.op == "BUY" then planBuy(a, result) else planSell(a, result) end
        end)

    elseif step.phase == "searching" or step.phase == "waiting_price" then
        setStatus("Esperando respuesta del servidor…")

    elseif step.phase == "buy_commodity" then
        if GetMoney() < step.est then setStatus("No tienes oro suficiente.") step = { phase = "idle" } return end
        step.phase = "waiting_price"
        C_AuctionHouse.StartCommoditiesPurchase(a.itemID, step.n)

    elseif step.phase == "confirm_commodity" then
        step.phase = "buying"
        C_AuctionHouse.ConfirmCommoditiesPurchase(a.itemID, step.n)

    elseif step.phase == "buy_item" then
        if GetMoney() < step.buyout then setStatus("No tienes oro suficiente.") step = { phase = "idle" } return end
        C_AuctionHouse.PlaceBid(step.auctionID, step.buyout)
        a.done = a.done + step.n
        step = { phase = "idle" }
        setStatus("Compra enviada.")
        refresh()

    elseif step.phase == "post" then
        local _, loc = findInBags(a.itemID)
        if not loc then setStatus("Objeto bloqueado o no encontrado; vuelve a pulsar en un momento.") return end
        local duration = ns.Cfg("postDuration")
        if step.commodity then
            C_AuctionHouse.PostCommodity(loc, duration, step.n, step.price)
            a.done = a.done + step.n
            step = { phase = "idle" }
        else
            C_AuctionHouse.PostItem(loc, duration, 1, nil, step.price)
            a.done = a.done + 1
            if a.done < a.qty and findInBags(a.itemID) > 1 then
                setStatus(string.format("Publicado. Quedan %d; pulsa para el siguiente a %s.",
                    a.qty - a.done, ns.Money(step.price)))
            else
                step = { phase = "idle" }
            end
        end
        refresh()
    end
end

----------------------------------------------------------------------
-- Respuestas del servidor a la compra de commodities
----------------------------------------------------------------------
ns.On("COMMODITY_PRICE_UPDATED", function(unitPrice, totalPrice)
    if step.phase ~= "waiting_price" then return end
    local a = Queue.Current()
    if not a then return end
    if unitPrice > a.price then
        C_AuctionHouse.CancelCommoditiesPurchase()
        step = { phase = "idle" }
        setStatus(string.format("El precio subió a %s/u (máx %s). Cancelado; pulsa para reintentar.",
            ns.Money(unitPrice), ns.Money(a.price)))
        return
    end
    step.phase = "confirm_commodity"
    setStatus(string.format("Precio final %s (%s/u). Pulsa Siguiente para CONFIRMAR.",
        ns.Money(totalPrice), ns.Money(unitPrice)))
end)

ns.On("COMMODITY_PURCHASE_SUCCEEDED", function()
    local a = Queue.Current()
    if a and step.phase == "buying" then
        a.done = a.done + step.n
        step = { phase = "idle" }
        setStatus("Compra completada.")
        refresh()
    end
end)

ns.On("COMMODITY_PURCHASE_FAILED", function()
    if step.phase == "buying" or step.phase == "waiting_price" then
        step = { phase = "idle" }
        setStatus("La compra falló (alguien se adelantó). Pulsa para reintentar.")
    end
end)

ns.On("AUCTION_HOUSE_CLOSED", function() step = { phase = "idle" } end)

function Queue.Phase() return step.phase end
