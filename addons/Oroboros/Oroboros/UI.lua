-- Oroboros: ventana junto a la casa de subastas + diálogo de importación
local _, ns = ...
local UI = {}
ns.UI = UI

local f, statusText, queueText, footerText, importFrame

local function button(parent, label, w, h)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetSize(w, h or 22)
    b:SetText(label)
    return b
end

local function build()
    if f then return end
    f = CreateFrame("Frame", "OroborosFrame", UIParent, "BasicFrameTemplateWithInset")
    f:SetSize(330, 360)
    f:SetPoint("CENTER")
    f:SetMovable(true)
    f:EnableMouse(true)
    f:RegisterForDrag("LeftButton")
    f:SetScript("OnDragStart", f.StartMoving)
    f:SetScript("OnDragStop", f.StopMovingOrSizing)
    f:SetClampedToScreen(true)
    f:Hide()
    table.insert(UISpecialFrames, "OroborosFrame")   -- se cierra con Escape

    f.title = f:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    f.title:SetPoint("TOP", 0, -5)
    f.title:SetText("Oroboros")

    local scan = button(f, "Escaneo completo", 150)
    scan:SetPoint("TOPLEFT", 12, -32)
    scan:SetScript("OnClick", function() ns.Scanner.FullScan() end)
    f.scanButton = scan

    local imp = button(f, "Importar ruta", 150)
    imp:SetPoint("TOPRIGHT", -12, -32)
    imp:SetScript("OnClick", UI.ShowImport)

    statusText = f:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusText:SetPoint("TOPLEFT", 14, -62)
    statusText:SetPoint("TOPRIGHT", -14, -62)
    statusText:SetHeight(42)
    statusText:SetJustifyH("LEFT")
    statusText:SetJustifyV("TOP")
    statusText:SetWordWrap(true)
    statusText:SetText("Abre la subasta y pulsa Escaneo completo.")

    local nextB = button(f, "Siguiente >", 200, 30)
    nextB:SetPoint("TOPLEFT", 12, -108)
    nextB:SetScript("OnClick", function() ns.Queue.Next() end)   -- clic = evento de hardware

    local skip = button(f, "Saltar", 96, 30)
    skip:SetPoint("TOPRIGHT", -12, -108)
    skip:SetScript("OnClick", function() ns.Queue.Skip() end)

    queueText = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    queueText:SetPoint("TOPLEFT", 14, -148)
    queueText:SetPoint("BOTTOMRIGHT", -14, 34)
    queueText:SetJustifyH("LEFT")
    queueText:SetJustifyV("TOP")

    footerText = f:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
    footerText:SetPoint("BOTTOMLEFT", 14, 12)
    footerText:SetPoint("BOTTOMRIGHT", -14, 12)
    footerText:SetJustifyH("LEFT")

    local elapsed = 0
    f:SetScript("OnUpdate", function(_, dt)
        elapsed = elapsed + dt
        if elapsed < 1 then return end
        elapsed = 0
        UI.UpdateFooter()
    end)
end

function UI.UpdateFooter()
    if not f then return end
    local ok, left = ns.Scanner.CanFullScan()
    local m = ns.DB.Market()
    local last = m.lastFull > 0 and date("%d/%m %H:%M", m.lastFull) or "nunca"
    local scanTxt
    if ns.Scanner.AuctionatorReplicates() then
        scanTxt = "escaneo: lo hace Auctionator"
    else
        scanTxt = ok and "escaneo listo" or string.format("escaneo en %d:%02d", math.floor(left / 60), left % 60)
    end
    local nScans, cap = ns.DB.ScanCount()
    footerText:SetText(string.format("%s  ·  último completo: %s  ·  escaneos guardados: %d/%d%s  ·  %s",
        scanTxt, last, nScans, cap, nScans >= cap and " (exporta)" or "", ns.Money(GetMoney())))
end

function UI.SetStatus(text)
    build()
    statusText:SetText(text)
end

function UI.Refresh()
    if not f then return end
    local items = ns.Queue.Items()
    local _, idx = ns.Queue.Current()
    local pend = ns.Queue.Pending()
    local others = ""
    if #pend > 0 then
        local t = {}
        for _, p in ipairs(pend) do t[#t + 1] = p.name .. " (" .. p.left .. ")" end
        others = "\n|cffaaaaaaPendiente en otros personajes: " .. table.concat(t, ", ") .. "|r"
    end
    if #items == 0 then
        queueText:SetText("Sin ruta para este personaje. Pulsa |cffffd100Importar ruta|r y pega la que genere el planificador." .. others)
    else
        local lines = {}
        local first = math.max(1, (idx or #items) - 2)
        for i = first, math.min(#items, first + 11) do
            local a = items[i]
            local mark
            if a.done >= a.qty then mark = "|TInterface\\RaidFrame\\ReadyCheck-Ready:12|t "
            elseif i == idx then mark = "|cffffd100>|r "
            else mark = "   " end
            lines[#lines + 1] = mark .. ns.Queue.Describe(a)
        end
        local done = 0
        for _, a in ipairs(items) do if a.done >= a.qty then done = done + 1 end end
        table.insert(lines, 1, string.format("|cffaaaaaaRuta: %d/%d hechas|r", done, #items))
        queueText:SetText(table.concat(lines, "\n") .. others)
    end
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
        f:Hide()
    end
end

----------------------------------------------------------------------
-- Importar ruta
----------------------------------------------------------------------
function UI.ShowImport()
    if not importFrame then
        importFrame = CreateFrame("Frame", "OroborosImportFrame", UIParent, "BasicFrameTemplateWithInset")
        importFrame:SetSize(460, 380)
        importFrame:SetPoint("CENTER")
        importFrame:SetFrameStrata("DIALOG")
        importFrame:SetMovable(true)
        importFrame:EnableMouse(true)
        importFrame:RegisterForDrag("LeftButton")
        importFrame:SetScript("OnDragStart", importFrame.StartMoving)
        importFrame:SetScript("OnDragStop", importFrame.StopMovingOrSizing)
        table.insert(UISpecialFrames, "OroborosImportFrame")

        local title = importFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
        title:SetPoint("TOP", 0, -5)
        title:SetText("Pegar ruta (Ctrl+V)")

        local scroll = CreateFrame("ScrollFrame", nil, importFrame, "UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT", 14, -32)
        scroll:SetPoint("BOTTOMRIGHT", -34, 44)

        local edit = CreateFrame("EditBox", nil, scroll)
        edit:SetMultiLine(true)
        edit:SetAutoFocus(false)
        edit:SetFontObject(ChatFontNormal)
        edit:SetWidth(400)
        edit:SetScript("OnEscapePressed", edit.ClearFocus)
        scroll:SetScrollChild(edit)
        importFrame.edit = edit

        local load = button(importFrame, "Cargar ruta", 140)
        load:SetPoint("BOTTOMRIGHT", -14, 12)
        load:SetScript("OnClick", function()
            ns.Queue.Import(edit:GetText() or "")
            importFrame:Hide()
            if f then f:Show() end
        end)

        local add = button(importFrame, "Añadir a la ruta", 130)
        add:SetPoint("RIGHT", load, "LEFT", -8, 0)
        add:SetScript("OnClick", function()
            ns.Queue.Import(edit:GetText() or "", true)
            importFrame:Hide()
            if f then f:Show() end
        end)

        local clear = button(importFrame, "Vaciar", 90)
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
