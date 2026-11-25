-- Install only on your own isolated test server. No anti-cheat bypass.
local grants = {}
local attempts = {}

local function allowed(source)
    return GetConvarInt('assist_lab_enabled', 0) == 1
        and IsPlayerAceAllowed(source, 'assist.lab')
end

RegisterNetEvent('assist_lab:request', function()
    local src = source
    local now = GetGameTimer()
    if attempts[src] and now - attempts[src] < 1000 then return end
    attempts[src] = now
    local ok = allowed(src)
    grants[src] = ok and true or nil
    TriggerClientEvent('assist_lab:permission', src, ok,
        ok and GetConvarInt('assist_lab_players', 0) == 1)
    print(('[Assist Lab] access %s: player %s'):format(ok and 'granted' or 'denied', src))
end)

AddEventHandler('playerDropped', function()
    grants[source] = nil
    attempts[source] = nil
end)

CreateThread(function()
    while true do
        Wait(2000)
        for src in pairs(grants) do
            if not allowed(src) then
                TriggerClientEvent('assist_lab:permission', src, false, false)
                grants[src] = nil
            else
                TriggerClientEvent('assist_lab:policy', src, GetConvarInt('assist_lab_players', 0) == 1)
            end
        end
    end
end)
