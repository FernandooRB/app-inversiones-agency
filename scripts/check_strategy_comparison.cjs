// Fictional account analysis, current proposals and recovery; no orders or providers.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
  const python=process.env.SIG_PYTHON||'python';
  execFileSync(python,[path.join(__dirname,'strategy_comparison_fixture.py'),out],{env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'}});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const settle=async p=>{await p.waitForTimeout(200);await p.locator('[data-stale="true"]').first().waitFor({state:'detached'});};
  const expand=async(p,label)=>{
    const block=p.getByText(label,{exact:true}).first().locator('xpath=ancestor::*[@data-testid="stExpander"][1]');
    if(!await block.evaluate(el=>el.tagName==='DETAILS'?el.open:!!el.querySelector('details')?.open))await block.getByText(label,{exact:true}).click();
    return block;
  };
  const open=async(p,filename)=>{
    const block=await expand(p,'Abrir paquete de movimientos');
    await block.locator('input[type=file]').setInputFiles(path.join(out,filename));
    await p.getByText('Vista previa del paquete',{exact:true}).waitFor();await settle(p);
    await p.getByRole('button',{name:'Retomar movimientos',exact:true}).click();
    await p.getByText('Propuesta recuperada. Revisa sus datos y vuelve a confirmar para recalcular.',{exact:true}).waitFor({state:'attached'});
    await p.getByRole('tab',{name:'Implementación',exact:true}).click();await settle(p);
    if(await p.getByRole('radio',{name:'Libro de movimientos',exact:true}).isChecked()){
      await expand(p,'Preparar desde el libro de movimientos');
      await p.getByRole('checkbox',{name:/Cotejé títulos, efectivo liquidado/}).press('Space');
      await p.getByRole('button',{name:'Usar libro para preparar propuesta',exact:true}).click();
      await p.getByText('Posiciones y efectivo preparados. Revisa los costos y límites antes de calcular.',{exact:true}).waitFor();
      await settle(p);
    }
  };
  await page.goto(url+'?strategy_fixture=1');
  await open(page,'strategy_fixture_v3.zip');
  await page.getByText('Alternativa del análisis de cuenta',{exact:true}).click();await settle(page);
  const selection=page.getByRole('combobox',{name:'Alternativa objetivo del análisis',exact:true});
  await selection.click();await selection.fill('');
  await page.getByRole('option',{name:'Máximo Sharpe',exact:true}).click();
  await page.getByText(/Estrategia: Máximo Sharpe/).waitFor();await settle(page);
  const confirmation=page.getByRole('checkbox',{name:/Confirmé precios sin ajuste/});
  assert.equal(await confirmation.isChecked(),false);
  await confirmation.press('Space');await settle(page);
  const start=Date.now();
  await page.getByRole('button',{name:'Calcular propuesta de títulos',exact:true}).click();
  await page.getByText(/Efectivo final/).waitFor();await settle(page);
  const calculationMs=Date.now()-start;
  await page.getByRole('button',{name:'Comparar alternativas con estos insumos',exact:true}).click();
  await page.getByRole('button',{name:'Descargar comparación CSV',exact:true}).waitFor();await settle(page);
  assert.equal(await page.getByTestId('stException').count(),0);
  const download=async(p,label,name)=>{
    const event=p.waitForEvent('download');await p.getByText(label,{exact:true}).click();
    await (await event).saveAs(path.join(out,name));
  };
  await download(page,'Descargar comparación CSV','strategy_comparison.csv');
  await page.getByRole('button',{name:'Preparar PDF de la propuesta',exact:true}).click();
  await download(page,'Descargar PDF de la propuesta','strategy_proposal.pdf');
  await expand(page,'Guardar propuesta y revisión');
  await download(page,'Descargar paquete de movimientos','strategy_review_v4.zip');
  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const axe=await page.evaluate(async()=>{const r=await axe.run();return {violations:r.violations.map(x=>({id:x.id,impact:x.impact,nodes:x.nodes.map(n=>({target:n.target,html:n.html,summary:n.failureSummary}))})),incomplete:r.incomplete.map(x=>x.id),passes:r.passes.length};});
  fs.writeFileSync(path.join(out,'strategy_accessibility.json'),JSON.stringify(axe,null,2));
  const wcag=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});
  fs.writeFileSync(path.join(out,'strategy_wcag.json'),JSON.stringify(wcag,null,2));
  for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:900});
    await page.getByRole('heading',{name:'Conservar, cambio parcial y propuesta',exact:true}).evaluate(el=>el.scrollIntoView({block:'start'}));
    await page.screenshot({path:path.join(out,`strategy-comparison-${width}.png`)});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  }
  await page.setViewportSize({width:1440,height:900});
  const saved=JSON.parse(execFileSync(python,['-c',
    'import json,sys;from zipfile import ZipFile;from pathlib import Path;import pandas as pd;from pypdf import PdfReader;z=ZipFile(sys.argv[1]);m=json.loads(z.read("review.json"));p=json.loads(z.read("proposal/proposal.json"));t=pd.read_csv(sys.argv[2]);e=json.loads(Path(sys.argv[3]).read_text());assert m["schema"]==4 and p["schema"]==2;assert p["inputs"]["strategy"]["name"]=="Máximo Sharpe";assert all(abs(a-b)<1e-8 for a,b in zip(p["inputs"]["target"],e["weights"],strict=True));assert t["Alternativa"].tolist()==["Conservar","Cambio parcial","Propuesta"];assert t.iloc[0]["Costo"]==0 and t.iloc[0]["Efectivo"]==1000;assert abs(t.iloc[2]["Efectivo"]-p["result"]["cash"])<1e-8;assert t["Volatilidad anual"].notna().all();assert len(PdfReader(sys.argv[4]).pages)<=2;print(json.dumps({"cash":p["result"]["cash"],"schema":m["schema"],"risk_available":True}))',
    path.join(out,'strategy_review_v4.zip'),path.join(out,'strategy_comparison.csv'),path.join(out,'strategy_expected.json'),path.join(out,'strategy_proposal.pdf')],{encoding:'utf8'}));
  await selection.click();await selection.fill('');
  await page.getByRole('option',{name:'Pesos iguales',exact:true}).click();
  await page.getByText(/Estrategia: Pesos iguales/).waitFor();
  await page.getByText(/Efectivo final/).first().waitFor({state:'detached'});
  assert.equal(await confirmation.isChecked(),false);
  assert.equal(await page.getByText(/Efectivo final/).count(),0);
  const restored=await browser.newPage({viewport:{width:390,height:900}});
  await restored.goto(url);await open(restored,'strategy_review_v4.zip');
  await restored.getByText(/Procedencia guardada: Máximo Sharpe/).waitFor();
  const check=restored.getByRole('checkbox',{name:/Confirmé precios sin ajuste/});
  assert.equal(await check.isChecked(),false);
  await check.press('Space');await settle(restored);
  await restored.getByRole('button',{name:'Calcular propuesta de títulos',exact:true}).click();
  await restored.getByText(/Efectivo final/).waitFor();
  assert((await restored.getByText(/Efectivo final/).innerText()).includes(saved.cash.toFixed(2)));
  await restored.getByRole('button',{name:'Comparar alternativas con estos insumos',exact:true}).click();
  await restored.getByText(/Riesgo pendiente:/).waitFor();
  await restored.screenshot({path:path.join(out,'strategy-reopened-390.png')});
  assert.equal(await restored.getByTestId('stException').count(),0);
  fs.writeFileSync(path.join(out,'strategy_verification.json'),JSON.stringify({fictional_only:true,strategy_selected:true,three_plans:true,post_cost_risk:true,v4_reopened:true,new_confirmations:true,missing_model_is_pending:true,widths:[1440,768,390],physical_phone:false,human_test:false,calculation_ms:calculationMs,...saved},null,2));
  assert.equal(wcag.violations.length,0);
  assert.equal(axe.violations.filter(v=>['critical','serious'].includes(v.impact)).length,0);
  await restored.close();await page.close();
};
