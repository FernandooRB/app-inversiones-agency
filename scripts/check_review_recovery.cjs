// Fictional native recovery UI; local encryption is exercised in separate processes.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
 execFileSync(process.env.SIG_PYTHON||'python',[path.join(__dirname,'review_recovery_fixture.py'),out],
  {env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'},timeout:180000});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();page.setDefaultTimeout(45000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const m=page.getByRole('tabpanel',{name:'Movimientos',exact:true});
 const ready=async()=>{await page.waitForTimeout(400);await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();};
 const upload=async name=>{
  await m.getByTestId('stFileUploader').filter({hasText:'Paquete de movimientos ZIP'})
   .locator('input[type=file]').setInputFiles(path.join(out,name));
  await m.getByRole('button',{name:'Remove '+name,exact:true}).waitFor();await ready();
 };
 let record;
 try{
  await page.goto(url);await m.getByText('Abrir paquete de movimientos',{exact:true}).click();await ready();
  const guide=m.getByText('Copias personales en tu computadora',{exact:true}).locator('xpath=ancestor::summary[1]');
  await guide.focus();await guide.press('Enter');await ready();
  const download=page.waitForEvent('download');
  await m.getByRole('button',{name:'Descargar guía de copias personales',exact:true}).click();
  await (await download).saveAs(path.join(out,'recovery_guide.txt'));
  assert(fs.readFileSync(path.join(out,'recovery_guide.txt'),'utf8').includes('No necesitas extraer'));
  await upload('recovery_restored.zip');
  await m.getByText('Libro incluido · Al abrir se requiere una nueva revisión.',{exact:true}).waitFor();
  assert.equal(await m.getByTestId('stMetric').count(),0);
  const axes=[];
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});await ready();
   await m.getByText('Vista previa del paquete',{exact:true}).scrollIntoViewIfNeeded();
   await page.screenshot({path:path.join(out,`recovery-preview-${width}.png`)});
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
   await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
   const result=await page.evaluate(async()=>{const a=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:a.violations,incomplete:a.incomplete,passes:a.passes.length};});
   axes.push({width,...result});assert.equal(result.violations.length,0);
  }
  await m.getByRole('button',{name:'Retomar movimientos',exact:true}).press('Enter');await ready();
  await m.getByText('Revisión recuperada. Se recalculan las vistas; confirma otra vez las fuentes y los flujos.',{exact:true}).waitFor();
  await m.getByText('Revisión de flujos y resultado',{exact:true}).click();await ready();
  const flows=m.getByRole('checkbox',{name:'Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida',exact:true});
  assert.equal(await flows.isChecked(),false);assert.equal(await m.getByTestId('stMetric').count(),0);
  await upload('recovery_invalid.zip');
  await m.getByText(/El paquete de movimientos no supera/).waitFor();
  assert.equal(await m.getByRole('button',{name:'Reemplazar revisión con este paquete',exact:true}).count(),0);
  if(!await flows.count()){
   await m.getByText('Revisión de flujos y resultado',{exact:true}).click();await ready();
  }
  assert.equal(await flows.isChecked(),false);
  await upload('recovery_draft.zip');
  await m.getByText('Borrador sin libro · Al abrir se requiere una nueva revisión.',{exact:true}).waitFor();
  await m.getByText(/Debes volver a adjuntar los originales PDF\/XML/).waitFor();
  assert.equal(await m.getByRole('button',{name:'Reemplazar revisión con este paquete',exact:true}).count(),1);
  assert.equal(await page.getByTestId('stException').count(),0);assert.equal(errors.length,0);
  fs.writeFileSync(path.join(out,'recovery_accessibility.json'),JSON.stringify(axes,null,2));
  record={fictional_only:true,native_restored_zip:true,keyboard_preview_and_open:true,
   guide_download:true,preview_never_confirms:true,consent_renewed:true,
   bad_zip_keeps_current_inputs:true,draft_without_book_explained:true,originals_required:true,
   widths:[1440,768,390],wcag_violations:axes.map(a=>a.violations.length),page_errors:errors};
 }catch(error){
  await page.screenshot({path:path.join(out,'recovery-failure.png')}).catch(()=>{});
  await page.locator('body').ariaSnapshot().then(s=>fs.writeFileSync(path.join(out,'recovery-failure.txt'),s)).catch(()=>{});
  throw error;
 }finally{await context.close();}
 fs.writeFileSync(path.join(out,'recovery_verification.json'),JSON.stringify(record,null,2));
 return record;
};
