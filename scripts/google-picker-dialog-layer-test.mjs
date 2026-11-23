import fs from 'node:fs';
import assert from 'node:assert/strict';

// Regression for native HTML dialog top-layer obscuring Google Picker's iframe.
// Exercise the production folder Picker function with mocked picker callbacks.
const app=fs.readFileSync(new URL('../app.js',import.meta.url),'utf8');
const start=app.indexOf('async function chooseUserDriveFolder(kind){');
const end=app.indexOf('async function openSharedLibraryPicker(){',start);
assert.ok(start>0&&end>start,'Drive folder picker function must be present');
const pickerSource=app.slice(start,end);
const makePicker=new Function('state','sharedLibraryFeatureReady',
  'ensureImporterGoogleAuth','loadGooglePickerApi','$','google','cfg',
  'location','isRetiredDriveRoot','console',
  pickerSource+';return chooseUserDriveFolder;');

async function run(action,options={}){
  const steps=[],state={token:'temporary-token',accountSub:'accountA',
    libraryRootId:'activeRoot0001'};
  const modal=options.modal!==false;
  const dialog={
    open:modal,closeCalls:0,showCalls:0,
    close(){assert.equal(this.open,true);this.open=false;this.closeCalls++;steps.push('suspend');},
    showModal(){assert.equal(this.open,false);this.open=true;this.showCalls++;steps.push('restore');}
  };
  let pickerShows=0,pickerHides=0,callbackCalls=0;
  class DocsView{
    setIncludeFolders(){return this;}setMimeTypes(){return this;}
    setSelectFolderEnabled(){return this;}setMode(){return this;}
  }
  class PickerBuilder{
    addView(){return this;}setOAuthToken(){return this;}
    setDeveloperKey(){return this;}setAppId(){return this;}
    setOrigin(){return this;}setTitle(){return this;}
    setCallback(callback){this.callback=callback;return this;}
    build(){
      return {setVisible:visible=>{
        steps.push(visible?'picker-open':'picker-close');
        if(!visible){pickerHides++;return;}
        pickerShows++;
        assert.equal(dialog.open,false,
          'The native modal MUST leave the browser top layer before Google Picker appears');
        if(action==='open-failed')throw Error('Picker open failed');
        queueMicrotask(()=>{
          if(action==='account-changed')state.accountSub='otherAccount';
          const response=action==='cancel'?{action:'cancel'}:
            {action:'picked',documents:[{id:action==='invalid-id'?'!invalid!':'folder00001',
              name:'XMID'}]};
          callbackCalls++;this.callback(response);
          if(action==='duplicate-callback'){callbackCalls++;this.callback(response);}
        });
      }};
    }
  }
  const google={picker:{
    DocsView,PickerBuilder,ViewId:{DOCS:'docs'},DocsViewMode:{LIST:'list'},
    Response:{ACTION:'action',DOCUMENTS:'documents'},
    Action:{CANCEL:'cancel',PICKED:'picked'},
    Document:{ID:'id',NAME:'name'}
  }};
  let verified=0,loaded=0;
  const choose=makePicker(state,()=>true,
    async()=>{verified++;},
    async()=>{loaded++;if(action==='load-failed')throw Error('Google Picker library failed');},
    ()=>dialog,google,{googlePickerApiKey:'test-key',googleAppId:'test-app'},
    {origin:'https://webbase-x.github.io'},()=>false,{warn(){}});
  let result,exception;
  try{result=await choose(options.kind||'music');}
  catch(error){exception=error;}
  return {result,exception,steps,dialog,pickerShows,pickerHides,
    callbackCalls,verified,loaded};
}
for(const kind of ['music','soundfont','fx']){
  const r=await run('picked',{kind});
  assert.deepEqual(r.result,{id:'folder00001',name:'XMID'});
  assert.deepEqual(r.steps,['suspend','picker-open','picker-close','restore']);
  assert.equal(r.dialog.open,true);
  assert.equal(r.dialog.closeCalls,1);
  assert.equal(r.dialog.showCalls,1);
}
for(const action of ['cancel','open-failed','account-changed','invalid-id','duplicate-callback']){
  const r=await run(action);
  assert.deepEqual(r.steps,['suspend','picker-open','picker-close','restore']);
  assert.equal(r.dialog.open,true,'Importer should be back above its page');
  assert.equal(r.pickerHides,1,'Picker should be hidden exactly once');
  if(action==='cancel')assert.equal(r.result,null);
  if(action==='open-failed')assert.match(r.exception?.message||'',/Picker open failed/);
  if(action==='account-changed')assert.match(r.exception?.message||'',/บัญชีหรือคลัง/);
  if(action==='invalid-id')assert.match(r.exception?.message||'',/Folder ID/);
}
const closed=await run('picked',{modal:false});
assert.deepEqual(closed.steps,['picker-open','picker-close'],
  'Do not open a formerly closed importer dialog');
assert.equal(closed.dialog.open,false);
const failedLoad=await run('load-failed');
assert.match(failedLoad.exception?.message||'',/Google Picker library failed/);
assert.deepEqual(failedLoad.steps,[],
  'Do not suspend importer until Picker is fully loaded and built');
assert.equal(failedLoad.dialog.open,true);
console.log('PASS: Google Picker appears above suspended native modal and restores importer after pick/cancel/failure without losing state');
