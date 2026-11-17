// Fictional in-app criteria only; no scheduled source or real documents.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
module.exports=async({browser,out,url})=>{
 execFileSync(process.env.SIG_PYTHON||'python',[path.join(__dirname,'policy_alerts_fixture.py'),out],{env:{...process.env,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'}});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(45000);
 const ready=async()=>{await page.waitForTimeout(250);await page.locator('.stApp[data-test-script-state="notRunning"]').waitFor();};
 const expand=async label=>{const b=page.getByText(label,{exact:true}).first().locator('xpath=ancestor::*[@data-testid="stExpander"][1]');if(!await b.evaluate(e=>e.tagName==='DETAILS'?e.open:!!e.querySelector('details')?.open))await b.getByText(label,{exact:true}).click();await ready();return b;};
 const download=async(label,name)=>{const event=page.waitForEvent('download');await page.getByRole('button',{name:label,exact:true}).click();await (await event).saveAs(path.join(out,name));await ready();};
 const open=async filename=>{const b=await expand('Abrir paquete de movimientos');await b.locator('input[type=file]').setInputFiles(path.join(out,filename));await page.getByText('Vista previa del paquete',{exact:true}).waitFor();await ready();await page.getByRole('button',{name:/^(Retomar movimientos|Reemplazar revisión con este paquete)$/}).click();await page.getByText(/Revisión recuperada/).waitFor();await ready();};
 await page.goto(url);await page.getByRole('tab',{name:'Movimientos',exact:true}).click();await open('policy_fixture_v1.zip');
 const raw=page.getByRole('checkbox',{name:'Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre',exact:true});await raw.press('Space');await ready();
 let block=await expand('Política y avisos de cartera');
 const number=label=>block.getByRole('spinbutton',{name:label,exact:true});
 assert.equal(await number('Máximo individual · % de la base elegida').inputValue(),'');
 await block.getByRole('textbox',{name:'Fuente de la política',exact:true}).fill('Política ficticia SIG');await page.keyboard.press('Tab');await ready();
 await block.getByRole('textbox',{name:'Pesos objetivo CSV · PesoObjetivo en %',exact:true}).fill('Instrumento,Moneda,PesoObjetivo\nAAA,MXN,60\n');await page.keyboard.press('Tab');await ready();
 for(const [label,v] of [['Tolerancia de desvío · puntos porcentuales','5'],['Máximo individual · % de la base elegida','50'],['Mínimo de efectivo disponible · % del patrimonio neto','20']]){await number(label).fill(v);await number(label).press('Enter');await ready();}
 const consent=page.getByRole('checkbox',{name:'Confirmé la política, la cuenta y las fuentes de este corte',exact:true});assert.equal(await consent.isChecked(),false);await consent.press('Space');await ready();
 await page.getByText('Política: 1 desvíos · 0 pendientes · 2026-01-10',{exact:true}).waitFor();
 await download('Descargar avisos de política CSV','policy_alerts.csv');await download('Descargar política propuesta JSON','policy_proposed.json');
 await expand('Guardar revisión de movimientos');await download('Descargar paquete de movimientos','policy_review_v5.zip');
 await expand('Archivos y resumen descargable');await download('Descargar resumen de revisión','policy_summary.txt');await page.getByRole('button',{name:'Preparar PDF breve',exact:true}).click();await ready();await download('Descargar PDF de rendimiento','policy_performance.pdf');
 assert(fs.readFileSync(path.join(out,'policy_summary.txt'),'utf8').includes('"policy_report"'));
 await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
 const axe=await page.evaluate(async()=>{const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}});return {violations:r.violations,incomplete:r.incomplete,passes:r.passes.length};});fs.writeFileSync(path.join(out,'policy_accessibility.json'),JSON.stringify(axe,null,2));assert.equal(axe.violations.length,0);
 for(const width of [1440,768,390]){await page.setViewportSize({width,height:1100});await page.waitForTimeout(400);await block.getByText('Compara este corte con los criterios que declares y confirmes.',{exact:true}).evaluate(e=>{e.style.scrollMarginTop='70px';e.scrollIntoView({block:'start'});});await page.screenshot({path:path.join(out,`policy-alerts-${width}.png`)});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));}
 // Replacing the review and opening v5 must restore proposed criteria only.
 await open('policy_review_v5.zip');block=await expand('Política y avisos de cartera');assert.equal(await raw.isChecked(),false);assert.equal(await consent.isChecked(),false);assert.equal(Number(await number('Máximo individual · % de la base elegida').inputValue()),50);
 await raw.press('Space');await ready();await consent.press('Space');await ready();await page.getByText('Política: 1 desvíos · 0 pendientes · 2026-01-10',{exact:true}).waitFor();
 await number('Máximo individual · % de la base elegida').fill('70');await number('Máximo individual · % de la base elegida').press('Enter');await ready();assert.equal(await consent.isChecked(),false);
 await expand('Guardar revisión de movimientos');await download('Descargar paquete de movimientos','policy_changed_v5.zip');
 const result=JSON.parse(execFileSync(process.env.SIG_PYTHON||'python',['-c','import sys,json;from pathlib import Path;from operations_review import read_operations_review;from pypdf import PdfReader;m,f=read_operations_review(Path(sys.argv[1]).read_bytes());n,g=read_operations_review(Path(sys.argv[2]).read_bytes());assert m["schema"]==5 and m["policy_data"]["max_weight"]=="0.5";assert n["policy_data"]["max_weight"]=="0.7";assert len(PdfReader(sys.argv[3]).pages)==2;print(json.dumps({"schema":5,"old_max":"0.5","new_max":"0.7","pdf_pages":2}))',path.join(out,'policy_review_v5.zip'),path.join(out,'policy_changed_v5.zip'),path.join(out,'policy_performance.pdf')],{encoding:'utf8'}));
 await block.getByText('Política y avisos de cartera',{exact:true}).click();await ready();await expand('Archivos y resumen descargable');await download('Descargar resumen de revisión','policy_closed_summary.txt');assert(fs.readFileSync(path.join(out,'policy_closed_summary.txt'),'utf8').includes('"policy_report": null'));
 assert.equal(await page.getByTestId('stException').count(),0);
 fs.writeFileSync(path.join(out,'policy_verification.json'),JSON.stringify({fictional_only:true,...result,no_active_default_limits:true,net_weight:.6,cash_available:40,initial_deviations:1,initial_pending:0,zip_restores_proposals_only:true,replacement_renews_confirmation:true,edited_policy_is_in_current_zip:true,closed_panel_removes_result:true,widths:[1440,768,390],wcag_violations:axe.violations.length},null,2));
 await page.close();
};
