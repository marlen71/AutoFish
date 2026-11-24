'use strict';
// Browser integration smoke; uses a temporary fixture server and playwright-core.
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
(async () => {
  const executablePath = process.env.RMACRO_CHROME_PATH;
  const port = process.env.RMACRO_TEST_PORT;
  if (!executablePath || !port) throw new Error('RMACRO_CHROME_PATH and RMACRO_TEST_PORT are required');
  const browser = await chromium.launch({executablePath, headless:true, args:['--disable-dev-shm-usage', ...(process.platform === 'linux' ? ['--no-sandbox'] : [])]});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1000}});
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message)); page.on('dialog',d=>d.accept());
    await page.goto('http://127.0.0.1:' + port + '/admin/');
    if (!(await page.title()).includes('Eternal Core')) throw new Error('Eternal Core title missing');
    if (!(await page.locator('#transport-note').innerText()).includes('не шифрует')) throw new Error('HTTP warning missing');
    if (!(await page.locator('.auth-art img').isVisible())) throw new Error('Eternal Core logo missing');
    const screenshots=process.env.RMACRO_UI_SCREENSHOTS;
    if (screenshots) { fs.mkdirSync(screenshots,{recursive:true}); await page.screenshot({path:path.join(screenshots,'03-admin-login.png')}); }
    await page.fill('#admin-login','fixture_admin'); await page.fill('#admin-password','fixture-admin-password');
    await page.click('#login-form button'); await page.waitForSelector('#app-view:not([hidden])'); await page.waitForSelector('.user-row');

    // F5 should restore this tab's admin session, but not the password or a
    // long-lived localStorage token. A fresh tab starts logged out.
    const sessionKey='eternal-core.admin-session.v1';
    const readSession=() => page.evaluate(key => { const raw=sessionStorage.getItem(key); return raw ? JSON.parse(raw) : null; }, sessionKey);
    const saved=await readSession();
    if (!saved || !/^[A-Za-z0-9_-]{40,64}$/.test(saved.token) || saved.name!=='fixture_admin') throw new Error('Tab session was not saved');
    const storage=await page.evaluate(() => ({session:JSON.stringify(sessionStorage), local:JSON.stringify(localStorage)}));
    if (storage.session.includes('fixture-admin-password') || storage.local.includes('fixture-admin-password') || storage.local.includes(saved.token))
      throw new Error('Password or long-lived admin token was stored');
    await page.reload(); await page.waitForSelector('#app-view:not([hidden])'); await page.waitForSelector('.user-row');
    if ((await readSession()).token!==saved.token || (await page.locator('#admin-name').innerText())!=='fixture_admin') throw new Error('F5 did not restore the same admin session');
    const otherTab=await page.context().newPage();
    await otherTab.goto('http://127.0.0.1:' + port + '/admin/'); await otherTab.waitForSelector('#login-view:not([hidden])');
    if (await otherTab.evaluate(key => sessionStorage.getItem(key), sessionKey)) throw new Error('Session leaked to an unrelated new tab');
    await otherTab.close();

    // A network error must not destroy a valid token. Retrying after recovery
    // restores the same session; an actual server-side revocation clears it.
    const userRequests=/\/api\/admin\/users(?:\?.*)?$/;
    const abortUserRequests=route => route.abort();
    await page.route(userRequests, abortUserRequests);
    await page.reload(); await page.locator('#login-message').filter({hasText:'Не удалось проверить сохранённый вход'}).waitFor();
    if (!(await readSession()) || (await readSession()).token!==saved.token) throw new Error('Network failure discarded the session');
    await page.unroute(userRequests, abortUserRequests);
    await page.reload(); await page.waitForSelector('#app-view:not([hidden])'); await page.waitForSelector('.user-row');
    let revoked=await page.request.post('http://127.0.0.1:' + port + '/api/admin/logout',{headers:{Authorization:'Bearer '+saved.token},data:{}});
    if (revoked.status()!==200) throw new Error('Could not revoke test session');
    await page.reload(); await page.locator('#login-message').filter({hasText:'Сессия больше не действительна'}).waitFor();
    if (await readSession()) throw new Error('Revoked session was not cleared');
    await page.fill('#admin-login','fixture_admin'); await page.fill('#admin-password','fixture-admin-password');
    await page.click('#login-form button'); await page.waitForSelector('#app-view:not([hidden])'); await page.waitForSelector('.user-row');

    // Denied sessionStorage is not fatal: login works, with a clear warning.
    const restricted=await page.context().newPage();
    await restricted.addInitScript(() => Object.defineProperty(window,'sessionStorage',{configurable:true,get() { throw new DOMException('denied','SecurityError'); }}));
    await restricted.goto('http://127.0.0.1:' + port + '/admin/');
    await restricted.fill('#admin-login','fixture_admin'); await restricted.fill('#admin-password','fixture-admin-password'); await restricted.click('#login-form button');
    await restricted.waitForSelector('#app-view:not([hidden])');
    await restricted.locator('#app-message').filter({hasText:'Браузер запрещает хранить сессию'}).waitFor();
    await restricted.reload(); await restricted.waitForSelector('#login-view:not([hidden])'); await restricted.close();

    const offlineLogout=await page.context().newPage();
    await offlineLogout.goto('http://127.0.0.1:' + port + '/admin/');
    await offlineLogout.fill('#admin-login','fixture_admin'); await offlineLogout.fill('#admin-password','fixture-admin-password');
    await offlineLogout.click('#login-form button'); await offlineLogout.waitForSelector('#app-view:not([hidden])');
    const offlineToken=(await offlineLogout.evaluate(key => JSON.parse(sessionStorage.getItem(key)), sessionKey)).token;
    const logoutRoute=/\/api\/admin\/logout$/;
    const abortLogout=route => route.abort();
    await offlineLogout.route(logoutRoute,abortLogout); await offlineLogout.click('#logout');
    await offlineLogout.waitForSelector('#login-view:not([hidden])');
    await offlineLogout.locator('#login-message').filter({hasText:'сервер не подтвердил выход'}).waitFor();
    if (await offlineLogout.evaluate(key => sessionStorage.getItem(key),sessionKey)) throw new Error('Offline logout left the local token');
    await offlineLogout.unroute(logoutRoute,abortLogout);
    await page.request.post('http://127.0.0.1:' + port + '/api/admin/logout',{headers:{Authorization:'Bearer '+offlineToken},data:{}});
    await offlineLogout.close();

    await page.fill('#new-user','browser_user'); await page.fill('#user-password','browser-user-password'); await page.click('#create-user button');
    await page.locator('#detail-name').filter({hasText:'browser_user'}).waitFor();
    if (screenshots) await page.screenshot({path:path.join(screenshots,'04-admin-dashboard.png'),fullPage:true});
    await page.fill('#grant-amount','3'); await page.selectOption('#grant-unit','3600'); await page.click('#grant');
    await page.locator('#app-message').filter({hasText:'продлена'}).waitFor();
    if (!(await page.locator('#current-subscriptions').innerText()).includes('RMFish')) throw new Error('Grant did not appear');
    await page.click('#reset-hwid'); await page.locator('#app-message').filter({hasText:'сброшена'}).waitFor();
    await page.click('#toggle-user'); await page.locator('#detail-state').filter({hasText:'Заблокирован'}).waitFor();
    await page.click('#toggle-user'); await page.locator('#detail-state').filter({hasText:'активен'}).waitFor();
    await page.fill('#new-password','browser-new-password'); await page.click('#password-form button');
    await page.locator('#app-message').filter({hasText:'изменён'}).waitFor();
    await page.fill('#game-code','browsergame'); await page.fill('#game-name','Браузерная игра'); await page.click('#create-game button');
    await page.locator('#game-list').filter({hasText:'Браузерная игра'}).waitFor();
    await page.selectOption('#product-game','browsergame');
    await page.fill('#product-code','otherproduct'); await page.fill('#product-name','Другой макрос'); await page.click('#create-product button');
    await page.locator('#product-list').filter({hasText:'Браузерная игра / Другой макрос'}).waitFor();
    await page.selectOption('#edit-product-code','otherproduct'); await page.fill('#edit-product-name','Макрос обновлён');
    await page.selectOption('#edit-product-game','gta5'); await page.selectOption('#edit-product-status','AT YOUR OWN RISK');
    await page.click('#edit-product button');
    await page.locator('#product-list').filter({hasText:'GTA5 · RMRP / Макрос обновлён'}).waitFor();
    await page.locator('#product-list').filter({hasText:'AT YOUR OWN RISK'}).waitFor();
    await page.selectOption('#edit-product-code','otherproduct');
    if (await page.inputValue('#edit-product-status') !== 'AT YOUR OWN RISK') throw new Error('Product status was not saved');
    await page.selectOption('#grant-product','otherproduct'); await page.click('#grant');
    await page.locator('#current-subscriptions').filter({hasText:'Макрос обновлён'}).waitFor();
    await page.fill('#grant-amount','1'); await page.selectOption('#grant-unit','60'); await page.click('#set-subscription');
    await page.locator('#app-message').filter({hasText:'изменён'}).waitFor();
    await page.selectOption('#key-product','otherproduct'); await page.fill('#key-duration','2'); await page.selectOption('#key-unit','3600');
    await page.fill('#key-users','2'); await page.fill('#key-uses','3'); await page.fill('#key-per-user','2');
    await page.click('#create-key button'); await page.waitForSelector('#created-key:not([hidden])');
    const key = await page.inputValue('#key-value');
    if (!/^EC-(?:[0-9A-F]{4}-){7}[0-9A-F]{4}$/.test(key)) throw new Error('Created key missing');
    await page.locator('#key-list').filter({hasText:'Активации: 0 / 3'}).waitFor();
    const device='a'.repeat(64), operation=require('crypto').randomBytes(16).toString('hex');
    let response=await page.request.post('http://127.0.0.1:' + port + '/api/login',{data:{username:'browser_user',password:'browser-new-password',device}});
    if (response.status()!==200) throw new Error('Created user login failed');
    const userToken=(await response.json()).token;
    response=await page.request.post('http://127.0.0.1:' + port + '/api/me/activate-key',{
      headers:{Authorization:'Bearer '+userToken,'X-RMacro-Device':device},data:{key,request_id:operation}});
    if (response.status()!==200) throw new Error('Created key activation failed: '+await response.text());
    await page.click('#refresh'); await page.locator('#key-list').filter({hasText:'Активации: 1 / 3'}).waitFor();
    if (screenshots) await page.locator('#keys').screenshot({path:path.join(screenshots,'05-admin-keys.png')});
    await page.locator('#key-list .key-row button').first().click();
    await page.locator('#key-list').filter({hasText:'Отключён'}).waitFor();
    response=await page.request.post('http://127.0.0.1:' + port + '/api/me/activate-key',{
      headers:{Authorization:'Bearer '+userToken,'X-RMacro-Device':device},data:{key,request_id:require('crypto').randomBytes(16).toString('hex')}});
    if (response.status()!==409 || (await response.json()).code!=='KEY_DISABLED') throw new Error('Disabled key still works');
    await page.fill('#rename-user','browser-renamed'); await page.click('#rename-form button');
    await page.locator('#detail-name').filter({hasText:'browser-renamed'}).waitFor();
    await page.fill('#search','browser-renamed'); await page.waitForTimeout(400);
    if (await page.locator('.user-row').count() !== 1) throw new Error('Search did not filter users');
    await page.setViewportSize({width:390,height:844});
    if (!(await page.locator('#logout').isVisible())) throw new Error('Logout is inaccessible on mobile');
    const finalSession=await readSession();
    const [logoutResponse] = await Promise.all([
      page.waitForResponse(response => response.url().endsWith('/api/admin/logout') && response.request().method()==='POST'),
      page.click('#logout')
    ]);
    if (logoutResponse.status()!==200) throw new Error('Server did not confirm logout');
    await page.waitForSelector('#login-view:not([hidden])');
    if (await readSession()) throw new Error('Logout did not clear the saved session');
    await page.reload(); await page.waitForSelector('#login-view:not([hidden])');
    revoked=await page.request.get('http://127.0.0.1:' + port + '/api/admin/users',{headers:{Authorization:'Bearer '+finalSession.token}});
    if (revoked.status()!==401) throw new Error('Logout did not revoke the server token');
    if (errors.length) throw new Error('Page errors: '+errors.join('; '));
    console.log('PASS: admin session survives F5 and network retry, but revocation/logout clears it; no password or long-lived token stored. Admin CRUD, key activation and mobile logout also passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
