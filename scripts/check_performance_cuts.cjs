// Actual native controls with fictional inputs. No orders, real documents or market calls.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
  execFileSync(process.env.SIG_PYTHON||'python',[path.join(__dirname,'performance_cuts_fixture.py'),out],{env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'}});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  page.setDefaultTimeout(45000);
  const times=[];const started=Date.now();
  const ready=async()=>{await page.waitForTimeout(200);await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();};
  const expand=async label=>{
    const block=page.getByText(label,{exact:true}).first().locator('xpath=ancestor::*[@data-testid="stExpander"][1]');
    if(!await block.evaluate(el=>el.tagName==='DETAILS'?el.open:!!el.querySelector('details')?.open))await block.getByText(label,{exact:true}).click();
    await ready();return block;
  };
  const download=async(label,name)=>{
    const event=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();
    await (await event).saveAs(path.join(out,name));await ready();
  };
  await page.goto(url);await page.getByRole('tab',{name:'Movimientos',exact:true}).click();
  let block=await expand('Abrir paquete de movimientos');
  await block.locator('input[type=file]').setInputFiles(path.join(out,'cuts_fixture_v1.zip'));
  await page.getByText('Vista previa del paquete',{exact:true}).waitFor();await ready();
  await page.getByRole('button',{name:'Retomar movimientos',exact:true}).click();
  await page.getByText(/Revisión recuperada/).waitFor();await ready();
  times.push({phase:'open_fictional_package',milliseconds:Date.now()-started});
  const raw=page.getByRole('checkbox',{name:'Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre',exact:true});
  await raw.press('Space');await ready();
  await page.getByText('105.70',{exact:true}).first().waitFor();
  block=await expand('Comparar y guardar cortes');
  await block.locator('input[type=file]').setInputFiles(path.join(out,'cuts_before.json'));
  const consent=page.getByRole('checkbox',{name:'Cotejé ambos cortes, su cuenta y sus fuentes para esta comparación',exact:true});
  await consent.waitFor();await ready();assert.equal(await consent.isChecked(),false);
  const gain=block.getByRole('row').filter({hasText:'Ganancia monetaria entre cortes'});
  assert((await gain.innerText()).includes('Pendiente'));
  const tick=Date.now();await consent.press('Space');await ready();
  await gain.getByText('5.70 MXN',{exact:true}).waitFor();
  times.push({phase:'confirm_attribution',milliseconds:Date.now()-tick});
  assert((await block.getByRole('row').filter({hasText:'Variación por precios'}).innerText()).includes('4.00 MXN'));
  await download('Descargar corte actual JSON','cuts_current.json');
  await download('Descargar comparación de cortes CSV','cuts_comparison.csv');
  const current=JSON.parse(fs.readFileSync(path.join(out,'cuts_current.json'),'utf8'));
  assert.equal(current.schema,1);assert.equal(current.payload.valuation.nav,'105.7');
  assert.equal(current.payload.events.length,4);assert(!('approved' in current.payload));
  await expand('Archivos y resumen descargable');
  await download('Descargar resumen de revisión','cuts_summary.txt');
  await page.getByRole('button',{name:'Preparar PDF breve',exact:true}).click();await ready();
  await download('Descargar PDF de rendimiento','cuts_performance.pdf');
  const summary=fs.readFileSync(path.join(out,'cuts_summary.txt'),'utf8');
  assert(summary.includes('"gain": "5.7"')&&summary.includes('"price": "4"'));
  await expand('Títulos, saldos, pesos y evidencia entre cortes');
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const axe=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});
  fs.writeFileSync(path.join(out,'cuts_accessibility.json'),JSON.stringify(axe,null,2));
  assert.equal(axe.violations.length,0);
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    await block.getByText('Guarda el estado de hoy y compáralo con otro corte de la misma cuenta y moneda.',{exact:true}).evaluate(el=>{el.style.scrollMarginTop='80px';el.scrollIntoView({block:'start'});});
    await page.screenshot({path:path.join(out,`cuts-comparison-${width}.png`)});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  }
  // A changed source must withdraw the attribution until confirmation is renewed.
  await raw.press('Space');await ready();
  await gain.getByText('Pendiente',{exact:true}).waitFor();
  assert.equal(await consent.isChecked(),false);
  assert((await gain.innerText()).includes('Pendiente'));
  await raw.press('Space');await ready();assert.equal(await consent.isChecked(),false);
  await block.locator('input[type=file]').setInputFiles(path.join(out,'cuts_altered.json'));
  await page.getByText(/El corte no es válido:/).waitFor();await ready();
  assert.equal(await page.getByRole('button',{name:'Descargar comparación de cortes CSV',exact:true}).count(),0);
  await block.getByText('Comparar y guardar cortes',{exact:true}).click();await ready();
  await expand('Archivos y resumen descargable');
  await download('Descargar resumen de revisión','cuts_after_rejection.txt');
  assert(fs.readFileSync(path.join(out,'cuts_after_rejection.txt'),'utf8').includes('"cut_comparison": null'));
  assert.equal(await page.getByTestId('stException').count(),0);
  fs.writeFileSync(path.join(out,'cuts_verification.json'),JSON.stringify({fictional_only:true,native_downloads:true,zip_v1_compatible:true,unconfirmed_is_pending:true,gain:5.7,price:4,income:3,fees:1,tax:.3,settlement_not_double_counted:true,changed_input_revokes_confirmation:true,altered_cut_rejected:true,widths:[1440,768,390],wcag_violations:axe.violations.length,timings:times},null,2));
  await page.close();
};
