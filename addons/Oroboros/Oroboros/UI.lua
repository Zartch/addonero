-- Oroboros: ventana junto a la casa de subastas + diálogo de importación (estilo de Style.lua)
local _, ns = ...
local UI = {}
ns.UI = UI

local f, statusText, queueText, importFrame
local W, PAD = 330, 12
local QUEUE_TOP = -176          -- donde empieza el texto de la ruta

local function build()
    if f then return end
    local S = ns.Style
    f = CreateFrame("Frame", "OroborosFrame", UIParent, "BackdropTemplate")
    f:SetSize(W, 300)
    f:SetPoint("CENTER")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosFrame")   -- se cierra con Escape
    UI.frame = f

    local h = S.Panel(f, "Oroboros  " .. S.Hex("muted", "v" .. (ns.version or "")))
    f.gold = S.Text(h, "small")
    f.gold:SetPoint("RIGHT", h.close, "LEFT", -6, 0)
    f.gold:SetJustifyH("RIGHT")
    S.Color(f.gold, "accent")

    local scan = S.Button(f, "Escaneo completo", 118, 26, "neutral")
    scan:SetPoint("TOPLEFT", PAD, -38)
    scan:SetScript("OnClick", function() ns.Scanner.FullScan() end)
    f.scanButton = scan

    local inv = S.Button(f, "Lo que tienes", 92, 26, "neutral")
    inv:SetPoint("LEFT", scan, "RIGHT", 4, 0)
    inv:SetScript("OnClick", function() ns.Inventory.Toggle() end)

    local imp = S.Button(f, "Importar ruta", 88, 26, "neutral")
    imp:SetPoint("TOPRIGHT", -PAD, -38)
    imp:SetScript("OnClick", UI.ShowImport)

    local stLabel = S.Text(f, "label")
    stLabel:SetPoint("TOPLEFT", PAD, -74)
    stLabel:SetText("ESTADO")
    statusText = S.Text(f, "small")
    statusText:SetPoint("TOPLEFT", PAD, -88)
    statusText:SetWidth(W - 2 * PAD)
    statusText:SetJustifyV("TOP")
    if statusText.SetMaxLines then statusText:SetMaxLines(2) end
    statusText:SetText("Abre la subasta: el escaneo se lanza solo si toca.")

    local nextB = S.Button(f, "Siguiente  >", 200, 30, "accent")
    nextB:SetPoint("TOPLEFT", PAD, -122)
    nextB:SetScript("OnClick", function() ns.Queue.Next() end)   -- clic = evento de hardware

    local skip = S.Button(f, "Saltar", 98, 30, "neutral")
    skip:SetPoint("TOPRIGHT", -PAD, -122)
    skip:SetScript("OnClick", function() ns.Queue.Skip() end)

    local qLabel = S.Text(f, "label")
    qLabel:SetPoint("TOPLEFT", PAD, -162)
    qLabel:SetText("RUTA")
    queueText = S.Text(f, "small")
    queueText:SetPoint("TOPLEFT", PAD, QUEUE_TOP)
    queueText:SetWidth(W - 2 * PAD)
    queueText:SetJustifyV("TOP")
    if queueText.SetSpacing then queueText:SetSpacing(3) end

    -- Pie: tres datos con etiqueta y valor
    f.footDiv = S.Divider(f)
    f.foot = {}
    for k, label in ipairs({ "PRÓXIMO ESCANEO", "ÚLTIMO", "SIN EXPORTAR" }) do
        local cell = { label = S.Text(f, "label"), value = S.Text(f, "value") }
        cell.label:SetText(label)
        f.foot[k] = cell
    end

    local elapsed = 0
    f:SetScript("OnUpdate", function(_, dt)
        elapsed = elapsed + dt
        if elapsed < 1 then return end
        elapsed = 0
        UI.UpdateFooter()
    end)
end

