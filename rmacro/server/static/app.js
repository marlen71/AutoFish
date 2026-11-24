'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let token = '', adminName = '', selected = null, users = [], games = [], products = [], keys = [], serverTime = 0, searchTimer;
  const sessionKey = 'eternal-core.admin-session.v1';
  const validToken = value => typeof value === 'string' && /^[A-Za-z0-9_-]{40,64}$/.test(value);
  const validName = value => typeof value === 'string' && /^[A-Za-z0-9_.-]{3,32}$/.test(value);
  // A tab-scoped token survives F5, but no password is retained. Storage can
  // be disabled by the browser; in that case login still works for this page.
  function clearSavedSession() { try { sessionStorage.removeItem(sessionKey); } catch (_) {} }
  function saveSession() {
    try { sessionStorage.setItem(sessionKey, JSON.stringify({token, name:adminName})); return true; }
    catch (_) { return false; }
  }
  function savedSession() {
    let raw;
    try { raw = sessionStorage.getItem(sessionKey); } catch (_) { return null; }
    if (!raw) return null;
    try {
      const value = raw.length <= 1024 && JSON.parse(raw);
      if (value && validToken(value.token) && validName(value.name)) return value;
    } catch (_) {}
    clearSavedSession(); return null;
  }
  const labels = {admin_login:'Вход администратора',create_user:'Создан аккаунт',create_product:'Добавлен макрос',update_product:'Изменён макрос',create_game:'Добавлена игра',
    'reset-hwid':'Сброшена привязка устройства',password:'Изменён пароль',profile_password:'Пароль изменён в лоадере',admin_reset_password:'Пароль администратора сброшен',
    rename_user:'Изменён логин',create_key:'Создан ключ',activate_key:'Активирован ключ',disable_key:'Ключ отключён',enable_key:'Ключ включён',
    enable:'Аккаунт разблокирован',disable:'Аккаунт заблокирован',grant:'Добавлено время',set:'Изменён срок подписки',revoke:'Подписка отозвана'};
  const text = (element, value) => { element.textContent = value == null ? '' : String(value); };
  const error = (element, message) => text(element, message || '');
  const uidText = n => String(n).padStart(8, '0');
  const dateText = n => n ? new Date(n * 1000).toLocaleString('ru-RU', {dateStyle:'short',timeStyle:'short'}) : 'Нет подписки';
  const element = (tag, className, value) => { const e = document.createElement(tag); if (className) e.className = className; if (value != null) text(e, value); return e; };
  if (location.protocol === 'https:') text($('transport-note'),'HTTPS включён. Используйте доверенный сертификат и ограничьте доступ к панели.');
  const defaultDeadline = new Date(Date.now() + 7 * 86400000);
  $('key-deadline').value = new Date(defaultDeadline.getTime() - defaultDeadline.getTimezoneOffset() * 60000).toISOString().slice(0,16);
  async function api(path, body, explicitToken) {
    const requestToken = explicitToken === undefined ? token : explicitToken;
    const headers = {}; if (requestToken) headers.Authorization = 'Bearer ' + requestToken;
    const options = {method: body === undefined ? 'GET' : 'POST', headers, cache:'no-store', credentials:'omit', redirect:'error'};
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch (_) { throw new Error('Сервер недоступен. Проверьте соединение.'); }
    let data = {}; try { data = await response.json(); } catch (_) { throw new Error('Некорректный ответ сервера.'); }
    if (!response.ok) {
      if (response.status === 401 && requestToken && token === requestToken && path !== '/api/admin/login') {
        showLogin(); error($('login-message'), data.message || 'Сессия завершена. Войдите заново.');
      }
      const failure = new Error(data.message || 'Ошибка сервера.'); failure.status = response.status; throw failure;
    }
    return data;
  }
  function showLogin() {
    clearSavedSession(); token = ''; adminName = ''; selected = null; users = []; games = []; products = []; keys = [];
    error($('login-message'),'');
    $('login-view').hidden = false; $('app-view').hidden = true; $('admin-password').value = '';
    $('key-value').value = ''; $('created-key').hidden = true; $('new-password').value = ''; $('user-password').value = '';
  }
  function showApp() {
    $('login-view').hidden = true; $('app-view').hidden = false; text($('admin-name'), adminName);
  }
  function renderUsers() {
    const list = $('user-list'); list.replaceChildren(); text($('user-count'), users.length);
    if (!users.length) list.append(element('p','empty','Пользователи не найдены.'));
    for (const u of users) {
      const row = element('button','user-row' + (u.uid === selected ? ' selected' : '')); row.type = 'button';
      row.append(element('span','person-avatar',(u.username[0] || 'E').toUpperCase()));
      const role = u.is_admin ? ' · Администратор' : u.login_conflict ? ' · Конфликт логина' : '';
      const info = element('span','user-info'); info.append(element('strong','',u.username),element('small','','UID ' + uidText(u.uid) + role)); row.append(info);
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
    text($('detail-name'),u.username); text($('detail-uid'),'UID ' + uidText(u.uid) + (u.is_admin ? ' · Администратор' : ''));
    text($('detail-role'),u.is_admin ? 'Администратор: единый пароль для сайта и лоадера; блокировка касается лоадера.' :
      u.login_conflict ? 'Старый пользователь с логином администратора. Переименуйте его, чтобы устранить конфликт; UID и подписки сохранятся.' : 'Обычный аккаунт лоадера.');
    $('rename-form').hidden = !!u.is_admin;
    $('new-password').minLength = u.is_admin ? 12 : 8;
    text($('detail-state'),u.disabled ? 'Заблокирован' : 'Аккаунт активен');
    $('detail-state').className = 'pill' + (u.disabled ? ' inactive' : '');
    text($('detail-device'),u.hwid_bound ? 'Привязано' : 'Не привязано');
    text($('toggle-user'),u.disabled ? 'Разблокировать' : u.is_admin ? 'Блокировать лоадер' : 'Заблокировать');
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
    const keySelect = $('key-product'), previousKey = keySelect.value;
    select.replaceChildren(); editSelect.replaceChildren(); keySelect.replaceChildren();
    for (const p of products) {
      list.append(element('span','product-tag',p.game_name + ' / ' + p.name + ' · ' + p.code + ' · ' + (p.status || 'OUTDATED')));
      const option = element('option','',p.game_name + ' / ' + p.name); option.value = p.code; select.append(option);
      const editOption = element('option','',p.game_name + ' / ' + p.name); editOption.value = p.code; editSelect.append(editOption);
      const keyOption = element('option','',p.game_name + ' / ' + p.name); keyOption.value = p.code; keySelect.append(keyOption);
    }
    if (products.some(p => p.code === previous)) select.value = previous;
    else if (products.some(p => p.code === 'rmfish')) select.value = 'rmfish';
    if (products.some(p => p.code === previousKey)) keySelect.value = previousKey;
    else if (products.some(p => p.code === 'rmfish')) keySelect.value = 'rmfish';
    if (products.some(p => p.code === previousEdit)) editSelect.value = previousEdit;
    syncProductEditor();
  }
  function syncProductEditor() {
    const product = products.find(p => p.code === $('edit-product-code').value);
    $('edit-product-name').value = product ? product.name : '';
    $('edit-product-game').value = product ? product.game_code : '';
    if ($('edit-product-status')) $('edit-product-status').value = product && product.status ? product.status : 'OUTDATED';
  }
  function renderKeys() {
    const list = $('key-list'); list.replaceChildren();
    if (!keys.length) list.append(element('p','empty','Ключей пока нет.'));
    for (const key of keys) {
      const row = element('div','key-row'), info = element('div','key-row-info');
      const state = key.disabled ? 'Отключён' : key.activate_before <= serverTime ? 'Срок активации истёк' :
        key.activation_count >= key.max_activations ? 'Активации исчерпаны' : 'Доступен';
      const duration = key.duration_seconds % 86400 === 0 ? (key.duration_seconds / 86400) + ' дн.' :
        key.duration_seconds % 3600 === 0 ? (key.duration_seconds / 3600) + ' ч.' : (key.duration_seconds / 60) + ' мин.';
      info.append(element('strong','',key.key_hint + '  ·  ' + key.game_name + ' / ' + key.product_name + '  ·  ' + state),
        element('small','','Срок: ' + duration + ' · Активировать до: ' + dateText(key.activate_before) +
          ' · Люди: ' + key.users_count + ' / ' + key.max_users + ' · Активации: ' + key.activation_count + ' / ' + key.max_activations +
          ' · На человека: ' + key.max_per_user));
      const toggle = element('button','button outline',key.disabled ? 'Включить' : 'Отключить'); toggle.type = 'button';
      toggle.addEventListener('click',async () => {
        if (!confirm(key.disabled ? 'Снова разрешить активацию этого ключа?' : 'Отключить ключ? Уже выданные подписки сохранятся.')) return;
        toggle.disabled = true;
        try { await api('/api/admin/keys/' + key.id + '/status',{enabled:!!key.disabled}); await refresh(); text($('app-message'),key.disabled ? 'Ключ включён.' : 'Ключ отключён.'); }
        catch(e) { error($('app-message'),e.message); } finally { toggle.disabled = false; }
      });
      row.append(info,toggle); list.append(row);
    }
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
    const expected = token;
    const data = await api('/api/admin/users?q=' + encodeURIComponent($('search').value));
    if (!expected || token !== expected) return;
    users = data.users; renderUsers(); renderDetail();
  }
  async function refresh() {
    const expected = token; if (!expected) return;
    error($('app-message'),'');
    try {
      const [userData, gameData, productData, keyData, auditData] = await Promise.all([
        api('/api/admin/users?q=' + encodeURIComponent($('search').value)), api('/api/admin/games'), api('/api/admin/products'), api('/api/admin/keys'), api('/api/admin/audit')]);
      if (token !== expected) return;
      users = userData.users; games = gameData.games; products = productData.products; keys = keyData.keys; serverTime = keyData.server_time;
      renderUsers(); renderDetail(); renderProducts(); renderKeys(); renderAudit(auditData.events);
    } catch (e) { if (token === expected) error($('app-message'), e.message); }
  }
  async function change(action, body, success) {
    if (!selected) return;
    try {
      await api('/api/admin/users/' + selected + '/' + action, body); await refresh();
      if (token) text($('app-message'),success);
      else error($('login-message'),success + ' Войдите в панель заново.');
    } catch (e) { error(token ? $('app-message') : $('login-message'),e.message); }
  }
  $('login-form').addEventListener('submit', async event => {
    event.preventDefault(); error($('login-message'),''); const button = event.submitter || event.target.querySelector('button'); button.disabled = true;
    try {
      const name = $('admin-login').value.trim();
      const data = await api('/api/admin/login',{username:name,password:$('admin-password').value});
      if (!validName(name) || !validToken(data.token)) throw new Error('Некорректный ответ сервера при входе.');
      adminName = name; token = data.token; const saved = saveSession();
      $('admin-password').value=''; showApp(); await refresh();
      if (!saved && token === data.token) error($('app-message'),'Браузер запрещает хранить сессию вкладки: после обновления страницы потребуется вход.');
    } catch (e) { error($('login-message'),e.message); } finally { button.disabled=false; }
  });
  $('logout').addEventListener('click',async () => {
    const previous = token;
    // Always forget locally immediately, even if the server is unreachable.
    showLogin();
    if (!previous) return;
    try { await api('/api/admin/logout',{},previous); }
    catch (e) {
      if (!token && e.status !== 401)
        error($('login-message'),'Вход на этом компьютере удалён, но сервер не подтвердил выход. Серверная сессия может действовать до 12 часов.');
    }
  });
  $('refresh').addEventListener('click',refresh);
  $('search').addEventListener('input',() => { clearTimeout(searchTimer); searchTimer=setTimeout(() => loadUsers().catch(e => error($('app-message'),e.message)),250); });
  $('create-user').addEventListener('submit',async event => {
    event.preventDefault(); try { const data=await api('/api/admin/users',{username:$('new-user').value.trim(),password:$('user-password').value}); $('user-password').value=''; $('new-user').value=''; $('search').value=''; selected=data.uid; await refresh(); text($('app-message'),'Пользователь создан. UID ' + uidText(data.uid)); }
    catch(e) { error($('app-message'),e.message); }
  });
  $('create-key').addEventListener('submit',async event => {
    event.preventDefault();
    const amount = Number($('key-duration').value), seconds = amount * Number($('key-unit').value);
    const deadline = Math.floor(new Date($('key-deadline').value).getTime() / 1000);
    const max_users = Number($('key-users').value), max_activations = Number($('key-uses').value), max_per_user = Number($('key-per-user').value);
    if (!Number.isInteger(amount) || amount < 1 || seconds > 10*366*86400 || !Number.isFinite(deadline) ||
        ![max_users,max_activations,max_per_user].every(n => Number.isInteger(n) && n >= 1 && n <= 1000000) || max_per_user > max_activations) {
      error($('app-message'),'Проверьте срок, дату и лимиты. Лимит на человека не может быть больше общего.'); return;
    }
    const button = event.submitter || event.target.querySelector('button'); button.disabled = true;
    try {
      const data = await api('/api/admin/keys',{product:$('key-product').value,seconds,activate_before:deadline,max_users,max_activations,max_per_user});
      $('key-value').value = data.key; $('created-key').hidden = false; text($('copy-message'),'Полный ключ больше не показывается сервером.');
      await refresh(); text($('app-message'),'Ключ создан. Сохраните его сейчас.');
    } catch(e) { error($('app-message'),e.message + ' Если ответ сервера потерян, проверьте список ключей.'); }
    finally { button.disabled = false; }
  });
  $('copy-key').addEventListener('click',async () => {
    const value = $('key-value').value; if (!value) return;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(value);
      else { $('key-value').select(); if (!document.execCommand('copy')) throw new Error('copy'); }
      text($('copy-message'),'Ключ скопирован. Передавайте его только нужным пользователям.');
    } catch (_) { $('key-value').select(); text($('copy-message'),'Выделите и скопируйте ключ вручную.'); }
  });
  $('create-game').addEventListener('submit',async event => {
    event.preventDefault(); try { const code=$('game-code').value.trim(); await api('/api/admin/games',{code,name:$('game-name').value.trim()}); $('game-code').value=''; $('game-name').value=''; await refresh(); $('product-game').value=code; text($('app-message'),'Игра добавлена.'); }
    catch(e) { error($('app-message'),e.message); }
  });
  $('edit-product-code').addEventListener('change',syncProductEditor);
  $('edit-product').addEventListener('submit',async event => {
    event.preventDefault(); try {
      const code=$('edit-product-code').value, body={name:$('edit-product-name').value.trim(),game_code:$('edit-product-game').value};
      if ($('edit-product-status')) body.status=$('edit-product-status').value;
      await api('/api/admin/products/' + encodeURIComponent(code),body); await refresh(); text($('app-message'),'Макрос изменён; подписки сохранены.');
    }
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
  $('password-form').addEventListener('submit',event => {
    event.preventDefault(); const password=$('new-password').value, u=users.find(item => item.uid===selected);
    const prompt = u && u.is_admin ? 'Сменить единый пароль администратора? Сеансы сайта и лоадера будут завершены.' : 'Сменить пароль и завершить текущие сессии?';
    if (confirm(prompt)) { $('new-password').value=''; change('password',{password},'Пароль изменён.'); }
  });
  $('rename-form').addEventListener('submit',event => {
    event.preventDefault(); const username=$('rename-user').value.trim();
    if (confirm('Изменить логин? UID и подписки сохранятся, текущие сеансы завершатся.')) { $('rename-user').value=''; change('rename',{username},'Логин изменён; UID и подписки сохранены.'); }
  });

  async function restoreSession() {
    const saved = savedSession(); if (!saved) return;
    token = saved.token; adminName = saved.name;
    text($('login-message'), 'Проверяем сохранённый вход…');
    try {
      // Existing authenticated endpoint works with old servers too. Do not
      // show the dashboard until the server accepts this saved token.
      const data = await api('/api/admin/users?q=' + encodeURIComponent($('search').value));
      if (token !== saved.token) return;
      users = data.users; showApp(); renderUsers(); renderDetail(); await refresh();
    } catch (e) {
      if (token === saved.token) {
        // A transient network failure is not a logout. Keep sessionStorage so
        // the same tab can retry by refreshing when the server is reachable.
        token = ''; adminName = '';
        error($('login-message'), 'Не удалось проверить сохранённый вход. Проверьте связь и обновите страницу. ' + e.message);
      }
      // A 401 already cleared storage and displayed the server's message.
    }
  }
  restoreSession();
})();
