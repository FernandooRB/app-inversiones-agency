// Fictional operations review only. Starts and stops its own loopback Streamlit process.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const {chromium}=require('playwright-core');
const root=path.resolve(__dirname,'..');
const out=path.resolve(process.env.SIG_BROWSER_OUTPUT||path.join(root,'tmp','operations_browser'));
const port=8540;
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
fs.mkdirSync(out,{recursive:true});
const appFile=path.join(out,'app.py');
fs.writeFileSync(appFile,`import streamlit as st
from operations_ui import _ledger
from portfolio_core import PortfolioError
from workspace_presentation import render_shell
st.set_page_config(page_title="SIG | Revisión portable ficticia", layout="wide")
render_shell(areas=("Operación",))
st.title("Operación por cuenta")
st.caption("Cuenta ficticia SIM-REVISION · comprobación local")
try:
    _ledger((None, None, None, None))
except PortfolioError as exc:
    st.error(str(exc))
`);
const server=spawn(process.env.SIG_PYTHON||'python',['-u','-m','streamlit','run',appFile,
  '--server.address','127.0.0.1','--server.port',String(port),'--server.fileWatcherType','none',
  '--server.headless','true'],{cwd:root,env:{...process.env,PYTHONPATH:root,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'},stdio:['ignore','pipe','pipe']});
const serverLog=fs.createWriteStream(path.join(out,'server.log'));
server.stdout.pipe(serverLog,{end:false});server.stderr.pipe(serverLog,{end:false});
let browser;
(async()=>{
  const deadline=Date.now()+60000;let healthy=false;
  while(Date.now()<deadline){
    if(server.exitCode!==null)throw Error('Local test server exited before becoming ready');
    try{healthy=(await fetch(`http://127.0.0.1:${port}/_stcore/health`,{signal:AbortSignal.timeout(2000)})).ok;}catch{}
    if(healthy)break;await pause(500);
  }
  assert(healthy,'Local test server was not ready within 60 seconds');
  const header='ID,Fecha,Liquidacion,Tipo,Instrumento,Moneda,Cantidad,Precio,Importe,Comision,Impuesto,Referencia,MomentoFlujo,Interes\n';
  fs.writeFileSync(path.join(out,'ledger.csv'),header+'opening,2026-01-01,2026-01-01,OPEN_CASH,,MXN,0,0,100,0,0,,UNKNOWN,0\n'+'flow,2026-01-05,2026-01-05,DEPOSIT,,MXN,0,0,50,0,0,,EOD,0\n');
  fs.writeFileSync(path.join(out,'nav.csv'),'Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,150\n');
  fs.writeFileSync(path.join(out,'nav_changed.csv'),'Fecha,NAV\n2026-01-01,100\n2026-01-05,150\n2026-01-10,160\n');
  fs.writeFileSync(path.join(out,'controls.csv'),'Fecha,Tipo,InstrumentoReferencia,Moneda,Saldo,Fuente\n2026-01-10,CASH,,MXN,150.01,Estado ficticio\n');
  fs.writeFileSync(path.join(out,'invalid.zip'),'invalid fictional package');
  browser=await chromium.launch({channel:process.platform==='win32'?'msedge':'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:900}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${port}/`);
  const input=(p,label)=>p.getByTestId('stFileUploader').filter({hasText:label}).locator('input[type=file]');
  const rawLabel='Confirmé las cotizaciones sin ajuste y las valuaciones contra las fuentes del cierre';
  const flowLabel='Concilié todos los flujos externos y las valuaciones del periodo en la moneda elegida';
  await input(page,'Libro normalizado de movimientos').setInputFiles(path.join(out,'ledger.csv'));
  const cutoff=page.getByTestId('stDateInput').locator('input');
  await cutoff.fill('2026/01/10');await cutoff.press('Enter');
  await page.getByText('Conciliar contra el estado de cuenta',{exact:true}).click();
  await input(page,'Controles de cierre').setInputFiles(path.join(out,'controls.csv'));
  await page.getByText(/Con diferencia: 1 · Sin control: 0/).waitFor({state:'visible'});
  await input(page,'Valuaciones históricas verificadas:').setInputFiles(path.join(out,'nav.csv'));
  await page.getByText(rawLabel,{exact:true}).click();
  await page.getByText(flowLabel,{exact:true}).click();
  await page.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
  await page.getByText('Guardar revisión de movimientos',{exact:true}).click();
  const downloaded=page.waitForEvent('download');
  await page.getByText('Descargar paquete de movimientos',{exact:true}).click();
  await (await downloaded).saveAs(path.join(out,'operations.zip'));
  const restored=await browser.newPage({viewport:{width:1440,height:900}});
  restored.on('pageerror',e=>errors.push(e.message));
  await restored.goto(`http://127.0.0.1:${port}/`);
  await restored.getByText('Abrir paquete de movimientos',{exact:true}).click();
  await input(restored,'Paquete de movimientos ZIP').setInputFiles(path.join(out,'operations.zip'));
  await restored.getByRole('button',{name:'Retomar movimientos',exact:true}).click();
  await restored.getByText(/Revisión recuperada/).waitFor({state:'visible'});
  assert.equal(await restored.getByTestId('stDateInput').locator('input').inputValue(),'2026/01/10');
  assert.equal(await restored.getByLabel(rawLabel,{exact:true}).isChecked(),false);
  assert.equal(await restored.getByLabel(flowLabel,{exact:true}).isChecked(),false);
  assert.equal(await restored.getByTestId('stMetric').count(),0);
  await restored.getByText('Conciliar contra el estado de cuenta',{exact:true}).click();
  await restored.getByText(/Con diferencia: 1 · Sin control: 0/).waitFor({state:'visible'});
  await restored.getByText('Guardar revisión de movimientos',{exact:true}).click();
  for(const width of [1440,768,390]){
    await restored.setViewportSize({width,height:width===390?844:900});
    await restored.getByText('Guardar revisión de movimientos',{exact:true}).scrollIntoViewIfNeeded();
    await restored.screenshot({path:path.join(out,`restored-${width}.png`)});
    assert.equal(await restored.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false);
    const cdp=await restored.context().newCDPSession(restored);
    const snapshot=await cdp.send('Page.captureSnapshot',{format:'mhtml'});
    fs.writeFileSync(path.join(out,`restored-${width}.mhtml`),snapshot.data);await cdp.detach();
  }
  await restored.getByText(flowLabel,{exact:true}).click();
  await restored.getByTestId('stMetric').filter({hasText:'TWR del periodo'}).getByText('0.00%',{exact:true}).waitFor({state:'visible'});
  await restored.getByTestId('stSelectbox').filter({hasText:'Moneda del rendimiento y valuación'}).getByRole('combobox').click();
  await restored.getByRole('option',{name:'USD',exact:true}).click();
  await restored.getByTestId('stMetric').first().waitFor({state:'detached'});
  assert.equal(await restored.getByLabel(flowLabel,{exact:true}).isChecked(),false);
  await input(restored,'Valuaciones históricas verificadas:').setInputFiles(path.join(out,'nav_changed.csv'));
  await restored.getByRole('button',{name:'Remove nav_changed.csv',exact:true}).click();
  assert.equal(await restored.getByText('Recuperado: Valuaciones históricas.',{exact:true}).count(),0);
  await input(restored,'Paquete de movimientos ZIP').setInputFiles(path.join(out,'invalid.zip'));
  await restored.getByRole('button',{name:'Retomar movimientos',exact:true}).click();
  await restored.getByText(/El paquete de movimientos no supera/).waitFor({state:'visible'});
  assert.equal(await restored.getByTestId('stDateInput').locator('input').inputValue(),'2026/01/10');
  await restored.getByRole('button',{name:'Remove invalid.zip',exact:true}).click();
  await restored.getByRole('button',{name:'Quitar archivo recuperado · Libro de movimientos',exact:true}).click();
  await restored.getByText(/Importa el libro para revisar saldos y flujos/).waitFor({state:'visible'});
  assert.equal(errors.length,0);assert.equal(await restored.getByTestId('stException').count(),0);
  fs.writeFileSync(path.join(out,'browser_verification.json'),JSON.stringify({fictional_only:true,native_zip_download:true,new_session_reopen:true,cutoff_and_currency_restored:true,confirmations_reset:true,cent_difference_preserved:true,eod_neutral_twr_zero:true,currency_change_invalidates_consent:true,replacement_removal_does_not_resurrect:true,bad_zip_keeps_current_review:true,ledger_removal_clears_screen:true,widths:[1440,768,390],page_errors:errors},null,2));
  console.log('Operations browser verification passed with fictional data');
})().catch(async e=>{
  console.error(e.message);
  if(browser){let n=0;for(const context of browser.contexts())for(const page of context.pages())
    await page.screenshot({path:path.join(out,`failure-${n++}.png`)}).catch(()=>{});}
  process.exitCode=1;
}).finally(async()=>{
  if(browser)await browser.close();
  server.kill('SIGTERM');serverLog.end();
});