-- Coloca el pie debajo de la ruta y ajusta la altura de la ventana
local function layout(queueLines)
    local qh = math.max(28, queueLines * 16 + 4)
    local y = QUEUE_TOP - qh - 6
    f.footDiv:ClearAllPoints()
    f.footDiv:SetPoint("TOPLEFT", PAD, y)
    f.footDiv:SetPoint("TOPRIGHT", -PAD, y)
    local colX = { 0, 124, 234 }      -- la primera etiqueta («PRÓXIMO ESCANEO») es la más larga
    for k, cell in ipairs(f.foot) do
        cell.label:ClearAllPoints(); cell.label:SetPoint("TOPLEFT", PAD + colX[k], y - 10)
        cell.value:ClearAllPoints(); cell.value:SetPoint("TOPLEFT", PAD + colX[k], y - 24)
    end
    f:SetHeight(-(y - 46) + 4)
end

function UI.UpdateFooter()
    if not f then return end
    local S = ns.Style
    local ok, left = ns.Scanner.CanFullScan()
    local m = ns.DB.Market()
    local nextTxt, nextTone
    if ns.Scanner.state ~= "idle" then
        nextTxt, nextTone = "escaneando", "accent"
    elseif ns.Scanner.AuctionatorReplicates() then
        nextTxt, nextTone = "Auctionator", "label"
    elseif ok then
        nextTxt, nextTone = "listo", "good"
    else
        nextTxt, nextTone = string.format("en %d:%02d", math.floor(left / 60), left % 60), "value"
    end
    f.foot[1].value:SetText(nextTxt); S.Color(f.foot[1].value, nextTone)
    f.foot[2].value:SetText(m.lastFull > 0 and date("%d/%m %H:%M", m.lastFull) or "nunca")
    local pend, cap = ns.DB.PendingScans()
    f.foot[3].value:SetText(string.format("%d/%d%s", pend, cap, pend >= cap - 2 and "  exporta" or ""))
    S.Color(f.foot[3].value, pend >= cap and "bad" or (pend >= cap - 2 and "accent" or "value"))
    f.gold:SetText(ns.Coin(GetMoney()))
end

-- Botón de escaneo: pulsado y desactivado mientras se escanea, sea a mano o automático
function UI.SetScanning(on)
    build()
    local b = f.scanButton
    if on then
        b:SetText("Escaneando…")
        if b.SetButtonState then b:SetButtonState("PUSHED", true) end
        if b.Disable then b:Disable() end
    else
        b:SetText("Escaneo completo")
        if b.SetButtonState then b:SetButtonState("NORMAL") end
        if b.Enable then b:Enable() end
    end
    UI.UpdateFooter()
end

function UI.SetStatus(text)
    UI.lastStatus = text
    build()
    statusText:SetText(text)
end

