local L = LabLogic
local cfg = L.settings({}, false)
local approved, playersAllowed, enabled, menuOpen = false, false, false, false
local dummies, logs, players = {}, {}, {}
local locked, triggerTarget, triggerSince, nextShot, pulseUntil = nil, nil, 0, 0, 0
local spawning = false

local function log(event, detail)
    if type(detail) == 'table' then detail = json.decode(json.encode(detail)) end
    logs[#logs+1] = { ms = GetGameTimer(), event = event, detail = detail }
    if #logs > 200 then table.remove(logs,1) end
end

local function resetInput()
    locked, triggerTarget, pulseUntil = nil, nil, 0
    triggerSince = 0
end

local function clearDummies()
    for _, ped in ipairs(dummies) do
        if DoesEntityExist(ped) then DeleteEntity(ped) end
    end
    dummies = {}
end

local function sendState()
    SendNUIMessage({ type = 'state', approved = approved, enabled = enabled,
        playersAllowed = playersAllowed, settings = cfg, logs = logs })
end

local function closeMenu()
    menuOpen = false
    SetNuiFocus(false,false)
    SendNUIMessage({type='close'})
    resetInput()
end

local function stop()
    enabled = false
    cfg.aim, cfg.trigger = false, false
    resetInput()
    closeMenu()
    log('stop','Assistance and trigger disabled')
end

RegisterNetEvent('assist_lab:permission', function(ok, allowPlayers)
    approved, playersAllowed = ok == true, allowPlayers == true
    if not approved then
        stop()
        clearDummies()
        print('[Assist Lab] Access denied/revoked. Requires assist_lab_enabled=1 and ACE assist.lab.')
        return
    end
    cfg.includePlayers = cfg.includePlayers and playersAllowed
    menuOpen = true
    resetInput()
    SetNuiFocus(true,true)
    SendNUIMessage({type='open'})
    sendState()
    log('permission','Test access granted; master remains OFF until explicitly enabled')
end)

RegisterNetEvent('assist_lab:policy', function(allowPlayers)
    local changed = playersAllowed ~= (allowPlayers == true)
    playersAllowed = allowPlayers == true
    if not playersAllowed then cfg.includePlayers = false end
    if changed then resetInput() end
end)

RegisterCommand('assistlab', function()
    if menuOpen then closeMenu() else TriggerServerEvent('assist_lab:request') end
end,false)
RegisterKeyMapping('assistlab','Assist Lab: open/close test menu','keyboard','INSERT')
RegisterCommand('assistlab_toggle', function()
    if not approved or menuOpen then return end
    enabled = not enabled
    resetInput()
    log('master',enabled)
end,false)
RegisterKeyMapping('assistlab_toggle','Assist Lab: master on/off','keyboard','F6')
RegisterCommand('assistlab_mode', function()
    if not approved or menuOpen then return end
    cfg.activation = cfg.activation == 'rmb' and 'auto' or 'rmb'
    resetInput()
    log('activation',cfg.activation)
end,false)
RegisterKeyMapping('assistlab_mode','Assist Lab: auto/RMB','keyboard','F7')
RegisterCommand('assistlab_trigger', function()
    if not approved or menuOpen then return end
    cfg.trigger = not cfg.trigger
    resetInput()
    log('trigger',cfg.trigger)
end,false)
RegisterKeyMapping('assistlab_trigger','Assist Lab: trigger toggle','keyboard','F9')
RegisterCommand('assistlab_stop',stop,false)
RegisterKeyMapping('assistlab_stop','Assist Lab: emergency stop','keyboard','F10')

RegisterNUICallback('ready',function(_,cb) sendState(); cb({ok=true}) end)
RegisterNUICallback('close',function(_,cb) closeMenu(); cb({ok=true}) end)
RegisterNUICallback('stop',function(_,cb) stop(); cb({ok=true}) end)
RegisterNUICallback('settings',function(data,cb)
    if not approved or not menuOpen then cb({ok=false,error='Not authorized'}); return end
    local updated, err = L.settings(data,playersAllowed)
    if not updated then cb({ok=false,error=err}); return end
    cfg = updated
    resetInput()
    log('settings',cfg)
    sendState()
    cb({ok=true})
end)
RegisterNUICallback('master',function(_,cb)
    if not approved then cb({ok=false}); return end
    enabled = not enabled
    resetInput()
    log('master',enabled)
    sendState()
    cb({ok=true})
end)
RegisterNUICallback('clear',function(_,cb)
    clearDummies()
    resetInput()
    log('dummies','Removed')
    cb({ok=true})
end)
RegisterNUICallback('spawn',function(_,cb)
    if not approved or not menuOpen or spawning then cb({ok=false,error='Not available'}); return end
    spawning = true
    cb({ok=true})
    CreateThread(function()
        local model = joaat('s_m_y_construct_01')
        RequestModel(model)
        local deadline = GetGameTimer()+5000
        while approved and not HasModelLoaded(model) and GetGameTimer()<deadline do Wait(50) end
        if not approved or not HasModelLoaded(model) then
            spawning = false
            SetModelAsNoLongerNeeded(model)
            log('spawn_error','Model unavailable/access revoked')
            return
        end
        clearDummies()
        local me = PlayerPedId()
        for i=1,3 do
            local pos = GetOffsetFromEntityInWorldCoords(me,(i-2)*4.0,12.0+i*2,0.)
            local found,z = GetGroundZFor_3dCoord(pos.x,pos.y,pos.z+20.,false)
            local ped = CreatePed(4,model,pos.x,pos.y,found and z or pos.z,GetEntityHeading(me)+180.,false,true)
            if ped ~= 0 then
                SetEntityAsMissionEntity(ped,true,true)
                SetEntityInvincible(ped,true)
                SetBlockingOfNonTemporaryEvents(ped,true)
                if i == 3 then TaskWanderInArea(ped,pos.x,pos.y,pos.z,8.,2.,5.) end
                dummies[#dummies+1] = ped
            end
        end
        SetModelAsNoLongerNeeded(model)
        spawning = false
        log('dummies','Created local-only test peds (not networked)')
    end)
end)

local function screenPoint(pos)
    local ok,x,y = GetScreenCoordFromWorldCoord(pos.x,pos.y,pos.z)
    if not ok or x<0 or x>1 or y<0 or y>1 then return nil end
    return {x=x,y=y}
end

local function box(ped)
    local minimum,maximum = GetModelDimensions(GetEntityModel(ped))
    local left,top,right,bottom = 1.,1.,0.,0.
    for _,x in ipairs({minimum.x,maximum.x}) do
        for _,y in ipairs({minimum.y,maximum.y}) do
            for _,z in ipairs({minimum.z,maximum.z}) do
                local pos = GetOffsetFromEntityInWorldCoords(ped,x,y,z)
                local p = screenPoint(pos)
                if not p then return nil end
                left,top,right,bottom = math.min(left,p.x),math.min(top,p.y),math.max(right,p.x),math.max(bottom,p.y)
            end
        end
    end
    return {left=left,top=top,right=right,bottom=bottom}
end

local function drawBox(b,w,h)
    local x,y,dx,dy = (b.left+b.right)/2,(b.top+b.bottom)/2,b.right-b.left,b.bottom-b.top
    DrawRect(x,b.top,dx,2/h,0,230,150,220)
    DrawRect(x,b.bottom,dx,2/h,0,230,150,220)
    DrawRect(b.left,y,2/w,dy,0,230,150,220)
    DrawRect(b.right,y,2/w,dy,0,230,150,220)
end

local function hud(text)
    SetTextFont(0); SetTextScale(.0,.30); SetTextColour(240,240,240,230)
    SetTextOutline(); BeginTextCommandDisplayText('STRING'); AddTextComponentSubstringPlayerName(text)
    EndTextCommandDisplayText(.015,.02)
end

CreateThread(function()
    while true do
        players = GetActivePlayers()
        if menuOpen then sendState() end
        Wait(500)
    end
end)

CreateThread(function()
    while true do
        Wait(0)
        if approved then
            local me = PlayerPedId()
            local active = enabled and not menuOpen and not IsPauseMenuActive() and IsScreenFadedIn()
                and not IsEntityDead(me) and not IsNuiFocused()
            local w,h = GetActiveScreenResolution()
            local candidates = {}
            if active then
                for i=0,47 do
                    local angle=i*math.pi/24
                    DrawRect(.5+math.cos(angle)*cfg.fov/w,.5+math.sin(angle)*cfg.fov/h,1.5/w,1.5/h,180,180,190,150)
                end
                local position = GetEntityCoords(me)
                local pool, seen = {}, {}
                for _,ped in ipairs(dummies) do pool[#pool+1]=ped end
                if cfg.includePlayers and playersAllowed then
                    for _,player in ipairs(players) do pool[#pool+1]=GetPlayerPed(player) end
                end
                for _,ped in ipairs(pool) do
                    if ped ~= me and not seen[ped] and DoesEntityExist(ped) and not IsEntityDead(ped) then
                        seen[ped]=true
                        local pos = GetEntityCoords(ped)
                        if #(pos-position)<=cfg.distance and IsEntityOnScreen(ped) and HasEntityClearLosToEntity(me,ped,17) then
                            local bone = cfg.point == 'head' and 31086 or 24818
                            local aim = GetPedBoneCoords(ped,bone,0.,0.,0.)
                            local p = screenPoint(aim)
                            if p then
                                local pixels = math.sqrt(((p.x-.5)*w)^2+((p.y-.5)*h)^2)
                                local b = box(ped)
                                candidates[#candidates+1] = {id=ped,point=aim,pixels=pixels,screen=p,box=b}
                                if cfg.esp and b then drawBox(b,w,h) end
                            end
                        end
                    end
                end
            end
            local activated = active and IsPedArmed(me,4) and not IsPedReloading(me)
                and (cfg.activation == 'auto' or IsControlPressed(0,25))
            local target = activated and L.nearest(candidates,cfg.fov,locked) or nil
            if target then
                if locked ~= target.id then log('target',target.id) end
                locked=target.id
                if cfg.aim then
                    local heading,pitch = L.cameraDelta(GetGameplayCamCoord(),target.point,GetGameplayCamRot(2),GetFrameTime(),cfg.smooth)
                    SetGameplayCamRelativeHeading(GetGameplayCamRelativeHeading()+heading)
                    SetGameplayCamRelativePitch(math.max(-70,math.min(70,GetGameplayCamRelativePitch()+pitch)),1.)
                end
            else locked=nil end
            local now = GetGameTimer()
            -- Trigger uses the pre-movement screen measurement; never predicts a hit.
            local canTrigger = activated and cfg.trigger and target and target.box
                and target.pixels<=cfg.triggerRadius and (not IsControlPressed(0,24) or now<pulseUntil)
                and target.box.left<=.5 and target.box.right>=.5 and target.box.top<=.5 and target.box.bottom>=.5
            if canTrigger then
                if triggerTarget ~= target.id then triggerTarget=target.id; triggerSince=now end
                if now-triggerSince>=cfg.triggerDelay and now>=nextShot then
                    pulseUntil=now+35
                    nextShot=now+cfg.triggerInterval
                    log('trigger_pulse',{ped=target.id,pixels=target.pixels})
                end
            else triggerTarget=nil; pulseUntil=0 end
            if canTrigger and now<pulseUntil then SetControlNormal(0,24,1.) end
            if not active then resetInput() end
            hud(('ASSIST LAB | %s | %s | AIM %s | TRIGGER %s~n~Insert menu / F6 master / F7 mode / F9 trigger / F10 stop')
                :format(enabled and 'ON' or 'OFF',cfg.activation,cfg.aim and 'ON' or 'OFF',cfg.trigger and 'ON' or 'OFF'))
        else Wait(200) end
    end
end)

AddEventHandler('onResourceStop',function(resource)
    if resource ~= GetCurrentResourceName() then return end
    enabled=false
    resetInput()
    SetNuiFocus(false,false)
    clearDummies()
end)
