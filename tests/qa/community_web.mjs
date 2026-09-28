// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
// SPDX-License-Identifier: GPL-2.0-or-later
// Disposable loopback API only; synthetic publications, no production accounts.
// MIXAR_PLAYWRIGHT_PATH=/path/to/playwright/index.mjs node tests/qa/community_web.mjs
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
const { chromium } = await import(process.env.MIXAR_PLAYWRIGHT_PATH || 'playwright');
const base='http://127.0.0.1:8019',out=process.env.QA_SCENARIO_OUT||'/tmp/community-qa';
mkdirSync(out,{recursive:true});
const browser=await chromium.launch({channel:'chrome'});
const created=[];
try{
  const page=await browser.newPage({viewport:{width:1440,height:1100},reducedMotion:'reduce'});
  await page.goto(base+'/api/v1/moodboards/browse');
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const titles=['Desert architecture','Quiet interiors','Forest atmosphere','Shapes in motion','Studio lighting','Material studies','Soft landscapes'];
  for(let i=0;i<titles.length;i++){
    const image=await page.evaluate(i=>{
      const c=document.createElement('canvas');c.width=720;c.height=440;const ctx=c.getContext('2d');
      const pairs=[['#f3cba2','#a46040'],['#ddd4c2','#555443'],['#90aa74','#2d4c32'],['#babbe3','#625786'],['#edcdb7','#645349'],['#c9bfa3','#77795a'],['#cad8c0','#7b947d']];
      const [light,dark]=pairs[i];const g=ctx.createLinearGradient(0,0,720,440);g.addColorStop(0,light);g.addColorStop(1,dark);ctx.fillStyle=g;ctx.fillRect(0,0,720,440);
      ctx.fillStyle=light;ctx.beginPath();ctx.arc(470,210,130,0,Math.PI*2);ctx.fill();ctx.fillStyle=dark;ctx.fillRect(120,150,170,220);ctx.fillStyle='#ffffff28';ctx.fillRect(0,340,720,100);
      return c.toDataURL('image/png').split(',')[1];
    },i);
    const id=randomUUID();created.push(id);
    const response=await page.request.put(base+'/api/v1/moodboards/'+id,{headers:{'x-qa-user':'owner'},data:{
      title:titles[i],description:'A study of color, form and atmosphere. Collect references, explore the composition, and make it your own.',visibility:'public',
      snapshot:{version:1,media:[{node_id:'ref',image_name:'a0',position_x:0,position_y:0,scale:1}],textboxes:[],nodes:[],links:[],frames:[],annotations:[]},assets:[{id:'a0',data:image}]}});
    assert.equal(response.status(),200,await response.text());
  }
  const archive=execFileSync('python3',['-c',"import io,zipfile,base64;b=io.BytesIO();z=zipfile.ZipFile(b,'w');z.writestr('studio_tools/__init__.py',\"bl_info={'name':'Studio Tools'}\\ndef register(): pass\\ndef unregister(): pass\\n\");z.writestr('studio_tools/README.md','Lighting tools made in Mixar.');z.close();print(base64.b64encode(b.getvalue()).decode())"],{encoding:'utf8'}).trim();
  const id=randomUUID();created.push(id);
  let response=await page.request.put(base+'/api/v1/moodboards/addons/'+id,{headers:{'x-qa-user':'owner'},data:{title:'Studio Tools',description:'Set up a clean lighting rig in seconds. Designed for product renders and quick look development.',module:'studio_tools',version:'1.2.0',category:'Rendering',license:'GPL-3.0-or-later',visibility:'public',archive}});
  assert.equal(response.status(),200,await response.text());const addon=(await response.json()).data;
  await page.goto(base+'/api/v1/moodboards/browse');
  await page.waitForFunction(()=>document.querySelectorAll('.card').length===6);
  await page.screenshot({path:out+'/web-desktop.png',fullPage:true});
  await page.getByRole('button',{name:'Next →'}).click();
  await page.waitForFunction(()=>document.getElementById('page').textContent.includes('Page 2'));
  assert.equal(await page.locator('.card').count(),1);
  await page.getByRole('button',{name:'← Previous'}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.card').length===6);
  await page.getByLabel('Search community').fill('Studio');await page.getByRole('button',{name:'Search',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('.card').length===1&&document.getElementById('status').textContent.includes('matching'));
  await page.locator('.card').click();await page.waitForSelector('#canvas svg');
  const original=await page.locator('#canvas svg').getAttribute('viewBox');
  await page.getByLabel('Zoom in',{exact:true}).click();assert.notEqual(await page.locator('#canvas svg').getAttribute('viewBox'),original);
  await page.getByRole('button',{name:'Fit board',exact:true}).click();assert.equal(await page.locator('#canvas svg').getAttribute('viewBox'),original);
  await page.screenshot({path:out+'/web-board.png',fullPage:true});
  await page.goto(base+'/api/v1/moodboards/browse?kind=addon&q=Studio&sort=title');
  await page.waitForFunction(()=>document.querySelectorAll('.card').length===1);
  await page.locator('.card').click();await page.getByRole('link',{name:'Download ZIP ↓'}).waitFor();
  const downloadPromise=page.waitForEvent('download');await page.getByRole('link',{name:'Download ZIP ↓'}).click();
  const download=await downloadPromise;assert.equal(download.suggestedFilename(),'studio_tools-1.2.0.zip');assert.equal(await download.failure(),null);
  await page.screenshot({path:out+'/web-addon.png',fullPage:true});
  for(const width of [390,320]){
    await page.setViewportSize({width,height:900});await page.goto(base+'/api/v1/moodboards/browse');
    await page.waitForFunction(()=>document.querySelectorAll('.card').length===6);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:out+`/web-mobile-${width}.png`,fullPage:true});
    await page.getByRole('button',{name:'Add-ons',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('.card h2')?.textContent==='Studio Tools');
    await page.locator('.card').filter({has:page.getByRole('heading',{name:'Studio Tools',exact:true})}).click();await page.getByRole('link',{name:'Download ZIP ↓'}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:out+`/web-addon-mobile-${width}.png`,fullPage:true});
  }
  await page.goto(base+'/api/v1/moodboards/browse?q=NoSuchCreativeTool');
  await page.getByRole('heading',{name:'No matches yet'}).waitFor();
  await page.screenshot({path:out+'/web-empty.png',fullPage:true});
  await page.route('**/api/v1/moodboards/explore?**',route=>route.abort());
  await page.getByRole('button',{name:'Clear search'}).click();
  await page.getByRole('heading',{name:'Couldn’t load the community'}).waitFor();
  await page.screenshot({path:out+'/web-error.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({ok:true,widths:[1440,390,320],pagination:true,search:true,zoom:true,download:true,empty:true,error:true,paid_requests:0,screenshots:out}));
}finally{
  const context=browser.contexts()[0];
  if(context)for(const id of created)await context.request.delete(base+'/api/v1/moodboards/'+id,{headers:{'x-qa-user':'owner'}});
  await browser.close();
}