function UI.Refresh()
    if not f then return end
    local S = ns.Style
    local items = ns.Queue.Items()
    local _, idx = ns.Queue.Current()
    local pend = ns.Queue.Pending()
    local lines = {}
    if #items == 0 then
        lines[1] = "Sin ruta para este personaje."
        lines[2] = S.Hex("label", "Pulsa ") .. S.Hex("accent", "Importar ruta") .. S.Hex("label", " y pega la del planificador.")
    else
        local done = 0
        for _, a in ipairs(items) do if a.done >= a.qty then done = done + 1 end end
        lines[1] = S.Hex("label", string.format("%d de %d hechas", done, #items))
        local first = math.max(1, (idx or #items) - 2)
        for i = first, math.min(#items, first + 11) do
            local a = items[i]
            local txt = ns.Queue.Describe(a)
            if a.done >= a.qty then
                lines[#lines + 1] = "|TInterface\\RaidFrame\\ReadyCheck-Ready:12|t " .. S.Hex("muted", txt)
            elseif i == idx then
                lines[#lines + 1] = S.Hex("accent", "> " .. txt)
            else
                lines[#lines + 1] = "   " .. txt
            end
        end
    end
    if #pend > 0 then
        local t = {}
        for _, p in ipairs(pend) do t[#t + 1] = p.name .. " (" .. p.left .. ")" end
        lines[#lines + 1] = S.Hex("label", "Pendiente en otros personajes: " .. table.concat(t, ", "))
    end
    queueText:SetText(table.concat(lines, "\n"))
    layout(#lines)
    UI.UpdateFooter()
end

function UI.Toggle()
    build()
    if f:IsShown() then f:Hide() else f:Show(); UI.Refresh() end
end

function UI.OnAuctionHouse(open)
    build()
    if open then
        f:ClearAllPoints()
        if AuctionHouseFrame then
            f:SetPoint("TOPLEFT", AuctionHouseFrame, "TOPRIGHT", 4, 0)
        else
            f:SetPoint("CENTER")
        end
        f:Show()
        UI.Refresh()
    else
        UI.SetScanning(false)
        f:Hide()
    end
end

----------------------------------------------------------------------
-- Importar ruta
----------------------------------------------------------------------
function UI.ShowImport()
    local S = ns.Style
    if not importFrame then
        importFrame = CreateFrame("Frame", "OroborosImportFrame", UIParent, "BackdropTemplate")
        importFrame:SetSize(480, 400)
        importFrame:SetPoint("CENTER")
        importFrame:SetFrameStrata("DIALOG")
        importFrame:SetMovable(true)
        importFrame:EnableMouse(true)
        importFrame:RegisterForDrag("LeftButton")
        importFrame:SetScript("OnDragStart", importFrame.StartMoving)
        importFrame:SetScript("OnDragStop", importFrame.StopMovingOrSizing)
        table.insert(UISpecialFrames, "OroborosImportFrame")
        S.Panel(importFrame, "Pegar ruta  " .. S.Hex("muted", "Ctrl+V"))

        local box = CreateFrame("Frame", nil, importFrame, "BackdropTemplate")
        box:SetPoint("TOPLEFT", PAD, -38)
        box:SetPoint("BOTTOMRIGHT", -PAD, 50)
        S.Backdrop(box, S.C.section, S.C.border)

        local scroll = CreateFrame("ScrollFrame", nil, box, "UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT", 8, -8)
        scroll:SetPoint("BOTTOMRIGHT", -28, 8)

        local edit = CreateFrame("EditBox", nil, scroll)
        edit:SetMultiLine(true)
        edit:SetAutoFocus(false)
        edit:SetFontObject(ChatFontNormal)
        edit:SetWidth(410)
        edit:SetScript("OnEscapePressed", edit.ClearFocus)
        scroll:SetScrollChild(edit)
        importFrame.edit = edit

        local load = S.Button(importFrame, "Cargar ruta", 140, 28, "accent")
        load:SetPoint("BOTTOMRIGHT", -PAD, 12)
        load:SetScript("OnClick", function()
            ns.Queue.Import(edit:GetText() or "")
            importFrame:Hide()
            if f then f:Show() end
        end)

        local add = S.Button(importFrame, "Añadir a la ruta", 140, 28, "neutral")
        add:SetPoint("RIGHT", load, "LEFT", -8, 0)
        add:SetScript("OnClick", function()
            ns.Queue.Import(edit:GetText() or "", true)
            importFrame:Hide()
            if f then f:Show() end
        end)

        local clear = S.Button(importFrame, "Vaciar", 90, 28, "neutral")
        clear:SetPoint("RIGHT", add, "LEFT", -8, 0)
        clear:SetScript("OnClick", function() edit:SetText("") edit:SetFocus() end)
    end
    local r = OroborosDB.routes[ns.CharKey()]
    importFrame.edit:SetText((r and r.text) or "")
    importFrame:Show()
    importFrame.edit:SetFocus()
end

----------------------------------------------------------------------
-- Atajo de teclado (Opciones > Atajos > Oroboros). Pulsar una tecla también
-- cuenta como evento de hardware, así que sirve igual que el botón.
----------------------------------------------------------------------
BINDING_HEADER_OROBOROS = "Oroboros"
BINDING_NAME_OROBOROS_NEXT = "Siguiente acción de la ruta"
function Oroboros_Next() ns.Queue.Next() end
