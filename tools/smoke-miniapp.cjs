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
  const jobId='A'.repeat(32);
  await page.route('**/api/v1/jobs', async r=>{
    if(r.request().method()!=='POST') return r.abort();
    if(!r.request().headers()['x-telegram-init-data']) throw new Error('Missing authenticated create header');
    creates++;
    await r.fulfill({status:202,json:{job_id:jobId,state:'queued',created_at:Math.floor(Date.now()/1000),updated_at:Math.floor(Date.now()/1000)}});
  });
  await page.route('**/api/v1/jobs/'+jobId, async r=>{
    if(!r.request().headers()['x-telegram-init-data']) throw new Error('Missing authenticated status header');
    statusCalls++;
    const state=statusCalls===1?'queued':statusCalls===2?'processing':'completed';
    await r.fulfill({json:{job_id:jobId,state,created_at:Math.floor(Date.now()/1000),updated_at:Math.floor(Date.now()/1000)}});
  });
  await page.route('**/api/v1/jobs/'+jobId+'/result', async r=>{
    downloads++;
    if(!r.request().headers()['x-telegram-init-data']) throw new Error('Missing authenticated download header');
    await r.fulfill({headers:{'content-type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','content-disposition':'attachment; filename="converted.docx"'},body:Buffer.from('PK mock-result-for-ui')});
  });
  try {
    await page.goto(process.env.FILESHAPE_SMOKE_URL || 'http://127.0.0.1:5173/');
    await page.locator('input[type=file]').first().setInputFiles({name:'sample.txt',mimeType:'text/plain',buffer:Buffer.from('hello')});
    await page.getByRole('button',{name:'→ DOCX',exact:true}).click();
    await page.getByRole('button',{name:'Выполнить в фоне',exact:true}).click();
    await page.getByText('Ожидает в очереди', {exact:true}).first().waitFor({timeout:15000});
    if(await page.getByRole('progressbar').count()) throw new Error('Conversion percent must not be fabricated');
    await page.evaluate(()=>{
      window.__hidden=true;
      Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.__hidden});
      Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__hidden?'hidden':'visible'});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    const beforePause=statusCalls;
    await page.clock.fastForward(60_000);
    if(statusCalls!==beforePause) throw new Error('Polling continued while hidden');
    await context.setOffline(true);
    await page.evaluate(()=>{window.__hidden=false;document.dispatchEvent(new Event('visibilitychange'))});
    await page.clock.fastForward(10_000);
    if(statusCalls!==beforePause) throw new Error('Polling continued while offline');
    await context.setOffline(false);
    await page.getByText('Обрабатывается',{exact:true}).waitFor();
    if(await page.getByRole('progressbar').count()) throw new Error('Processing has no measured percentage');
    await page.clock.fastForward(11_000);
    await page.getByText('Обработка завершена',{exact:true}).waitFor();
    const completedCalls=statusCalls;
    await page.clock.fastForward(60_000);
    if(statusCalls!==completedCalls) throw new Error('Polling did not stop after terminal state');
    const download=page.waitForEvent('download');
    await page.getByRole('button',{name:'Скачать результат',exact:true}).click();
    const file=await download;
    if(!file.suggestedFilename().endsWith('.docx')||downloads!==1) throw new Error('Authenticated result download failed');
    const stored=await page.evaluate(()=>Object.entries(localStorage));
    const values=JSON.stringify(stored);
    if(values.includes('sample.txt')||values.includes('mock-signed')||values.includes('hello')) throw new Error('Private data stored with job references');
    await page.screenshot({path:'/tmp/fileshape-v43-completed.png',fullPage:true});
    await page.reload();
    await page.getByText('Обработка завершена',{exact:true}).waitFor();
    if(creates!==1) throw new Error('Reopen resubmitted an upload');
    if(errors.length) throw new Error('Browser JS errors: '+errors.join(';'));
    console.log(JSON.stringify({creates,statusCalls,downloads,hiddenOfflinePause:true,terminalStop:true,reopenWithoutUpload:true,privateStorageClean:true,errors}));

  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1)});
