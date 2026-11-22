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
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
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
    await page.selectOption('#edit-product-game','gta5'); await page.click('#edit-product button');
    await page.locator('#product-list').filter({hasText:'GTA5 · RMRP / Макрос обновлён'}).waitFor();
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
    await page.click('#logout'); await page.waitForSelector('#login-view:not([hidden])');
    if (errors.length) throw new Error('Page errors: '+errors.join('; '));
    console.log('PASS: Eternal Core branding, admin UI login, key creation/redemption/disable, rename, games, subscriptions, HWID, password and mobile logout.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
