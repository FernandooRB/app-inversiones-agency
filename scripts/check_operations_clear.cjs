// Clear fictional movement reviews on the owned loopback fixture only.
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
module.exports=async({browser,out,url})=>{
  assert(/^http:\/\/127\.0\.0\.1:[0-9]+\/$/.test(url));
  const context=await browser.newContext({viewport:{width:1440,height:900}});
  const page=await context.newPage(),other=await context.newPage();
  const errors=[];for(const p of [page,other])p.on('pageerror',e=>errors.push(e.message));
  const panel=p=>p.getByRole('tabpanel',{name:'Movimientos',exact:true});
  const flow='Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida';
  const raw='Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre';
  const settle=async p=>{await p.waitForTimeout(350);await p.locator('[data-stale="true"]').first().waitFor({state:'detached'});};
  const choose=async(p,label,file)=>{await panel(p).getByTestId('stFileUploader').filter({hasText:label}).locator('input[type=file]').setInputFiles(out+'/'+file);await panel(p).getByRole('button',{name:'Remove '+file,exact:true}).waitFor({state:'visible'});await settle(p);};
  const open=async p=>{await p.goto(url);await panel(p).getByText('Abrir paquete de movimientos',{exact:true}).click();await choose(p,'Paquete de movimientos ZIP','operations.zip');await panel(p).getByRole('button',{name:'Retomar movimientos',exact:true}).click();await settle(p);};
  const confirm=async p=>{await panel(p).getByText(raw,{exact:true}).click();await settle(p);await panel(p).getByText(flow,{exact:true}).click();await settle(p);await panel(p).getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});};
  const empty=async p=>{await panel(p).getByText('Revisión de movimientos vacía. Carga un libro o abre un ZIP para empezar.',{exact:true}).waitFor({state:'visible'});assert.equal(await panel(p).getByTestId('stMetric').count(),0);assert.equal(await panel(p).getByTestId('stDateInput').count(),0);assert.equal(await panel(p).getByRole('button',{name:/^Remove /}).count(),0);assert.equal(await panel(p).getByText('Vista previa del paquete',{exact:true}).count(),0);assert.equal(await p.getByRole('button',{name:'Guardar para continuar después',exact:true}).count(),0);assert.equal(await panel(p).getByText(/Recuperado:/).count(),0);assert.equal(await panel(p).getByTestId('stAlert').filter({hasText:'Revisa '}).count(),0);};
  const clear=async p=>{const button=panel(p).getByRole('button',{name:'Vaciar movimientos y empezar',exact:true});if(!await button.isVisible())await panel(p).getByText('Nueva revisión de movimientos',{exact:true}).click();await button.click();await settle(p);await empty(p);};
  let report;
  try{
    await fs.writeFile(out+'/bad_ledger.csv','not a movement ledger');
    await open(page);await confirm(page);await open(other);await confirm(other);
    await panel(page).getByText('Nueva revisión de movimientos',{exact:true}).click();await settle(page);
    assert(await panel(page).getByLabel(flow,{exact:true}).isChecked());
    for(const width of [1440,768,390]){await page.setViewportSize({width,height:width===390?844:900});await panel(page).getByRole('button',{name:'Vaciar movimientos y empezar',exact:true}).evaluate(el=>el.scrollIntoView({block:'center'}));await page.screenshot({path:out+`/clear-review-${width}.png`});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);}
    const action=panel(page).getByRole('button',{name:'Vaciar movimientos y empezar',exact:true});await action.focus();await action.press('Enter');await settle(page);await empty(page);
    assert(await panel(other).getByLabel(flow,{exact:true}).isChecked());await panel(other).getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
    await page.getByRole('tab',{name:'Originales GBM',exact:true}).click();await page.getByRole('tab',{name:'Movimientos',exact:true}).click();await settle(page);await empty(page);
    await page.evaluate(()=>document.querySelector('[data-testid="stMain"]').scrollTop=0);await page.screenshot({path:out+'/clear-empty-390.png'});
    await panel(page).getByText('Abrir paquete de movimientos',{exact:true}).click();await choose(page,'Paquete de movimientos ZIP','operations.zip');await panel(page).getByRole('button',{name:'Retomar movimientos',exact:true}).click();await settle(page);
    assert.equal(await panel(page).getByLabel(flow,{exact:true}).isChecked(),false);assert.equal(await panel(page).getByLabel(raw,{exact:true}).isChecked(),false);assert.equal(await panel(page).getByTestId('stMetric').count(),0);
    await clear(page);
    await choose(page,'Libro normalizado de movimientos','ledger.csv');const cutoff=panel(page).getByTestId('stDateInput').locator('input');await cutoff.fill('2026-01-10');await cutoff.press('Enter');await choose(page,'Valuaciones históricas verificadas:','nav.csv');await confirm(page);await clear(page);
    await choose(page,'Libro normalizado de movimientos','bad_ledger.csv');await panel(page).getByText('Revisa Libro de movimientos.',{exact:true}).waitFor({state:'visible'});await clear(page);
    await panel(page).getByText('Abrir paquete de movimientos',{exact:true}).click();await choose(page,'Paquete de movimientos ZIP','invalid.zip');await panel(page).getByText(/El paquete de movimientos no supera/).waitFor({state:'visible'});await clear(page);await clear(other);
    assert.equal(errors.length,0);assert.equal(await page.getByTestId('stException').count(),0);
    report={fictional_only:true,opening_disclosure_preserves_review:true,explicit_keyboard_clear:true,recovered_inputs_cleared:true,manual_inputs_cleared:true,bad_ledger_cleared:true,bad_zip_cleared:true,empty_after_rerun:true,zip_picker_reset:true,reopen_requires_confirmation:true,other_session_preserved:true,widths:[1440,768,390],page_errors:errors};
  }catch(error){await page.screenshot({path:out+'/clear-failure.png'}).catch(()=>{});await page.locator('body').ariaSnapshot().then(s=>fs.writeFile(out+'/clear-failure.txt',s)).catch(()=>{});throw error;}
  finally{await context.close();}
  report.owned_context_closed=true;await fs.writeFile(out+'/clear_verification.json',JSON.stringify(report,null,2));return report;
};
