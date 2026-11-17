// Native fake-only group review, save/reopen/replace/clear and viewport evidence.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
 execFileSync(process.env.SIG_PYTHON||'python',[path.join(__dirname,'book_consolidation_fixture.py'),out],{env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'}});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(45000);
 const ready=async()=>{await page.waitForTimeout(400);await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();};
 const expand=async label=>{const b=page.getByText(label,{exact:true}).first().locator('xpath=ancestor::*[@data-testid="stExpander"][1]');if(!await b.evaluate(e=>e.tagName==='DETAILS'?e.open:!!e.querySelector('details')?.open))await b.getByText(label,{exact:true}).click();await ready();return b;};
 const download=async(label,name)=>{const event=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();await (await event).saveAs(path.join(out,name));await ready();};
 const group=async()=>{await page.getByRole('tab',{name:'Patrimonio',exact:true}).click();await ready();return expand('Consolidar libros revisados');};
 const open=async filename=>{
   const b=await expand('Reabrir consolidación guardada');await b.locator('input[type=file]').setInputFiles(path.join(out,filename));
   await page.getByText(/Propuesta: 2 cuentas/).waitFor();await ready();
   const marker=page.getByRole('button',{name:'Vaciar consolidación',exact:true});
   const oldKey=await marker.evaluate(e=>e.closest('[class*="st-key-consolidation_"]')?.className);
   await page.getByRole('button',{name:/^(Retomar consolidación|Reemplazar consolidación)$/}).click();
   if(oldKey){const cls=oldKey.split(' ').find(c=>c.startsWith('st-key-consolidation_'));if(cls)await page.locator('.'+cls).waitFor({state:'detached'});}
   await page.getByText('Corte común del grupo: 2026-01-10. Valores nativos convertidos una sola vez.',{exact:true}).waitFor();await ready();
 };
 const label='Confirmé pertenencia, corte común, valuaciones y fuentes de estas cuentas';
 const consent=()=>page.getByRole('checkbox',{name:label,exact:true});
 await page.goto(url);await group();await open('group_fixture.zip');
 assert.equal(await consent().isChecked(),false);assert.equal(await page.getByText('300.11 MXN',{exact:true}).count(),0);
 await consent().press('Space');await page.getByText('300.11 MXN',{exact:true}).waitFor();await ready();
 await download('Descargar resultado consolidado JSON','group_result.json');
 await download('Descargar consolidación CSV','group_result.csv');await download('Descargar consolidación TXT','group_result.txt');
 await page.getByRole('button',{name:'Preparar PDF de patrimonio',exact:true}).click();await ready();await download('Descargar PDF de patrimonio','group_result.pdf');
 await page.getByRole('button',{name:'Preparar paquete de consolidación',exact:true}).click();await ready();await download('Descargar paquete de consolidación','group_review.zip');
 const report=JSON.parse(fs.readFileSync(path.join(out,'group_result.json'),'utf8'));assert.equal(report.nav,'300.11');
 assert(fs.readFileSync(path.join(out,'group_result.txt'),'utf8').includes('300.11 MXN'));
 const axes=[];
 for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(650);
   await page.getByText('Patrimonio completo del grupo · MXN',{exact:true}).evaluate(e=>{e.style.scrollMarginTop='70px';e.scrollIntoView({block:'start'});});
   await page.screenshot({path:path.join(out,`group-${width}.png`)});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
   const a=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});
   axes.push({width,...a});assert.equal(a.violations.length,0);
 }
 fs.writeFileSync(path.join(out,'group_accessibility.json'),JSON.stringify(axes,null,2));
 await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('textbox',{name:'FX documentado del grupo CSV',exact:true}).fill('Fecha,Moneda,Base,Tasa,Fuente\n');await page.keyboard.press('Tab');await ready();
 assert.equal(await consent().isChecked(),false);assert.equal(await page.getByRole('button',{name:'Descargar PDF de patrimonio',exact:true}).count(),0);
 await consent().press('Space');await ready();await page.getByText('Subtotal documentado del grupo: 100.01 MXN',{exact:true}).waitFor();
 const form=await expand('Completar tipo de cambio');
 await form.getByRole('textbox',{name:'Tasa FX del corte',exact:true}).fill('20.01');
 await form.getByRole('textbox',{name:'Fuente FX del grupo',exact:true}).fill('Cierre ficticio del formulario');
 await form.getByRole('button',{name:'Añadir FX al CSV',exact:true}).click();await ready();
 assert((await page.getByRole('textbox',{name:'FX documentado del grupo CSV',exact:true}).inputValue()).includes('20.01,Cierre ficticio del formulario'));
 assert.equal(await consent().isChecked(),false);
 const source=page.getByRole('textbox',{name:'Fuente de pertenencia de cuenta 1',exact:true});await source.fill('Fuente ficticia editada');await source.press('Tab');await ready();
 await page.getByText('Consolidar libros revisados',{exact:true}).click();await source.waitFor({state:'detached'});await ready();await expand('Consolidar libros revisados');await source.waitFor({state:'visible'});
 assert.equal(await source.inputValue(),'Fuente ficticia editada');assert.equal(await consent().isChecked(),false);
 await open('group_review.zip');assert.equal(await consent().isChecked(),false);await consent().press('Space');await page.getByText('300.11 MXN',{exact:true}).waitFor();
 // Rejecting a corrupt archive keeps the current group and its reviewed result.
 const restore=await expand('Reabrir consolidación guardada');await restore.locator('input[type=file]').setInputFiles(path.join(out,'group_invalid.zip'));
 await page.getByText(/El paquete de consolidación no supera/).waitFor();assert.equal(await consent().isChecked(),true);
 await page.getByRole('button',{name:'Vaciar consolidación',exact:true}).click();await ready();
 assert.equal(await consent().count(),0);assert.equal(await page.getByText('300.11 MXN',{exact:true}).count(),0);
 const cuts=page.getByText('Cortes JSON de las cuentas',{exact:true}).locator('xpath=ancestor::*[@data-testid="stFileUploader"][1]');
 await cuts.locator('input[type=file]').setInputFiles([path.join(out,'Cuenta1.cut.json'),path.join(out,'Cuenta2.cut.json')]);await ready();
 for(const i of [1,2]){const input=page.getByRole('textbox',{name:`Fuente de pertenencia de cuenta ${i}`,exact:true});await input.fill('Cuenta ficticia cargada '+i);await input.press('Tab');await ready();}
 await page.getByText('Corte común del grupo: 2026-01-10. Valores nativos convertidos una sola vez.',{exact:true}).waitFor();
 await cuts.getByRole('button',{name:'Remove Cuenta1.cut.json',exact:true}).click();await ready();
 await cuts.getByRole('button',{name:'Remove Cuenta2.cut.json',exact:true}).click();await ready();assert.equal(await consent().count(),0);
 assert.equal(await page.getByTestId('stException').count(),0);
 // A separate browser session restores proposed inputs, never consent.
 const fresh=await browser.newPage({viewport:{width:390,height:1000}});await fresh.goto(url);await fresh.getByRole('tab',{name:'Patrimonio',exact:true}).click();await fresh.getByText('Consolidar libros revisados',{exact:true}).click();await fresh.getByText('Reabrir consolidación guardada',{exact:true}).click();
 const panel=fresh.getByText('Reabrir consolidación guardada',{exact:true}).locator('xpath=ancestor::*[@data-testid="stExpander"][1]');await panel.locator('input[type=file]').setInputFiles(path.join(out,'group_review.zip'));
 await fresh.getByRole('button',{name:'Retomar consolidación',exact:true}).click();const c=fresh.getByRole('checkbox',{name:label,exact:true});await c.waitFor();assert.equal(await c.isChecked(),false);
 const old=JSON.parse(fs.readFileSync(path.join(out,'group_result.json'),'utf8'));assert.equal(old.nav,'300.11');
 const pages=execFileSync(process.env.SIG_PYTHON||'python',['-c','from pypdf import PdfReader;import sys;print(len(PdfReader(sys.argv[1]).pages))',path.join(out,'group_result.pdf')],{encoding:'utf8'}).trim();assert.equal(pages,'2');
 fs.writeFileSync(path.join(out,'group_verification.json'),JSON.stringify({fictional_only:true,nav:'300.11',missing_fx_subtotal:'100.01',input_change_renews_consent:true,replacement_renews_consent:true,new_session_renews_consent:true,corrupt_zip_preserves_review:true,clear_removes_result:true,form_uses_submitted_values:true,collapse_preserves_edits_without_consent:true,native_cuts_upload_and_removal:true,pdf_pages:2,widths:[1440,768,390],wcag_violations:axes.map(a=>a.violations.length)},null,2));
 await fresh.close();await page.close();
};
