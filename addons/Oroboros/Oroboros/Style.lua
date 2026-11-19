-- Oroboros: estilo común de las ventanas (oscuro y plano; docs/rediseno-ventanas.md)
local _, ns = ...
local Style = {}
ns.Style = Style

local C = {
    bg      = { 0.06, 0.07, 0.09, 0.92 },
    header  = { 0.10, 0.11, 0.14, 0.98 },
    section = { 0.09, 0.10, 0.13, 0.95 },
    border  = { 0.22, 0.24, 0.28, 1 },
    label   = { 0.58, 0.60, 0.65, 1 },
    value   = { 0.94, 0.94, 0.96, 1 },
    muted   = { 0.45, 0.47, 0.52, 1 },
    accent  = { 0.90, 0.72, 0.30, 1 },
    good    = { 0.35, 0.82, 0.45, 1 },
    bad     = { 0.95, 0.40, 0.38, 1 },
    grid    = { 1, 1, 1, 0.07 },
    ref     = { 0.58, 0.60, 0.65, 0.85 },
}
Style.C = C

local FONT = STANDARD_TEXT_FONT or "Fonts\\FRIZQT__.TTF"
-- papel → tamaño y color
local ROLES = {
    label = { 10, C.label }, value = { 14, C.value }, big = { 22, C.value },
    small = { 11, C.value }, title = { 13, C.value }, muted = { 10, C.muted },
}

function Style.Text(parent, role, layer)
    local r = ROLES[role] or ROLES.value
    local fs = parent:CreateFontString(nil, layer or "OVERLAY")
    fs:SetFont(FONT, r[1], "")
    fs:SetTextColor(unpack(r[2]))
    fs:SetJustifyH("LEFT")
    if fs.SetWordWrap then fs:SetWordWrap(true) end
    return fs
end

function Style.Color(fs, key)
    if fs and C[key] then fs:SetTextColor(unpack(C[key])) end
end

function Style.Hex(key, text)
    local c = C[key] or C.value
    return string.format("|cff%02x%02x%02x%s|r", math.floor(c[1] * 255), math.floor(c[2] * 255), math.floor(c[3] * 255), text)
end

local BACKDROP = { bgFile = "Interface\\Buttons\\WHITE8x8", edgeFile = "Interface\\Buttons\\WHITE8x8", edgeSize = 1 }

function Style.Backdrop(f, bg, border)
    if not f.SetBackdrop and BackdropTemplateMixin and Mixin then Mixin(f, BackdropTemplateMixin) end
    if f.SetBackdrop then
        f:SetBackdrop(BACKDROP)
        f:SetBackdropColor(unpack(bg or C.bg))
        f:SetBackdropBorderColor(unpack(border or C.border))
    end
end

-- Fondo, borde y cabecera con título y «×». Devuelve la cabecera (f.header).
function Style.Panel(f, title)
    Style.Backdrop(f)
    local h = CreateFrame("Frame", nil, f, "BackdropTemplate")
    h:SetPoint("TOPLEFT", 1, -1)
    h:SetPoint("TOPRIGHT", -1, -1)
    h:SetHeight(28)
    Style.Backdrop(h, C.header, C.header)
    h.title = Style.Text(h, "title")
    h.title:SetPoint("LEFT", 10, 0)
    h.title:SetPoint("RIGHT", -30, 0)
    h.title:SetText(title or "")
    local x = CreateFrame("Button", nil, h)
    x:SetSize(24, 24)
    x:SetPoint("RIGHT", -3, 0)
    x.t = Style.Text(x, "title")
    x.t:SetPoint("CENTER")
    x.t:SetText("×")
    Style.Color(x.t, "label")
    x:SetScript("OnEnter", function() Style.Color(x.t, "value") end)
    x:SetScript("OnLeave", function() Style.Color(x.t, "label") end)
    x:SetScript("OnClick", function() f:Hide() end)
    h.close = x
    f.header = h
    return h
end

-- Botón plano. kind: "accent" (dorado) o "neutral". Se ve pulsado y desactivado.
function Style.Button(parent, text, w, h, kind)
    local b = CreateFrame("Button", nil, parent, "BackdropTemplate")
    b:SetSize(w, h or 26)
    local fs = Style.Text(b, "small")
    fs:SetPoint("CENTER")
    fs:SetJustifyH("CENTER")
    b:SetFontString(fs)
    b:SetText(text)
    local accent = kind == "accent"
    local function paint(state)
        local bg = accent and { 0.36, 0.27, 0.08, 0.95 } or { 0.14, 0.15, 0.19, 0.95 }
        if state == "hover" then bg = accent and { 0.48, 0.37, 0.12, 1 } or { 0.20, 0.22, 0.27, 1 }
        elseif state == "down" then bg = accent and { 0.26, 0.19, 0.05, 1 } or { 0.08, 0.09, 0.12, 1 }
        elseif state == "off" then bg = { 0.10, 0.11, 0.14, 0.9 } end
        Style.Backdrop(b, bg, (accent and state ~= "off") and C.accent or C.border)
        fs:SetTextColor(unpack(state == "off" and C.muted or (accent and C.accent or C.value)))
    end
    paint("normal")
    local function enabled() return not b.IsEnabled or b:IsEnabled() end
    b:SetScript("OnEnter", function() if enabled() then paint("hover") end end)
    b:SetScript("OnLeave", function() paint(enabled() and "normal" or "off") end)
    b:SetScript("OnMouseDown", function() if enabled() then paint("down") end end)
    b:SetScript("OnMouseUp", function() if enabled() then paint("hover") end end)
    b:SetScript("OnDisable", function() paint("off") end)
    b:SetScript("OnEnable", function() paint("normal") end)
    b.paint = paint
    return b
end

-- Separador horizontal fino
function Style.Divider(parent)
    local t = parent:CreateTexture(nil, "ARTWORK")
    t:SetColorTexture(unpack(C.border))
    t:SetHeight(1)
    return t
end
