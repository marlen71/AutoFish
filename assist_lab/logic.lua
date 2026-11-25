-- Pure, native-independent geometry. Lua 5.4 / FiveM.
LabLogic = {}
local L = LabLogic
L.defaults = {
    esp = true, aim = false, trigger = false, activation = 'rmb', point = 'head',
    fov = 100, smooth = 12, distance = 150, includePlayers = false,
    triggerRadius = 5, triggerDelay = 150, triggerInterval = 300,
}
local ranges = { fov = {10,600}, smooth = {1,60}, distance = {10,300},
    triggerRadius = {1,20}, triggerDelay = {50,1000}, triggerInterval = {150,2000} }

function L.settings(input, playersAllowed)
    if type(input) ~= 'table' then return nil, 'Settings must be a table' end
    local out = {}
    for key, default in pairs(L.defaults) do
        local value = input[key]
        if value == nil then value = default end
        if type(default) == 'boolean' then
            if type(value) ~= 'boolean' then return nil, 'Invalid '..key end
        elseif type(default) == 'number' then
            value = tonumber(value)
            if not value or value ~= value or value == math.huge or value == -math.huge then return nil, 'Invalid '..key end
            if value < ranges[key][1] or value > ranges[key][2] then return nil, 'Out of range: '..key end
        elseif key == 'activation' and value ~= 'rmb' and value ~= 'auto' then
            return nil, 'Invalid activation'
        elseif key == 'point' and value ~= 'head' and value ~= 'body' then
            return nil, 'Invalid point'
        end
        out[key] = value
    end
    out.includePlayers = out.includePlayers and playersAllowed == true
    return out
end

function L.wrap(angle)
    return (angle + 180) % 360 - 180
end

function L.cameraDelta(camera, target, rotation, dt, smooth)
    local x,y,z = target.x-camera.x, target.y-camera.y, target.z-camera.z
    local horizontal = math.sqrt(x*x+y*y)
    if horizontal < 0.0001 and math.abs(z) < 0.0001 then return 0,0 end
    local heading = math.deg(math.atan(-x,y))
    local pitch = math.deg(math.atan(z,horizontal))
    local alpha = 1 - math.exp(-math.min(math.max(dt,0),.05)*60/math.max(1,smooth))
    return L.wrap(heading-rotation.z)*alpha, L.wrap(pitch-rotation.x)*alpha
end

function L.nearest(items, radius, locked)
    local best
    for _, item in ipairs(items) do
        if item.pixels <= radius then
            if item.id == locked then return item end
            if not best or item.pixels < best.pixels then best = item end
        end
    end
    return best
end
