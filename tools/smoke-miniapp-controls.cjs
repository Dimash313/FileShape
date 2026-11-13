// Optional mocked mobile control/TTL regression; requires Playwright + Chromium
// and a localhost Mini App dev server. Not a real Telegram WebView test.
// Optional mobile Chromium UI regression. Requires Playwright, Chromium and
// a local Mini App dev server. Telegram/API responses are mocks, not live tests.
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({executablePath:process.env.CHROMIUM_BIN || '/usr/bin/chromium',headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const context = await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,acceptDownloads:true});
  const page = await context.newPage();
  await page.clock.install({time:new Date()});
  const errors=[]; let statusCalls=0; let creates=0; let downloads=0;
  page.on('pageerror', e=>errors.push(e.message));
  await page.addInitScript(() => {
    window.Telegram={WebApp:{initData:'mock-signed-launch-for-ui-only',ready(){},expand(){},close(){},colorScheme:'dark'}};
  });
  await page.route('https://telegram.org/**', r=>r.fulfill({body:''}));
  await page.route('**/api/v1/session', r=>r.fulfill({json:{ok:true,user_id:12345,max_upload_bytes:20971520}}));
  const jobId='A'.repeat(32), nextId='B'.repeat(32);
  let cancelled=false, retries=0, nextStatuses=0;
  let heldRetry, releaseRetry;
  let serverNow=Math.floor(Date.now()/1000), originalNow=serverNow;
  let createKey, retryKey;
  const snapshot=(id,state)=>({job_id:id,state,created_at:id===jobId?originalNow:serverNow,updated_at:serverNow});
  await page.route('**/api/v1/jobs', async r=>{
    creates++;
    createKey=r.request().headers()['idempotency-key'];
    if(!createKey||!r.request().headers()['x-telegram-init-data']) throw new Error('Missing create auth/idempotency');
    await r.fulfill({status:202,json:snapshot(jobId,'queued')});
  });
  await page.route('**/api/v1/jobs/'+jobId, r=>{statusCalls++;return r.fulfill({json:snapshot(jobId,cancelled?'cancelled':'queued')})});
  await page.route('**/api/v1/jobs/'+jobId+'/cancel', r=>{
    if(!r.request().headers()['x-telegram-init-data']) throw new Error('Missing cancel auth');
    cancelled=true;return r.fulfill({json:snapshot(jobId,'cancelled')});
  });
  await page.route('**/api/v1/jobs/'+jobId+'/retry', async r=>{
    retries++;retryKey=r.request().headers()['idempotency-key'];
    if(!retryKey||retryKey===createKey||!r.request().headers()['x-telegram-init-data']) throw new Error('Missing or reused logical retry key');
    heldRetry=r; await new Promise(resolve=>{releaseRetry=resolve});
  });
  await page.route('**/api/v1/jobs/'+nextId,r=>{nextStatuses++;return r.fulfill({json:snapshot(nextId,nextStatuses===1?'processing':'completed')})});
  await page.route('**/api/v1/jobs/'+nextId+'/result',r=>{
    downloads++;
    if(!r.request().headers()['x-telegram-init-data']) throw new Error('Missing download auth');
    return r.fulfill({headers:{'content-type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'},body:Buffer.from('PK mock result')});
  });
  try {
    await page.goto(process.env.FILESHAPE_SMOKE_URL || 'http://127.0.0.1:5173/');
    await page.locator('input[type=file]').first().setInputFiles({name:'sample.txt',mimeType:'text/plain',buffer:Buffer.from('hello')});
    await page.getByRole('button',{name:'→ DOCX',exact:true}).click();
    await page.getByRole('button',{name:'Выполнить в фоне',exact:true}).click();
    await page.getByText('Ожидает в очереди', {exact:true}).first().waitFor({timeout:15000});
    await page.getByRole('button',{name:'Отменить задание',exact:true}).click();
    await page.getByText('Задание отменено',{exact:true}).waitFor();
    const delta=await page.evaluate(()=>JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k=>k.startsWith('fileshape:jobs:'))))[0].createdAt*1000+3600000-Date.now()-5000);
    if(delta<=0) throw new Error('No live ref for TTL test');
    await page.clock.fastForward(delta); serverNow=Math.floor(await page.evaluate(()=>Date.now())/1000);
    await page.getByRole('button',{name:'Повторить обработку',exact:true}).click();
    for(let i=0;i<100&&!heldRetry;i++) await new Promise(r=>setTimeout(r,20));
    if(!heldRetry) throw new Error('Retry did not start near TTL');
    await page.clock.fastForward(10_000); serverNow=Math.floor(await page.evaluate(()=>Date.now())/1000);
    await heldRetry.fulfill({status:202,json:snapshot(nextId,'queued')}); releaseRetry();
    await page.getByText('Ожидает в очереди',{exact:true}).waitFor();
    await page.clock.fastForward(21_000); serverNow+=21;
    await page.getByText('Обрабатывается',{exact:true}).waitFor();
    await page.clock.fastForward(11_000);
    await page.getByText('Обработка завершена',{exact:true}).waitFor();
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Скачать результат',exact:true}).click();
    await download;
    const storage=JSON.stringify(await page.evaluate(()=>Object.entries(localStorage)));
    if(storage.includes(createKey)||storage.includes(retryKey)||storage.includes('sample.txt')) throw new Error('Upload intent leaked into storage');
    if(creates!==1||retries!==1||downloads!==1||errors.length) throw new Error(JSON.stringify({creates,retries,downloads,errors}));
    console.log(JSON.stringify({creates,retries,downloads,cancelled,distinctKeys:createKey!==retryKey,crossedParentExpiry:true,errors}));

  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
