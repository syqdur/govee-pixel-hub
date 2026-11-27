local frame = CreateFrame("Frame")

local function SafeCall(fn, ...)
    if type(fn) ~= "function" then
        return nil
    end
    local ok, a, b, c = pcall(fn, ...)
    if ok then
        return a, b, c
    end
    return nil
end

local function Round1(val)
    if type(val) ~= "number" then
        return 0
    end
    return math.floor(val * 10 + 0.5) / 10
end

local function GetSpecName()
    if GetSpecialization and GetSpecializationInfo then
        local idx = SafeCall(GetSpecialization)
        if idx then
            local _, name = SafeCall(GetSpecializationInfo, idx)
            if name then
                return name
            end
        end
    end
    return ""
end

local function GetBestCrit()
    local best = SafeCall(GetCritChance) or 0
    if GetRangedCritChance then
        local r = SafeCall(GetRangedCritChance) or 0
        if r > best then best = r end
    end
    if GetSpellCritChance then
        for school = 2, 7 do
            local s = SafeCall(GetSpellCritChance, school) or 0
            if s > best then best = s end
        end
    end
    return Round1(best)
end

local function GetBestHaste()
    local h = SafeCall(GetHaste)
    if type(h) == "number" then
        return Round1(h)
    end
    if GetCombatRatingBonus and CR_HASTE_MELEE then
        return Round1(SafeCall(GetCombatRatingBonus, CR_HASTE_MELEE) or 0)
    end
    return 0
end

local function UpdateStats()
    local name = UnitName("player") or "Hero"
    local _, classFile = UnitClass("player")
    local level = UnitLevel("player") or 1
    local hpMax = UnitHealthMax("player") or 0
    local _, equippedIlvl = SafeCall(GetAverageItemLevel)
    local ilvl = math.floor((equippedIlvl or 0) + 0.5)

    local crit = GetBestCrit()
    local haste = GetBestHaste()
    local mastery = Round1(SafeCall(GetMasteryEffect) or 0)
    local vers = 0
    if GetCombatRatingBonus and CR_VERSATILITY_DAMAGE_DONE then
        vers = Round1(SafeCall(GetCombatRatingBonus, CR_VERSATILITY_DAMAGE_DONE) or 0)
    end

    local money = GetMoney() or 0
    local gold = math.floor(money / 10000)
    local zone = GetRealZoneText() or GetZoneText() or ""
    local spec = GetSpecName()

    GoveePixelStatsDB = {
        name = name,
        class = classFile or "WARRIOR",
        spec = spec,
        level = level,
        ilvl = ilvl,
        hp_max = hpMax,
        crit = crit,
        haste = haste,
        mastery = mastery,
        vers = vers,
        gold = gold,
        zone = zone,
        updated_at = time(),
    }
    return GoveePixelStatsDB
end

frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:RegisterEvent("PLAYER_EQUIPMENT_CHANGED")
frame:RegisterEvent("PLAYER_LEVEL_UP")
frame:RegisterEvent("UNIT_STATS")
frame:RegisterEvent("PLAYER_MONEY")
frame:RegisterEvent("ZONE_CHANGED_NEW_AREA")
frame:RegisterEvent("PLAYER_LOGOUT")

frame:SetScript("OnEvent", function(_, event, unit)
    if event == "UNIT_STATS" and unit ~= "player" then
        return
    end
    UpdateStats()
end)

SLASH_GOVEEPIXEL1 = "/govee"
SlashCmdList["GOVEEPIXEL"] = function()
    local db = UpdateStats()
    print(string.format(
        "|cff00e5ffGoveePixelStats:|r %s (Lv %d, Crit %.1f%%, Haste %.1f%%, %dG, %s) -> jetzt |cffffd166/reload|r fuer Hub-Sync!",
        db.name, db.level, db.crit, db.haste, db.gold, db.zone
    ))
end
