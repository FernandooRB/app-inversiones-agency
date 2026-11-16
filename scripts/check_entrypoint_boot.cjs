// Start the real entrypoint with synthetic local auth and verify the anonymous gate.
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const net=require('node:net');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const unusedPort=()=>new Promise((resolve,reject)=>{
  const socket=net.createServer();socket.once('error',reject);
  socket.listen(0,'127.0.0.1',()=>{const port=socket.address().port;socket.close(error=>error?reject(error):resolve(port));});
});
module.exports=async({browser,out,root,python})=>{
  const cwd=path.join(out,'entrypoint-workdir');
  fs.mkdirSync(path.join(cwd,'.streamlit'),{recursive:true});
  // No identity/provider calls: only render the anonymous login button.
  const secretsFile=path.join(cwd,'.streamlit','secrets.toml');
  fs.writeFileSync(secretsFile,'[auth]\ncookie_secret="synthetic-entrypoint-cookie-secret-not-for-real-use"\n');
  const env={...process.env,PYTHONPATH:root,OPENBLAS_NUM_THREADS:'1',OMP_NUM_THREADS:'1'};
  for(const key of ['STREAMLIT_SECRETS_FILES','SIG_SECRETS_FILE','SIG_SECRETS_TOML'])delete env[key];
  const port=await unusedPort();
  const url=`http://127.0.0.1:${port}`;
  const server=spawn(python,['-u','-m','streamlit','run',path.join(root,'app_inversiones.py'),
    '--server.address','127.0.0.1','--server.port',String(port),'--server.fileWatcherType','none',
    '--server.headless','true','--secrets.files',secretsFile],{cwd,env,stdio:['ignore','pipe','pipe']});
  let spawnFailure;
  server.once('error',error=>{spawnFailure=error;});
  const assertAlive=()=>{if(spawnFailure||server.exitCode!==null||server.signalCode!==null)throw Error('Real entrypoint child exited or failed');};
  const log=fs.createWriteStream(path.join(out,'entrypoint-server.log'));
  server.stdout.pipe(log,{end:false});server.stderr.pipe(log,{end:false});
  let page;
  try{
    let healthy=false;
    for(let i=0;i<100;i++){
      assertAlive();
      try{healthy=(await fetch(url+'/_stcore/health',{signal:AbortSignal.timeout(1000)})).ok;}catch{}
      assertAlive();
      if(healthy)break;await pause(250);
    }
    assert(healthy,'Real entrypoint did not become healthy');
    page=await browser.newPage({viewport:{width:1440,height:900}});
    await page.goto(url+'/');
    await page.getByRole('button',{name:'Iniciar sesión',exact:true}).waitFor({timeout:30000});
    assert.equal(await page.getByTestId('stException').count(),0);
    assert.equal(await page.locator('.st-key-workspace_area').count(),0);
    assert.equal(await page.getByText('La app se actualizó y requiere reiniciar el proceso para continuar con una versión coherente.',{exact:true}).count(),0);
    assert.equal(await page.evaluate(()=>document.documentElement.lang),'es-MX');
    await page.screenshot({path:path.join(out,'entrypoint-login.png')});
    assertAlive();
    fs.writeFileSync(path.join(out,'entrypoint_boot.json'),JSON.stringify({real_entrypoint:true,synthetic_auth:true,provider_calls:false,anonymous_login_visible:true,anonymous_workspace_blocked:true,no_false_restart_guard:true,no_exceptions:true,lang:'es-MX'},null,2));
  }finally{
    if(page)await page.close();
    if(server.exitCode===null&&!spawnFailure){const exited=new Promise(resolve=>server.once('exit',resolve));server.kill('SIGTERM');await Promise.race([exited,pause(5000)]);}
    server.stdout.unpipe(log);server.stderr.unpipe(log);
    await new Promise((resolve,reject)=>{log.once('error',reject);log.once('close',resolve);log.end();});
  }
};
