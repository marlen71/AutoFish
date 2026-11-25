'use strict';
const menu = document.querySelector('#menu');
const form = document.querySelector('#settings');
const message = document.querySelector('#message');
let dirty = false;
let state = {};
const resource = typeof GetParentResourceName === 'function' ? GetParentResourceName() : null;
async function post(name, data = {}) {
  if (!resource) throw new Error('Откройте ресурс в FiveM, не отдельную HTML-страницу.');
  const response = await fetch(`https://${resource}/${name}`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const result = await response.json();
  if (!result.ok) throw new Error(result.error || 'Действие недоступно');
  return result;
}
function fail(error) { message.textContent = String(error.message || error); }
function fill(settings) {
  for (const [name, value] of Object.entries(settings || {})) {
    const control = form.elements.namedItem(name);
    if (!control) continue;
    if (control.type === 'checkbox') control.checked = value === true;
    else control.value = value;
  }
}
window.addEventListener('message', event => {
  const data = event.data;
  if (!data || typeof data !== 'object') return;
  if (data.type === 'open') { menu.hidden = false; dirty = false; message.textContent = ''; }
  if (data.type === 'close') menu.hidden = true;
  if (data.type === 'state') {
    state = data;
    document.querySelector('#status').textContent = !data.approved ? 'НЕТ ДОСТУПА' : data.enabled ? 'MASTER ON' : 'MASTER OFF';
    if (!dirty) fill(data.settings);
    form.elements.includePlayers.disabled = !data.playersAllowed;
    if (!data.playersAllowed) form.elements.includePlayers.checked = false;
    document.querySelector('#players-policy').textContent = data.playersAllowed
      ? 'Администратор разрешил цели-игроков. Различения команд нет.'
      : 'Игроки отключены серверной политикой. Сейчас только ваши тестовые NPC.';
  }
});
form.addEventListener('input', () => { dirty = true; });
form.addEventListener('change', () => { dirty = true; });
form.addEventListener('submit', async event => {
  event.preventDefault();
  const settings = {};
  for (const control of form.elements) {
    if (!control.name) continue;
    settings[control.name] = control.type === 'checkbox' ? control.checked
      : control.type === 'number' ? Number(control.value) : control.value;
  }
  try { await post('settings', settings); dirty = false; message.textContent = 'Применено. Esc — вернуться в игру.'; }
  catch (error) { fail(error); }
});
for (const name of ['master', 'spawn', 'clear']) {
  document.querySelector(`#${name}`).addEventListener('click', async () => {
    try { await post(name); message.textContent = name === 'spawn' ? 'Запрошено создание NPC. Подождите загрузку модели.' : 'Готово'; }
    catch (error) { fail(error); }
  });
}
async function close() { try { await post('close'); } catch (error) { fail(error); } }
document.querySelector('#close').addEventListener('click', close);
window.addEventListener('keydown', event => {
  if (event.key === 'F10') { event.preventDefault(); post('stop').catch(fail); }
  if (event.key === 'Escape' || event.key === 'Insert') { event.preventDefault(); close(); }
});
document.querySelector('#logs').addEventListener('click', () => {
  document.querySelector('#log-output').value = JSON.stringify({resource, logs: state.logs || []}, null, 2);
});
post('ready').catch(fail);
