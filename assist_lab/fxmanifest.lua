fx_version 'cerulean'
game 'gta5'
author 'Assist Lab'
description 'Opt-in FiveM test resource: native screen-space diagnostics and controlled aim tests'
version '0.1.0'

ui_page 'web/index.html'
files { 'web/index.html', 'web/style.css', 'web/app.js' }
server_script 'server.lua'
client_scripts { 'logic.lua', 'client.lua' }
