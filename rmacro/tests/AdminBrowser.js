'use strict';
// Browser integration smoke; uses a temporary fixture server and playwright-core.
const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');
(async () => {
  const executablePath = process.env.RMACRO_CHROME_PATH;
  const port = process.env.RMACRO_TEST_PORT;
  if (!executablePath || !port) throw new Error('RMACRO_CHROME_PATH and RMACRO_TEST_PORT are required');
  const browser = await chromium.launch({executablePath, headless:true, args:['--disable-dev-shm-usage']});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(10000);
    const errors=[]; page.on('pageerror',e=>errors.push(e.message)); page.on('dialog',d=>d.accept());
    await page.goto('http://127.0.0.1:' + port + '/admin/');
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
    await page.fill('#search','browser_user'); await page.waitForTimeout(400);
    if (await page.locator('.user-row').count() !== 1) throw new Error('Search did not filter users');
    await page.setViewportSize({width:390,height:844});
    if (!(await page.locator('#logout').isVisible())) throw new Error('Logout is inaccessible on mobile');
    await page.click('#logout'); await page.waitForSelector('#login-view:not([hidden])');
    if (errors.length) throw new Error('Page errors: '+errors.join('; '));
    console.log('PASS: admin UI login, user creation, games, macros, per-product grant, HWID reset, block/unblock, password, search, mobile logout.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
