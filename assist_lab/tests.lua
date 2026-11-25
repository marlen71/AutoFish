-- Run from repo root: lua assist_lab/tests.lua (or Fengari Lua VM).
dofile('assist_lab/logic.lua')
local L = LabLogic
local count = 0
local function check(value, name)
    assert(value, name)
    count=count+1
end
local cfg = assert(L.settings({},false))
check(not cfg.aim and not cfg.trigger and not cfg.includePlayers,'safe defaults')
check(L.settings({includePlayers=true},false).includePlayers == false,'player policy clamp')
check(L.settings({includePlayers=true},true).includePlayers == true,'explicit player policy')
check(L.settings({distance=500},true) == nil,'range validation')
check(L.settings({smooth=0/0},true) == nil,'NaN rejected')
check(L.settings({smooth=math.huge},true) == nil,'infinity rejected')
check(L.settings({trigger='true'},true) == nil,'boolean validation')
check(L.settings({activation='anything'},true) == nil,'mode validation')
check(L.wrap(359)==-1 and L.wrap(-359)==1,'shortest angular route')
local a,b = L.cameraDelta({x=0,y=0,z=0},{x=0,y=10,z=0},{x=0,z=0},1/60,12)
check(a==0 and b==0,'aligned camera')
a,b = L.cameraDelta({x=0,y=0,z=0},{x=10,y=0,z=0},{x=0,z=0},1/60,12)
check(a<0 and a>-90 and b==0,'bounded yaw step')
local items={{id=1,pixels=80},{id=2,pixels=10}}
check(L.nearest(items,100,1).id==1,'target lock')
check(L.nearest(items,50,1).id==2,'lock must stay in FOV')
check(L.nearest(items,5)==nil,'no out-of-FOV target')
local function simulate(fps)
    local yaw=0
    for _=1,fps do
        local delta=L.cameraDelta({x=0,y=0,z=0},{x=10,y=0,z=0},{x=0,z=yaw},1/fps,12)
        yaw=yaw+delta
    end
    return yaw
end
check(math.abs(simulate(30)-simulate(60))<.00001,'frame-rate-independent smoothing')

-- Smoke-test client callback gates without running native-dependent frame loops.
local events,commands,nui,threads,messages={},{},{},{},{}
function RegisterNetEvent(name,cb) events[name]=cb end
function RegisterCommand(name,cb) commands[name]=cb end
function RegisterKeyMapping() end
function RegisterNUICallback(name,cb) nui[name]=cb end
function CreateThread(cb) threads[#threads+1]=cb end
function AddEventHandler() end
function SetNuiFocus() end
function SendNUIMessage(data) messages[#messages+1]=data end
function GetGameTimer() return 100 end
json={encode=function(v) return v end,decode=function(v) return v end}
dofile('assist_lab/client.lua')
local reply
local function cb(value) reply=value end
nui.settings({aim=true},cb)
check(not reply.ok,'unauthorized settings rejected')
nui.master({},cb)
check(not reply.ok,'unauthorized master rejected')
events['assist_lab:permission'](true,false)
nui.ready({},cb)
check(not messages[#messages].enabled,'grant does not activate master')
nui.settings({aim=true,trigger=true,includePlayers=true},cb)
check(reply.ok,'authorized settings accepted')
nui.ready({},cb)
check(not messages[#messages].settings.includePlayers,'client cannot opt into player targets without policy')
nui.master({},cb)
check(reply.ok and messages[#messages].enabled,'explicit master toggle')
nui.stop({},cb)
nui.ready({},cb)
check(not messages[#messages].enabled and not messages[#messages].settings.trigger,'emergency stop disarms')
print(('Assist Lab: %d checks passed'):format(count))

-- Server gate smoke test: default disabled, ACE required, players opt-in.
local clock, serverEnabled, ace, allowPlayers = 1000,0,false,0
local replies={}
function GetGameTimer() return clock end
function GetConvarInt(name,default)
    if name=='assist_lab_enabled' then return serverEnabled end
    if name=='assist_lab_players' then return allowPlayers end
    return default
end
function IsPlayerAceAllowed() return ace end
function TriggerClientEvent(name,src,ok,playersOk)
    replies[#replies+1]={ok=ok,players=playersOk}
end
source=7
dofile('assist_lab/server.lua')
events['assist_lab:request']()
check(not replies[#replies].ok,'server disabled by default')
clock=clock+1500;serverEnabled=1
events['assist_lab:request']()
check(not replies[#replies].ok,'server requires ACE')
clock=clock+1500;ace=true
events['assist_lab:request']()
check(replies[#replies].ok and not replies[#replies].players,'NPC-only grant')
clock=clock+1500;allowPlayers=1
events['assist_lab:request']()
check(replies[#replies].ok and replies[#replies].players,'explicit player grant')
print(('Assist Lab total: %d checks passed'):format(count))
