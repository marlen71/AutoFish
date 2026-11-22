'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let token = '', adminName = '', selected = null, users = [], games = [], products = [], searchTimer;
  const labels = {admin_login:'Вход администратора',create_user:'Создан аккаунт',create_product:'Добавлен макрос',update_product:'Изменён макрос',create_game:'Добавлена игра',
    'reset-hwid':'Сброшена привязка устройства',password:'Изменён пароль',enable:'Аккаунт разблокирован',
    disable:'Аккаунт заблокирован',grant:'Добавлено время',set:'Изменён срок подписки',revoke:'Подписка отозвана'};
  const text = (element, value) => { element.textContent = value == null ? '' : String(value); };
  const error = (element, message) => text(element, message || '');
  const uidText = n => String(n).padStart(8, '0');
  const dateText = n => n ? new Date(n * 1000).toLocaleString('ru-RU', {dateStyle:'short',timeStyle:'short'}) : 'Нет подписки';
  const element = (tag, className, value) => { const e = document.createElement(tag); if (className) e.className = className; if (value != null) text(e, value); return e; };
  async function api(path, body) {
    const headers = {}; if (token) headers.Authorization = 'Bearer ' + token;
    const options = {method: body === undefined ? 'GET' : 'POST', headers, cache:'no-store', credentials:'omit', redirect:'error'};
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch (_) { throw new Error('Сервер недоступен. Проверьте соединение.'); }
    let data = {}; try { data = await response.json(); } catch (_) { throw new Error('Некорректный ответ сервера.'); }
    if (!response.ok) {
      if (response.status === 401 && token && path !== '/api/admin/login') { showLogin(); }
      throw new Error(data.message || 'Ошибка сервера.');
    }
    return data;
  }
  function showLogin() {
    token = ''; selected = null; users = []; games = []; products = [];
    $('login-view').hidden = false; $('app-view').hidden = true; $('admin-password').value = '';
  }
  function showApp() {
    $('login-view').hidden = true; $('app-view').hidden = false; text($('admin-name'), adminName);
  }
  function renderUsers() {
    const list = $('user-list'); list.replaceChildren(); text($('user-count'), users.length);
    if (!users.length) list.append(element('p','empty','Пользователи не найдены.'));
    for (const u of users) {
      const row = element('button','user-row' + (u.uid === selected ? ' selected' : '')); row.type = 'button';
      row.append(element('span','person-avatar',(u.username[0] || 'R').toUpperCase()));
      const info = element('span','user-info'); info.append(element('strong','',u.username),element('small','','UID ' + uidText(u.uid))); row.append(info);
      const active = u.products.filter(p => p.active).length;
      const status = u.disabled ? 'Заблокирован' : active ? 'Активных: ' + active : 'Нет подписки';
      row.append(element('span','pill' + (active && !u.disabled ? '' : ' inactive'),status));
      row.addEventListener('click', () => { selected = u.uid; renderUsers(); renderDetail(); }); list.append(row);
    }
  }
  function renderDetail() {
    const u = users.find(item => item.uid === selected);
    $('detail').hidden = !u; $('detail-empty').hidden = !!u;
    if (!u) return;
    text($('detail-name'),u.username); text($('detail-uid'),'UID ' + uidText(u.uid));
    text($('detail-state'),u.disabled ? 'Заблокирован' : 'Аккаунт активен');
    $('detail-state').className = 'pill' + (u.disabled ? ' inactive' : '');
    text($('detail-device'),u.hwid_bound ? 'Привязано' : 'Не привязано');
    text($('toggle-user'),u.disabled ? 'Разблокировать' : 'Заблокировать');
    const container = $('current-subscriptions'); container.replaceChildren();
    for (const p of u.products.filter(p => p.expires_at)) {
      const row = element('div','subscription'); row.append(element('span','',(p.game_name ? p.game_name + ' · ' : '') + p.name),element('strong','',p.active ? 'До ' + dateText(p.expires_at) : 'Истекла ' + dateText(p.expires_at))); container.append(row);
    }
  }
  function renderProducts() {
    const gameList = $('game-list'), gameSelect = $('product-game'), editGame = $('edit-product-game'), previousGame = gameSelect.value;
    gameList.replaceChildren(); gameSelect.replaceChildren(); editGame.replaceChildren();
    for (const game of games) {
      gameList.append(element('span','product-tag',game.name + ' · ' + game.code));
      const option = element('option','',game.name); option.value = game.code; gameSelect.append(option);
      const editOption = element('option','',game.name); editOption.value = game.code; editGame.append(editOption);
    }
    if (games.some(game => game.code === previousGame)) gameSelect.value = previousGame;
    const list = $('product-list'); list.replaceChildren();
    const select = $('grant-product'), previous = select.value, editSelect = $('edit-product-code'), previousEdit = editSelect.value;
    select.replaceChildren(); editSelect.replaceChildren();
    for (const p of products) {
      list.append(element('span','product-tag',p.game_name + ' / ' + p.name + ' · ' + p.code));
      const option = element('option','',p.game_name + ' / ' + p.name); option.value = p.code; select.append(option);
      const editOption = element('option','',p.game_name + ' / ' + p.name); editOption.value = p.code; editSelect.append(editOption);
    }
    if (products.some(p => p.code === previous)) select.value = previous;
    else if (products.some(p => p.code === 'rmfish')) select.value = 'rmfish';
    if (products.some(p => p.code === previousEdit)) editSelect.value = previousEdit;
    syncProductEditor();
  }
  function syncProductEditor() {
    const product = products.find(p => p.code === $('edit-product-code').value);
    $('edit-product-name').value = product ? product.name : '';
    $('edit-product-game').value = product ? product.game_code : '';
  }
  function renderAudit(events) {
    const list = $('audit-list'); list.replaceChildren();
    if (!events.length) list.append(element('p','empty','Действий пока нет.'));
    for (const event of events.slice(0, 15)) {
      const row = element('div','audit-row'); row.append(element('time','',dateText(event.at)),element('strong','',labels[event.action] || event.action),
        element('span','',event.actor + (event.uid ? ' · UID ' + uidText(event.uid) : '') + (event.details ? ' · ' + event.details : ''))); list.append(row);
    }
  }
  async function loadUsers() {
    const data = await api('/api/admin/users?q=' + encodeURIComponent($('search').value)); users = data.users; renderUsers(); renderDetail();
  }
  async function refresh() {
    error($('app-message'),'');
    try {
      const [userData, gameData, productData, auditData] = await Promise.all([
        api('/api/admin/users?q=' + encodeURIComponent($('search').value)), api('/api/admin/games'), api('/api/admin/products'), api('/api/admin/audit')]);
      users = userData.users; games = gameData.games; products = productData.products; renderUsers(); renderDetail(); renderProducts(); renderAudit(auditData.events);
    } catch (e) { error($('app-message'), e.message); }
  }
  async function change(action, body, success) {
    if (!selected) return;
    try { await api('/api/admin/users/' + selected + '/' + action, body); await refresh(); text($('app-message'),success); }
    catch (e) { error($('app-message'),e.message); }
  }
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault(); error($('login-message'),''); const button = event.submitter || event.target.querySelector('button'); button.disabled = true;
    try { adminName = $('admin-login').value.trim(); const data = await api('/api/admin/login',{username:adminName,password:$('admin-password').value}); token=data.token; $('admin-password').value=''; showApp(); await refresh(); }
    catch (e) { error($('login-message'),e.message); } finally { button.disabled=false; }
  });
  $('logout').addEventListener('click',async () => { try { await api('/api/admin/logout',{}); } catch (_) {} showLogin(); });
  $('refresh').addEventListener('click',refresh);
  $('search').addEventListener('input',() => { clearTimeout(searchTimer); searchTimer=setTimeout(() => loadUsers().catch(e => error($('app-message'),e.message)),250); });
  $('create-user').addEventListener('submit',async event => {
    event.preventDefault(); try { const data=await api('/api/admin/users',{username:$('new-user').value.trim(),password:$('user-password').value}); $('user-password').value=''; $('new-user').value=''; $('search').value=''; selected=data.uid; await refresh(); text($('app-message'),'Пользователь создан. UID ' + uidText(data.uid)); }
    catch(e) { error($('app-message'),e.message); }
  });
  $('create-game').addEventListener('submit',async event => {
    event.preventDefault(); try { const code=$('game-code').value.trim(); await api('/api/admin/games',{code,name:$('game-name').value.trim()}); $('game-code').value=''; $('game-name').value=''; await refresh(); $('product-game').value=code; text($('app-message'),'Игра добавлена.'); }
    catch(e) { error($('app-message'),e.message); }
  });
  $('edit-product-code').addEventListener('change',syncProductEditor);
  $('edit-product').addEventListener('submit',async event => {
    event.preventDefault(); try { const code=$('edit-product-code').value; await api('/api/admin/products/' + encodeURIComponent(code),{name:$('edit-product-name').value.trim(),game_code:$('edit-product-game').value}); await refresh(); text($('app-message'),'Макрос изменён; подписки сохранены.'); }
    catch(e) { error($('app-message'),e.message); }
  });
  $('create-product').addEventListener('submit',async event => {
    event.preventDefault(); try { await api('/api/admin/products',{code:$('product-code').value.trim(),name:$('product-name').value.trim(),game_code:$('product-game').value}); $('product-code').value=''; $('product-name').value=''; await refresh(); text($('app-message'),'Макрос добавлен.'); }
    catch(e) { error($('app-message'),e.message); }
  });
  function duration() {
    const amount=Number($('grant-amount').value), unit=Number($('grant-unit').value), seconds=amount*unit;
    if (!Number.isInteger(amount) || amount < 1 || seconds > 10*366*86400) { error($('app-message'),'Укажите целое положительное количество времени, не более 10 лет.'); return null; }
    return seconds;
  }
  $('grant').addEventListener('click',() => {
    const seconds=duration(); if (seconds !== null) change('grant',{product:$('grant-product').value,seconds},'Подписка продлена.');
  });
  $('set-subscription').addEventListener('click',() => {
    const seconds=duration();
    if (seconds !== null && confirm('Задать указанный срок с текущего момента? Прежний остаток будет заменён.'))
      change('set',{product:$('grant-product').value,seconds},'Срок подписки изменён.');
  });
  $('reset-hwid').addEventListener('click',() => { if (confirm('Сбросить HWID? Все текущие сессии пользователя будут завершены.')) change('reset-hwid',{},'Привязка сброшена; следующий вход привяжет новое устройство.'); });
  $('toggle-user').addEventListener('click',() => { const u=users.find(item => item.uid===selected); if (u && confirm(u.disabled ? 'Разблокировать пользователя?' : 'Заблокировать пользователя и завершить его сессии?')) change('status',{enabled:u.disabled},u.disabled ? 'Аккаунт разблокирован.' : 'Аккаунт заблокирован.'); });
  $('revoke').addEventListener('click',() => { if (confirm('Отозвать подписку на выбранный продукт? Оставшееся время будет потеряно.')) change('revoke',{product:$('grant-product').value},'Подписка отозвана.'); });
  $('password-form').addEventListener('submit',event => { event.preventDefault(); const password=$('new-password').value; if (confirm('Сменить пароль и завершить текущие сессии?')) { $('new-password').value=''; change('password',{password},'Пароль изменён.'); } });
})();
