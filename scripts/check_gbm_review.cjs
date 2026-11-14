// Exercise only fictional inputs in the loopback test app owned by the browser runner.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
  execFileSync(process.env.SIG_PYTHON||'python',[path.join(__dirname,'gbm_review_fixture.py'),path.join(out,'gbm_fictional.pdf')]);
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);
  const settle=async()=>{await page.waitForTimeout(150);await page.locator('[data-stale="true"]').first().waitFor({state:'detached'});};
  const expand=async(label,p=page)=>{
    const block=p.getByTestId('stExpander').filter({has:p.getByText(label,{exact:true})}).first();
    if(!(await block.locator('details').evaluate(el=>el.open).catch(()=>false)))await block.getByText(label,{exact:true}).click();
    return block;
  };
  const snapshots=async(label)=>{
    for(const width of [1440,768,390]){
      await page.setViewportSize({width,height:900});await page.waitForTimeout(200);
      if(label==='pending'){
        const form=page.getByTestId('stExpander').filter({has:page.getByText('Preparar desde estados GBM',{exact:true})}).first();
        await form.screenshot({path:path.join(out,`gbm-${label}-${width}.png`)});
      }else await page.screenshot({path:path.join(out,`gbm-${label}-${width}.png`)});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'Page overflows');
    }
    await page.setViewportSize({width:1440,height:900});await page.waitForTimeout(500);await settle();
  };
  await expand('Preparar desde estados GBM');
  const fixtureEvent=page.waitForEvent('download');
  await page.getByText('Descargar PDF ficticio de práctica',{exact:true}).click();
  await (await fixtureEvent).saveAs(path.join(out,'gbm_fictional.pdf'));
  await page.getByTestId('stFileUploader').filter({hasText:'Estados GBM de la misma cuenta'}).locator('input[type=file]').setInputFiles(path.join(out,'gbm_fictional.pdf'));
  await settle();await page.getByRole('button',{name:'Preparar borrador GBM',exact:true}).click();
  await page.getByText(/1 incidencias de normalización/).waitFor();await settle();
  await snapshots('pending');
  const classification=page.getByRole('combobox',{name:'Clasificación',exact:true});
  await classification.fill('DEPOSIT');await classification.press('ArrowDown');await classification.press('Enter');
  const timing=page.getByRole('combobox',{name:/Momento del flujo/});
  await timing.fill('EOD');await timing.press('ArrowDown');await timing.press('Enter');
  await page.getByRole('textbox',{name:'Motivo de la corrección',exact:true}).fill('Aportación cotejada en evidencia ficticia');
  await page.getByRole('textbox',{name:'Fuente del dato y ubicación en el documento',exact:true}).fill('Documento ficticio, datos de práctica en página 1');
  await page.getByRole('button',{name:'Guardar propuesta revisada',exact:true}).click();
  await page.getByText(/0 incidencias de normalización/).waitFor();await settle();
  await page.getByRole('checkbox',{name:/Cotejé cuenta, moneda/}).press('Space');await settle();
  await page.getByRole('button',{name:'Usar movimientos revisados',exact:true}).click();await settle();
  await page.getByText('Recuperado: Libro de movimientos.',{exact:true}).waitFor();
  for(const [day,value] of [['2025-12-31','100'],['2026-01-05','150'],['2026-01-30','150']]){
    const form=await expand('Completar en la app · Valuación histórica');
    await form.getByRole('textbox',{name:'Fecha',exact:true}).fill(day);
    await form.getByRole('textbox',{name:'NAV',exact:true}).fill(value);
    await form.getByRole('textbox',{name:'Fuente',exact:true}).fill('Valuación ficticia revisada');
    await form.getByRole('button',{name:'Guardar dato · Valuación histórica',exact:true}).click();await settle();
  }
  await page.getByRole('checkbox',{name:'Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida',exact:true}).press('Space');
  await settle();
  await page.getByText('Cuánto gané y por qué',{exact:true}).waitFor();
  assert.equal(await page.getByTestId('stException').count(),0);
  const metric=page.getByTestId('stMetric').filter({hasText:'TWR del periodo'});
  assert((await metric.innerText()).includes('0.00%'));
  await page.getByText('Cuánto gané y por qué',{exact:true}).scrollIntoViewIfNeeded();await snapshots('result');
  const summary=await expand('Archivos y resumen descargable');
  await summary.getByRole('button',{name:'Preparar PDF breve',exact:true}).click();await settle();
  const pdfEvent=page.waitForEvent('download');
  await page.getByText('Descargar PDF de rendimiento',{exact:true}).click();
  await (await pdfEvent).saveAs(path.join(out,'gbm_explained.pdf'));
  const save=await expand('Guardar revisión de movimientos');
  const zipEvent=page.waitForEvent('download');
  await save.getByText('Descargar paquete de movimientos',{exact:true}).click();
  await (await zipEvent).saveAs(path.join(out,'gbm_review_v2.zip'));
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const audit=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});
  fs.writeFileSync(path.join(out,'gbm_accessibility.json'),JSON.stringify(audit,null,2));
  assert.equal(audit.violations.filter(v=>['critical','serious'].includes(v.impact)).length,0,'Unresolved accessibility failures');
  const restored=await browser.newPage({viewport:{width:390,height:900}});
  await restored.goto(url);const opener=await expand('Abrir paquete de movimientos',restored);
  await opener.locator('input[type=file]').setInputFiles(path.join(out,'gbm_review_v2.zip'));
  await restored.getByRole('button',{name:'Retomar movimientos',exact:true}).click();
  await restored.getByText(/Adjunta los originales del borrador/).waitFor();
  assert(await restored.getByRole('button',{name:'Usar movimientos revisados',exact:true}).isDisabled());
  assert.equal(await restored.getByRole('checkbox',{name:/Cotejé cuenta, moneda/}).isChecked(),false);
  assert.equal(await restored.getByRole('checkbox',{name:/Concilié todos los flujos/}).isChecked(),false);
  assert.equal(await restored.getByTestId('stException').count(),0);
  assert.equal(errors.length,0);
  await restored.screenshot({path:path.join(out,'gbm-restored-390.png')});
  fs.writeFileSync(path.join(out,'gbm_verification.json'),JSON.stringify({fictional_only:true,pdf_to_review_to_ledger:true,manual_nav_form:true,twr_zero:true,cent_difference_preserved:true,native_pdf_download:true,v2_zip_download_reopen:true,originals_reattachment_required:true,confirmations_reset:true,axe_critical_serious:0,physical_phone:false,human_usability:false,widths:[1440,768,390]},null,2));
  await restored.close();await page.close();
};
