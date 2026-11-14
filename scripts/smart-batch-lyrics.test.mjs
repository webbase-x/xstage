import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {correctLrc,validateRules,runBatch,undoBatch} from '../tools/smart-batch-lyrics.mjs';

test('timestamp bytes, newline style, metadata and unrelated lyrics remain unchanged',()=>{
 const before='[ar:Artist]\r\n[00:01.20]ผิด ถูก\r\n[00:02.300]ไม่แก้\r\n';
 const after=correctLrc(before,[{from:'ผิด',to:'ถูกต้อง'}]);
 assert.equal(after.status,'changed');
 assert.equal(after.text,'[ar:Artist]\r\n[00:01.20]ถูกต้อง ถูก\r\n[00:02.300]ไม่แก้\r\n');
 assert.equal(after.replacements,1);
});
test('abnormal timing never writes',()=>{
 assert.equal(correctLrc('[00:03.00]a\n[00:01.00]b',[{from:'a',to:'c'}]).status,'skipped');
 assert.equal(correctLrc('ordinary text',[{from:'a',to:'b'}]).status,'skipped');
 assert.throws(()=>validateRules([{from:'[00:01]',to:'x'}]));
 assert.throws(()=>validateRules([{from:'a',to:'x\nz'}]));
});
test('dry run, apply, backup, undo and conflict protection', async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'xstage-lyrics-'));
 try {
  const file=path.join(root,'001.lrc'),invalid=path.join(root,'002.lrc');
  const original='[00:01.00]ผิด\n[00:02.00]เดิม\n';
  await fs.writeFile(file,original);
  await fs.writeFile(invalid,'[00:02.00]a\n[00:01.00]b\n');
  const rules=[{from:'ผิด',to:'ถูก'}];
  const dry=await runBatch({root,rules});
  assert.equal(dry.changed,1);
  assert.equal(await fs.readFile(file,'utf8'),original);
  const applied=await runBatch({root,rules,apply:true});
  assert.equal(applied.changed,1);
  assert.equal(applied.skipped,1);
  assert.equal(await fs.readFile(file,'utf8'),'[00:01.00]ถูก\n[00:02.00]เดิม\n');
  const undone=await undoBatch({root,runId:applied.runId});
  assert.equal(undone.restored,1);
  assert.equal(await fs.readFile(file,'utf8'),original);
  const again=await runBatch({root,rules,apply:true});
  await fs.writeFile(file,'[00:01.00]manual change\n');
  const conflict=await undoBatch({root,runId:again.runId});
  assert.equal(conflict.conflicts,1);
  assert.equal(await fs.readFile(file,'utf8'),'[00:01.00]manual change\n');
 } finally {await fs.rm(root,{recursive:true,force:true});}
});
test('unsupported NCN LYR CUR and unrelated JSON remain untouched',async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'xstage-ncn-'));
 try {
  for(const f of ['001.lyr','001.cur','001.json']) await fs.writeFile(path.join(root,f),'raw');
  const result=await runBatch({root,rules:[{from:'raw',to:'bad'}],apply:true});
  assert.equal(result.skipped,3);
  for(const f of ['001.lyr','001.cur','001.json']) assert.equal(await fs.readFile(path.join(root,f),'utf8'),'raw');
 } finally {await fs.rm(root,{recursive:true,force:true});}
});
