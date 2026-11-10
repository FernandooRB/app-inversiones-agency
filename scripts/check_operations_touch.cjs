// Real touch events in a narrow Chromium context; fictional loopback app only.
const fs=require('node:fs/promises');
module.exports=async({browser,out,url})=>{
  if(!/^http:\/\/127\.0\.0\.1:[0-9]+\/$/.test(url))throw Error("Touch checks require the loopback fixture");
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,deviceScaleFactor:1});
  const page=await context.newPage();
  page.setDefaultTimeout(20000);
  let result;
  try{
    await page.goto(url);
    await page.getByRole("heading",{name:"Estado de la revisión",exact:true}).waitFor({state:"visible"});
    result=await(async()=>{
const folder=out;
const p=page;

const ensure=(value,message)=>{if(!value)throw Error(message);};
const f=p;
const settle=async(pp,ff)=>{await pp.waitForTimeout(250);await ff.locator('[data-stale="true"]').first().waitFor({state:'detached',timeout:20000});};
const metrics=[];
const tap=async(locator,label)=>{
  await locator.scrollIntoViewIfNeeded();
  const box=await locator.evaluate(el=>{const target=el.closest('button,a,label,summary,[role="tab"]')||el;const r=target.getBoundingClientRect();return {width:r.width,height:r.height};});
  metrics.push({label,...box});
  await fs.writeFile(out+'/touch_targets.json',JSON.stringify(metrics,null,2)+'\n');
  if(await locator.getAttribute('role')==='tab'){
    ensure(await locator.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Tab label is clipped');
  }
  await locator.tap();
};
const chooser=async(pp,ff,panel,label,file)=>{
  await settle(pp,ff);
  const area=panel.getByTestId('stFileUploader').filter({hasText:label});
  const trigger=area.getByRole('button',{name:/Upload|Browse files/}).first();
  const [selected]=await Promise.all([
    pp.waitForEvent('filechooser',{timeout:20000}),
    tap(trigger,'Seleccionar archivo: '+label),
  ]);
  await selected.setFiles(folder+'/'+file);
  await panel.getByRole('button',{name:'Remove '+file,exact:true}).waitFor({state:'visible'});
  await settle(pp,ff);
};
const geometry=await f.evaluate(()=>({width:innerWidth,maxTouchPoints:navigator.maxTouchPoints}));
ensure(geometry.width===390&&geometry.maxTouchPoints>0,'Touch emulation not applied');
if(!await f.getByRole('tab',{name:'Movimientos',exact:true}).isVisible().catch(()=>false)){
  await tap(f.getByText('Operación',{exact:true}),'Área Operación');await settle(p,f);
}
await tap(f.getByRole('tab',{name:'Movimientos',exact:true}),'Pestaña Movimientos');
const origin=f.getByRole('tabpanel',{name:'Movimientos',exact:true});
await tap(origin.getByText('Abrir paquete de movimientos',{exact:true}),'Abrir paquete de movimientos');
await chooser(p,f,origin,'Paquete de movimientos ZIP','operations.zip');
await tap(origin.getByRole('button',{name:'Retomar movimientos',exact:true}),'Retomar movimientos');await settle(p,f);
const rawLabel='Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre';
const flowLabel='Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida';
await tap(origin.getByText(rawLabel,{exact:true}),'Confirmación de fuentes');await settle(p,f);
await tap(origin.getByText(flowLabel,{exact:true}),'Confirmación de flujos original');await settle(p,f);
await origin.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
const pendingPopup=p.waitForEvent('popup',{timeout:20000});
await tap(f.getByRole('link',{name:'Probar con datos ficticios',exact:true}),'Abrir demo');
const demo=await pendingPopup;demo.setDefaultTimeout(20000);
let d;
for(let i=0;i<60;i++){
  const candidate=demo;
  if(await candidate.getByRole('heading',{name:'Demo de revisión',exact:true}).isVisible().catch(()=>false)){d=candidate;break;}
  await demo.waitForTimeout(500);
}
ensure(d,'Demo did not load');
await settle(demo,d);
const panel=d.getByRole('tabpanel',{name:'Movimientos',exact:true});
const capture=async(name)=>{
  await d.evaluate(()=>document.querySelector('[data-testid="stMain"]').scrollTop=0);
  await demo.waitForTimeout(250);
  ensure(!await d.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),'Page overflow');
  await demo.screenshot({path:folder+'/'+name+'.png'});
};
const before=await d.evaluate(()=>({width:innerWidth,maxTouchPoints:navigator.maxTouchPoints}));
ensure(before.width===390&&before.maxTouchPoints>0,'Popup lost touch viewport');
ensure(!await panel.getByLabel(flowLabel,{exact:true}).isChecked(),'Demo imported consent');
await capture('touch-start');
await tap(d.getByRole('button',{name:'Abrir calendario de valuaciones',exact:true}),'Siguiente: calendario');await settle(demo,d);
await tap(d.getByText('Guía de práctica',{exact:true}),'Guía de práctica');
// The bounded native-download helper is inserted by the runner below.
const download=async(pp,button,suggested,name)=>{
  const pending=pp.waitForEvent("download",{timeout:20000});
  await tap(button,suggested);
  const selected=await pending;
  ensure(selected.suggestedFilename()===suggested,"Unexpected download name");
  await selected.saveAs(folder+"/"+name);return fs.readFile(folder+"/"+name);
};
const csv=await download(demo,d.getByRole('button',{name:'Descargar valuaciones completas del demo',exact:true}),'valuaciones_demo_completas.csv','valuaciones_demo_completas.csv');
ensure(csv.toString('utf8')==='Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,150\n','Corrective CSV differs');
await chooser(demo,d,panel,'Valuaciones históricas verificadas: Fecha,NAV','valuaciones_demo_completas.csv');
await tap(d.getByText('Guía de práctica',{exact:true}),'Cerrar guía');
await tap(d.getByRole('button',{name:'Abrir revisión de flujos',exact:true}),'Siguiente: revisar flujos');await settle(demo,d);
ensure(!await panel.getByLabel(flowLabel,{exact:true}).isChecked(),'Navigation granted consent');
ensure(await panel.getByTestId('stMetric').count()===0,'Result exists before confirmation');
await capture('touch-calendar-complete');
await tap(panel.getByText(flowLabel,{exact:true}),'Confirmación de flujos demo');await settle(demo,d);
await panel.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
await tap(d.getByRole('button',{name:'Abrir resumen descargable',exact:true}),'Siguiente: resumen');await settle(demo,d);
const report=(await download(demo,d.getByRole('button',{name:'Descargar resumen de revisión',exact:true}),'demo_resumen_revision_2026-01-10.txt','touch_demo_summary.txt')).toString('utf8');
ensure(report.startsWith('DEMO · Resumen de práctica de Operación'),'Demo mark missing');
ensure(report.includes('TWR del periodo: 0.00%')&&report.includes('Diferencia libro − control: -0.01 MXN.'),'Result or pending difference changed');
const baseline=await fs.readFile(folder+'/demo_review_summary.txt','utf8');
const meta={...JSON.parse(baseline.split('Huellas de los insumos y el código\n')[1].split('\n\nAprobación humana:')[0]),commit:process.env.GITHUB_SHA||'local-fixture'};
const manifest=JSON.parse(report.split('Huellas de los insumos y el código\n')[1].split('\n\nAprobación humana:')[0]);
ensure(JSON.stringify(manifest.inputs)===JSON.stringify(meta.inputs),'Demo inputs differ');
ensure(JSON.stringify(manifest.code_sha256)===JSON.stringify(meta.code_sha256),'Published core code differs');
await capture('touch-result');
await tap(d.getByText('Guía de práctica',{exact:true}),'Abrir guía para reiniciar');
await tap(d.getByRole('button',{name:'Reiniciar datos de práctica',exact:true}),'Reiniciar práctica');await settle(demo,d);
ensure(await panel.getByTestId('stMetric').count()===0,'Reset retained result');
ensure(!await panel.getByLabel(flowLabel,{exact:true}).isChecked(),'Reset retained consent');
await d.getByText('4 pendientes de revisión',{exact:true}).waitFor({state:'visible'});
await capture('touch-reset');
await demo.close();
ensure(await origin.getByLabel(flowLabel,{exact:true}).isChecked(),'Original flow confirmation changed');
ensure(await origin.getByLabel(rawLabel,{exact:true}).isChecked(),'Original source confirmation changed');
await origin.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
ensure(await origin.getByRole('button',{name:'Remove operations.zip',exact:true}).count()===1,'Original file changed');
await tap(origin.getByRole('button',{name:'Quitar archivo recuperado · Libro de movimientos',exact:true}),'Retirar libro ficticio de prueba');
await origin.getByText('Importa el libro para revisar saldos y flujos',{exact:false}).waitFor({state:'visible'});
ensure(metrics.every(x=>x.width>=43.9&&x.height>=43.9),'Touch target below 44px: '+JSON.stringify(metrics.filter(x=>x.width<43.9||x.height<43.9)));
await p.close();
const evidence={reference_commit:meta.commit,checked_at_utc:new Date().toISOString(),viewport:geometry,
  browser:'Chromium/Edge touch emulation',physical_device:false,human_test:false,
  fictional_only:true,tap_navigation:true,native_file_chooser:true,native_csv_download:true,native_txt_download:true,
  complete_dates_do_not_confirm:true,twr_zero:true,exact_cent_preserved:true,hashes_match_reference:true,
  reset_verified:true,original_tab_preserved:true,synthetic_inputs_removed:true,owned_pages_closed:true,owned_browser_closed:false,
  page_overflow:false,target_measurements:metrics,targets_under_44px:metrics.filter(x=>x.height<43.9||x.width<43.9),
  original_documents_uploaded:false,credentials_read:false,hosting_monthly_usd:0};
return evidence;

    })();
  }catch(error){
    if(!page.isClosed()){
      await page.screenshot({path:out+"/touch-failure.png"}).catch(()=>{});
      await page.locator("body").ariaSnapshot().then(text=>fs.writeFile(out+"/touch-failure.txt",text)).catch(()=>{});
    }
    throw error;
  }finally{await context.close();}
  delete result.owned_browser_closed;
  result.owned_context_closed=true;
  await fs.writeFile(out+"/touch_verification.json",JSON.stringify(result,null,2)+"\n");
  return result;
};
