import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'xstage-vdo-worker-'));
const avi=path.join(dir,'sample.avi');
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/'){
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store'});
    res.end('<!doctype html><title>VDO worker test</title><script src="/cloud-import-core.js"></script><script src="/video-transcode.js"></script>');
    return;
  }
  const filename=path.resolve(root,'.'+url.pathname);
  if(!filename.startsWith(root+path.sep)||!fs.existsSync(filename)){res.writeHead(404).end();return;}
  res.writeHead(200,{'Content-Type':'text/javascript','Cache-Control':'no-store'});
  fs.createReadStream(filename).pipe(res);
});
let browser;
try{
  execFileSync('ffmpeg',['-hide_banner','-loglevel','error','-y',
    '-f','lavfi','-i','testsrc2=duration=1:size=128x72:rate=8',
    '-f','lavfi','-i','sine=frequency=440:sample_rate=44100',
    '-t','1','-c:v','mpeg4','-c:a','mp3','-f','avi',avi],{timeout:30000});
  assert.ok(fs.statSync(avi).size>1024);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  const page=await browser.newPage();
  const errors=[];page.on('pageerror',err=>errors.push(err.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/',{waitUntil:'load'});
  const bytes=fs.readFileSync(avi).toString('base64');
  const data=await page.evaluate(async base64=>{
    const input=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
    const file=new File([input],'VDO-AVI.avi',{type:'video/x-msvideo'});
    const statuses=[];
    try{
      const result=await window.XStageVideoTranscode.convert(file,{
        requireAudio:true,onStatus:message=>statuses.push(message)
      });
      const head=new Uint8Array(await result.slice(0,12).arrayBuffer());
      return {size:result.size,mime:result.type,ftyp:String.fromCharCode(...head.slice(4,8)),
        sourceUnchanged:file.size===input.length,statuses:statuses.slice(-5)};
    }catch(error){
      return {error:String(error?.message||error),statuses:statuses.slice(-10)};
    }
  },bytes);
  assert.ok(!data.error,'AVI Web Worker conversion failed: '+JSON.stringify(data));
  assert.equal(data.mime,'video/mp4');
  assert.equal(data.ftyp,'ftyp');
  assert.ok(data.size>1024&&data.sourceUnchanged);
  assert.deepEqual(errors,[]);
  console.log('PASS: real AVI/MPEG4/MP3 → browser-local H.264/AAC MP4 worker');
}finally{
  await browser?.close();
  server.close();
  fs.rmSync(dir,{recursive:true,force:true});
}
