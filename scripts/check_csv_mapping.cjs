// Generic mapping with invented values only. Does not use the user's browser.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
module.exports=async({browser,out,url})=>{
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(45000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const m=page.getByRole('tabpanel',{name:'Movimientos',exact:true});
 const panel=m.getByText('Preparar desde CSV con otras columnas',{exact:true}).locator('xpath=ancestor::details[1]');
 const ready=async()=>{await page.waitForTimeout(400);await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();};
 const download=async(label,name,scope=panel)=>{
  const pending=page.waitForEvent('download');await scope.getByRole('button',{name:label,exact:true}).click();
  await (await pending).saveAs(path.join(out,name));
 };
 const upload=async(label,name)=>{
  await panel.getByTestId('stFileUploader').filter({hasText:label}).locator('input[type=file]').setInputFiles(path.join(out,name));await ready();
 };
 let result;
 try{
  const start=Date.now();await page.goto(url);
  await panel.locator('summary').first().focus();await panel.locator('summary').first().press('Enter');await ready();
  const initialMs=Date.now()-start;
  await panel.getByText('Práctica con datos ficticios',{exact:true}).click();
  await download('Descargar CSV ficticio','mapping_source.csv');
  await download('Descargar correspondencia ficticia','mapping_template.json');
  await upload('CSV original para correspondencia','mapping_source.csv');
  await panel.getByText(/3 filas ·/).waitFor();
  assert(await panel.getByRole('button',{name:'Usar movimientos del CSV',exact:true}).isDisabled());
  await upload('Correspondencia guardada JSON','mapping_template.json');
  await panel.getByRole('button',{name:'Aplicar correspondencia guardada',exact:true}).click();
  await panel.getByText('3 filas · 0 pendientes · 0 exclusiones documentadas',{exact:true}).waitFor();await ready();
  const axes=[];
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});await ready();
   await panel.getByText('Columnas y valores del libro',{exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,`csv-mapping-${width}.png`)});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
   const a=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});
   axes.push({width,...a});assert.equal(a.violations.length,0);
  }
  await panel.getByRole('button',{name:'Guardar borrador de correspondencia',exact:true}).click();await ready();
  await panel.getByText('Guardar borrador CSV',{exact:true}).click();await ready();
  await download('Descargar paquete de movimientos','mapping_partial.zip');
  assert.equal(await m.getByTestId('stMetric').count(),0);
  const consent=panel.getByRole('checkbox',{name:/Revisé cuenta/});
  assert.equal(await consent.isChecked(),false);await consent.focus();await consent.press('Space');await ready();
  const useStart=Date.now();await panel.getByRole('button',{name:'Usar movimientos del CSV',exact:true}).click();await ready();
  await m.getByText('Recuperado: Libro de movimientos.',{exact:true}).waitFor();
  const useMs=Date.now()-useStart;assert.equal(await consent.isChecked(),false);
  // Collapse/reopen preserves the working source while it renews import consent.
  await consent.focus();await consent.press('Space');await ready();await panel.locator('summary').first().click();await ready();
  await panel.locator('summary').first().click();await ready();assert.equal(await consent.isChecked(),false);
  await m.getByText('Guardar revisión de movimientos',{exact:true}).click();await ready();
  await download('Descargar paquete de movimientos','mapping_applied.zip',m);
  // Full v6 restore; preview before replacement, no surviving confirmations.
  await m.getByText('Abrir paquete de movimientos',{exact:true}).click();
  await m.getByTestId('stFileUploader').filter({hasText:'Paquete de movimientos ZIP'})
   .locator('input[type=file]').setInputFiles(path.join(out,'mapping_applied.zip'));await ready();
  await m.getByText('Libro incluido · Al abrir se requiere una nueva revisión.',{exact:true}).waitFor();
  await m.getByRole('button',{name:'Reemplazar revisión con este paquete',exact:true}).click();await ready();
  assert.equal(await consent.isChecked(),false);
  assert.equal(await page.getByTestId('stException').count(),0);assert.equal(errors.length,0);
  result={fictional_only:true,initial_ms:initialMs,use_ms:useMs,partial_and_applied_zip:true,
   keyboard_panel:true,explicit_import:true,reopened_v6:true,collapse_preserves_source_and_retires_consent:true,
   mobile_is_emulated:true,physical_device:false,axes,page_errors:errors};
 }catch(e){
  await page.screenshot({path:path.join(out,'csv-mapping-failure.png')}).catch(()=>{});
  await page.locator('body').ariaSnapshot().then(s=>fs.writeFileSync(path.join(out,'csv-mapping-failure.txt'),s)).catch(()=>{});throw e;
 }finally{await context.close();}
 fs.writeFileSync(path.join(out,'csv_mapping_verification.json'),JSON.stringify(result,null,2));return result;
};
