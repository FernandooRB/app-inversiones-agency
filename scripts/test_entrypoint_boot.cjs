// Boundary tests: a dying child must not borrow health from a different server;
// only the synthetic secrets file may reach the launched Streamlit process.
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {EventEmitter}=require('node:events');
const {PassThrough}=require('node:stream');
const cp=require('node:child_process');

test('reject a failed child even if another server reports healthy',async()=>{
  const out=fs.mkdtempSync(path.join(os.tmpdir(),'sig-entrypoint-test-'));
  const previousSpawn=cp.spawn,previousFetch=global.fetch;
  const child=new EventEmitter();
  Object.assign(child,{exitCode:null,signalCode:null,stdout:new PassThrough(),stderr:new PassThrough(),kill(){this.exitCode=0;queueMicrotask(()=>this.emit('exit',0));}});
  let browserUsed=false;
  cp.spawn=()=>child;
  global.fetch=async()=>{child.exitCode=1;return {ok:true};};
  delete require.cache[require.resolve('./check_entrypoint_boot.cjs')];
  try{
    await assert.rejects(require('./check_entrypoint_boot.cjs')({browser:{newPage:async()=>{browserUsed=true;throw Error('Borrowed server');}},out,root:process.cwd(),python:'synthetic-python'}),/exited|failed|alive/);
    assert.equal(browserUsed,false);
    assert.equal(fs.existsSync(path.join(out,'entrypoint_boot.json')),false);
  }finally{
    cp.spawn=previousSpawn;global.fetch=previousFetch;
    delete require.cache[require.resolve('./check_entrypoint_boot.cjs')];
    assert(path.resolve(out).startsWith(path.resolve(os.tmpdir())+path.sep));
    fs.rmSync(out,{recursive:true,force:true});
  }
});

test('launch only with explicitly selected synthetic secrets',async()=>{
  const out=fs.mkdtempSync(path.join(os.tmpdir(),'sig-entrypoint-test-'));
  const previousSpawn=cp.spawn,previousFetch=global.fetch,previousSecrets=process.env.STREAMLIT_SECRETS_FILES;
  let launch;
  const child=new EventEmitter();
  Object.assign(child,{exitCode:null,signalCode:null,stdout:new PassThrough(),stderr:new PassThrough(),kill(){this.exitCode=0;queueMicrotask(()=>this.emit('exit',0));}});
  cp.spawn=(command,args,options)=>{launch={command,args,options};return child;};
  global.fetch=async()=>({ok:true});
  process.env.STREAMLIT_SECRETS_FILES='synthetic-inherited-config';
  delete require.cache[require.resolve('./check_entrypoint_boot.cjs')];
  const page={goto:async()=>{},getByRole:()=>({waitFor:async()=>{}}),getByTestId:()=>({count:async()=>0}),locator:()=>({count:async()=>0}),getByText:()=>({count:async()=>0}),evaluate:async()=>'es-MX',screenshot:async()=>{},close:async()=>{}};
  try{
    await require('./check_entrypoint_boot.cjs')({browser:{newPage:async()=>page},out,root:process.cwd(),python:'synthetic-python'});
    const index=launch.args.indexOf('--secrets.files');
    assert(index>=0,'Missing explicit secrets selection');
    assert.equal(launch.args[index+1],path.join(out,'entrypoint-workdir','.streamlit','secrets.toml'));
    assert.equal(launch.options.env.STREAMLIT_SECRETS_FILES,undefined);
  }finally{
    cp.spawn=previousSpawn;global.fetch=previousFetch;
    if(previousSecrets===undefined)delete process.env.STREAMLIT_SECRETS_FILES;else process.env.STREAMLIT_SECRETS_FILES=previousSecrets;
    delete require.cache[require.resolve('./check_entrypoint_boot.cjs')];
    assert(path.resolve(out).startsWith(path.resolve(os.tmpdir())+path.sep));
    fs.rmSync(out,{recursive:true,force:true});
  }
});
