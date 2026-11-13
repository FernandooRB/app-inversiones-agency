// Preview/replacement uses fictional archives on the owned loopback server only.
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
module.exports=async({browser,out,url})=>{
  assert(/^http:\/\/127\.0\.0\.1:[0-9]+\/$/.test(url));
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const m=page.getByRole('tabpanel',{name:'Movimientos',exact:true});
  const raw='Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre';
  const flows='Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida';
  const settle=async()=>{await page.waitForTimeout(350);await page.locator('[data-stale="true"]').first().waitFor({state:'detached'});};
  const choose=async name=>{await m.getByTestId('stFileUploader').filter({hasText:'Paquete de movimientos ZIP'}).locator('input[type=file]').setInputFiles(out+'/'+name);await m.getByRole('button',{name:'Remove '+name,exact:true}).waitFor({state:'visible'});await settle();};
  const unchanged=async()=>{assert(await m.getByLabel(raw,{exact:true}).isChecked());assert(await m.getByLabel(flows,{exact:true}).isChecked());await m.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});};
  let report;
  try{
    await page.goto(url);
    await m.getByText('Abrir paquete de movimientos',{exact:true}).click();
    await choose('operations.zip');
    await m.getByText('Corte: 2026-01-10 · Moneda: MXN · 3 archivos CSV',{exact:true}).waitFor({state:'visible'});
    await m.getByRole('button',{name:'Retomar movimientos',exact:true}).click();await settle();
    await m.getByText(raw,{exact:true}).click();await settle();
    await m.getByText(flows,{exact:true}).click();await settle();await unchanged();
    await choose('operations_incomplete.zip');await unchanged();
    const replace=m.getByRole('button',{name:'Reemplazar revisión con este paquete',exact:true});
    await replace.waitFor({state:'visible'});
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:width===390?844:900});
      await m.getByText('Vista previa del paquete',{exact:true}).scrollIntoViewIfNeeded();
      await page.screenshot({path:out+`/replace-preview-${width}.png`});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    }
    await m.getByRole('button',{name:'Remove operations_incomplete.zip',exact:true}).click();await settle();
    assert.equal(await replace.count(),0);await unchanged();
    await choose('invalid.zip');
    await m.getByText(/El paquete de movimientos no supera/).waitFor({state:'visible'});
    assert.equal(await replace.count(),0);await unchanged();
    await choose('operations_incomplete.zip');await unchanged();
    await replace.focus();await replace.press('Enter');await settle();
    await page.getByText('4 pendientes de revisión',{exact:true}).waitFor({state:'visible'});
    assert.equal(await m.getByLabel(raw,{exact:true}).isChecked(),false);
    assert.equal(await m.getByLabel(flows,{exact:true}).isChecked(),false);
    assert.equal(await m.getByTestId('stMetric').count(),0);
    await m.getByText('Valuaciones necesarias para TWR',{exact:true}).click();
    const calendar=m.getByTestId('stExpander').filter({hasText:'Valuaciones necesarias para TWR'});
    await calendar.getByText('2026-01-05',{exact:true}).waitFor({state:'attached'});
    await m.getByRole('button',{name:'Quitar archivo recuperado · Libro de movimientos',exact:true}).click();await settle();
    assert.equal(errors.length,0);assert.equal(await page.getByTestId('stException').count(),0);
    report={fictional_only:true,preview_keeps_inputs_and_consent:true,removing_candidate_cancels:true,
      invalid_candidate_keeps_result:true,explicit_keyboard_replacement:true,confirmations_reset:true,
      incomplete_calendar_preserved:true,old_result_removed:true,widths:[1440,768,390],page_errors:errors};
  }catch(error){
    await page.screenshot({path:out+'/replace-failure.png'}).catch(()=>{});
    await page.locator('body').ariaSnapshot().then(s=>fs.writeFile(out+'/replace-failure.txt',s)).catch(()=>{});
    throw error;
  }finally{await context.close();}
  report.owned_context_closed=true;
  await fs.writeFile(out+'/replace_verification.json',JSON.stringify(report,null,2));
  return report;
};
