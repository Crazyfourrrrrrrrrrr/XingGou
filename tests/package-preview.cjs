/* Render the unpacked source release, with no dependency on the authoring tree. */
const {chromium}=require('playwright');const fs=require('node:fs');
let browser;
(async()=>{
 browser=await chromium.launch({channel:'msedge',headless:true,chromiumSandbox:true,ignoreDefaultArgs:['--unsafely-disable-devtools-self-xss-warnings'],args:['--enable-webgl','--ignore-gpu-blocklist']});
 const page=await browser.newPage({viewport:{width:1540,height:980}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 await page.goto(process.env.STARSCENE_URL||'http://127.0.0.1:8788');await page.locator('#loading-overlay').waitFor({state:'hidden'});await page.locator('#load-status').filter({hasText:'模型已就绪'}).waitFor({timeout:120000});
 await page.waitForFunction(()=>document.querySelectorAll('.asset-card img').length>=16,{},{timeout:60000});
 await page.screenshot({path:process.argv[2]||'preview.png'});console.log(JSON.stringify({packagedEditor:'passed',models:await page.locator('#library-count').innerText(),objects:await page.locator('#object-stats').innerText(),thumbnailCount:await page.locator('.asset-card img').count(),errors}));
 await browser.close();if(errors.length)process.exitCode=1;
})().catch(async e=>{console.error(e);await browser?.close();process.exitCode=1});
