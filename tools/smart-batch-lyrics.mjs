#!/usr/bin/env node
/**
 * X-Stage Smart Batch Lyrics Correction (safe LRC engine).
 * Default mode is a dry-run. It never edits audio, MIDI, CUR or LYR.
 * Node >=20; no external dependencies or network access.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash, randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const MAX_BYTES = 4 * 1024 * 1024;
const TIME_TAG = /\[(\d{1,3}):([0-5]\d)(?:\.(\d{1,3}))?\]/g;
const META = /^\[(?:ar|ti|al|by|offset|re|ve|length):/i;
const VALID_NAME = /^[a-zA-Z0-9_-]{8,80}$/;

function parseLrc(text) {
  const lines = text.split(/(\r\n|\n|\r)/);
  let timed = 0, previous = -1;
  for (let i = 0; i < lines.length; i += 2) {
    const line = lines[i];
    if (!line.trim() || META.test(line)) continue;
    const tags = [...line.matchAll(TIME_TAG)];
    if (!tags.length) return {ok:false, reason:'unrecognized-line', line:i/2+1};
    const prefix = tags.map(t=>t[0]).join('');
    if (!line.startsWith(prefix)) return {ok:false,reason:'mixed-timing',line:i/2+1};
    const content = line.slice(prefix.length);
    if (/\[\d{1,3}:\d/.test(content)) return {ok:false,reason:'embedded-timestamp',line:i/2+1};
    for (const t of tags) {
      const ms = (Number(t[1])*60+Number(t[2]))*1000 + Number((t[3]||'').padEnd(3,'0'));
      if (ms < previous) return {ok:false,reason:'backward-timing',line:i/2+1};
      previous = ms; timed++;
    }
  }
  return timed ? {ok:true,timed} : {ok:false,reason:'no-timestamps'};
}

function tags(text) {return [...text.matchAll(TIME_TAG)].map(m=>m[0]);}
export function correctLrc(text, rules) {
  const validation = parseLrc(text);
  if (!validation.ok) return {status:'skipped',reason:validation.reason};
  const parts = text.split(/(\r\n|\n|\r)/);
  let replacements = 0;
  for (let i=0;i<parts.length;i+=2) {
    const original=parts[i];
    if (!original || META.test(original)) continue;
    const matches=[...original.matchAll(TIME_TAG)];
    if (!matches.length) continue;
    const prefix=matches.map(m=>m[0]).join('');
    let lyric=original.slice(prefix.length);
    for (const rule of rules) {
      if (!rule.from || rule.from===rule.to) continue;
      // Literal, case-sensitive replacements, applied only to lyric payloads.
      const pieces=lyric.split(rule.from);
      if (pieces.length>1) {
        replacements+=pieces.length-1;
        lyric=pieces.join(rule.to);
      }
    }
    parts[i]=prefix+lyric;
  }
  const result=parts.join('');
  if (tags(result).join('\0')!==tags(text).join('\0')) return {status:'skipped',reason:'timestamp-change'};
  const after=parseLrc(result);
  if (!after.ok || after.timed!==validation.timed) return {status:'skipped',reason:'invalid-after'};
  return {status:result===text?'unchanged':'changed',text:result,replacements,timed:validation.timed};
}
export function validateRules(value) {
  if (!Array.isArray(value) || !value.length || value.length>1000) throw Error('rules must be a nonempty array (max 1000)');
  for (const r of value) {
    if (!r || typeof r.from!=='string' || typeof r.to!=='string' || !r.from || r.from.length>300 || r.to.length>300 ||
        /[\r\n\[\]]/.test(r.from+r.to)) throw Error('unsafe rule: timestamps, line breaks and brackets are not allowed');
  }
  return value;
}
async function* discover(root) {
  const stack=[root];
  while(stack.length) {
    const dir=stack.pop();
    for (const e of await fs.readdir(dir,{withFileTypes:true})) {
      const full=path.join(dir,e.name);
      if (e.isSymbolicLink() || e.name==='.xstage-lyrics-backup') continue;
      if (e.isDirectory()) stack.push(full);
      else if(e.isFile() && /\.(lrc|lyr|cur|json)$/i.test(e.name)) yield full;
    }
  }
}
async function putAtomic(dest,bytes) {
  const temp=dest+'.xstage-tmp-'+randomUUID();
  try {
    await fs.writeFile(temp,bytes,{flag:'wx',mode:0o600});
    await fs.rename(temp,dest);
  } finally {await fs.rm(temp,{force:true}).catch(()=>{});}
}
async function safeRead(file) {
  const stat=await fs.lstat(file);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size>MAX_BYTES) throw Error('oversize-or-unsafe-file');
  const bytes=await fs.readFile(file);
  const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  if (text.startsWith('\uFEFF')) throw Error('bom-unsupported');
  if (text.includes('\0')) throw Error('binary-content');
  return {bytes,text,stat};
}
function within(root,p) {
  const relative=path.relative(root,p);
  return relative && relative!=='.' && !relative.startsWith('..'+path.sep) && !path.isAbsolute(relative);
}
export async function runBatch({root,rules,apply=false,progress=()=>{}}) {
  root=await fs.realpath(root);
  validateRules(rules);
  const backupDir=path.join(root,'.xstage-lyrics-backup');
  const runId=new Date().toISOString().replace(/[:.]/g,'-')+'-'+randomUUID();
  const stats={scanned:0,changed:0,unchanged:0,skipped:0,errors:0,replacements:0,runId:apply?runId:null,details:[]};
  let log=[];
  for await (const file of discover(root)) {
    stats.scanned++;
    const relative=path.relative(root,file);
    if (!within(root,file)) continue;
    const ext=path.extname(file).toLowerCase();
    if (ext!=='.lrc') {
      stats.skipped++; // NCN LYR/CUR and other JSON require format-specific validators.
      continue;
    }
    try {
      const {bytes,text,stat}=await safeRead(file);
      const corrected=correctLrc(text,rules);
      if (corrected.status==='skipped') {
        stats.skipped++;
        if(stats.details.length<200) stats.details.push({file:relative,reason:corrected.reason});
      } else if(corrected.status==='unchanged') stats.unchanged++;
      else {
        const replacement=Buffer.from(corrected.text,'utf8');
        const beforeHash=sha(bytes), afterHash=sha(replacement);
        if (apply) {
          const current=await fs.lstat(file);
          if (!current.isFile() || current.isSymbolicLink() || current.size!==stat.size ||
             current.mtimeMs!==stat.mtimeMs || sha(await fs.readFile(file))!==beforeHash) throw Error('file-changed-during-scan');
          const backup=path.join(backupDir,runId,'files',relative);
          await fs.mkdir(path.dirname(backup),{recursive:true});
          await fs.writeFile(backup,bytes,{flag:'wx',mode:0o600});
          if(sha(await fs.readFile(backup))!==beforeHash) throw Error('backup-verification-failed');
          // Write a pending journal entry before replacing the original.
          const entry={file:relative,beforeHash,afterHash,backup:path.relative(root,backup)};
          log.push(entry);
          await fs.mkdir(path.join(backupDir,runId),{recursive:true});
          await putAtomic(path.join(backupDir,runId,'manifest.json'),Buffer.from(JSON.stringify({version:1,runId,entries:log},null,2)));
          await putAtomic(file,replacement);
          if(sha(await fs.readFile(file))!==afterHash) throw Error('postwrite-hash-mismatch');
        }
        stats.changed++; stats.replacements+=corrected.replacements;
      }
    } catch (error) {
      stats.errors++;
      if (stats.details.length<200) stats.details.push({file:relative,reason:String(error.message||error)});
    }
    if(stats.scanned%100===0) progress({...stats,details:undefined});
  }
  return stats;
}
export async function undoBatch({root,runId}) {
  root=await fs.realpath(root);
  if(!VALID_NAME.test(runId)) throw Error('invalid run ID');
  const base=path.join(root,'.xstage-lyrics-backup',runId);
  const manifest=JSON.parse(await fs.readFile(path.join(base,'manifest.json'),'utf8'));
  if(manifest.version!==1 || manifest.runId!==runId || !Array.isArray(manifest.entries)) throw Error('invalid journal');
  const summary={restored:0,conflicts:0};
  for (const e of [...manifest.entries].reverse()) {
    const original=path.resolve(root,e.file);
    const backup=path.resolve(root,e.backup);
    if(!within(root,original) || !within(base,backup) || !backup.startsWith(base+path.sep)) throw Error('unsafe journal path');
    try {
      const src=await fs.lstat(original);
      const b=await fs.lstat(backup);
      if(!src.isFile() || src.isSymbolicLink() || !b.isFile() || b.isSymbolicLink()) throw Error('unsafe file');
      const current=await fs.readFile(original), prior=await fs.readFile(backup);
      if(sha(prior)!==e.beforeHash) throw Error('corrupt backup');
      if(sha(current)===e.beforeHash) continue; // already restored
      if(sha(current)!==e.afterHash) throw Error('modified after correction');
      await putAtomic(original,prior);
      if(sha(await fs.readFile(original))!==e.beforeHash) throw Error('restore verification failed');
      summary.restored++;
    } catch { summary.conflicts++; }
  }
  return summary;
}
async function main(argv) {
  const args=Object.fromEntries(argv.filter(a=>a.startsWith('--')&&a.includes('=')).map(a=>a.slice(2).split(/=(.*)/s).slice(0,2)));
  const root=args.root;
  if(!root) throw Error('Usage: --root=FOLDER --rules=rules.json [--apply] OR --root=FOLDER --undo=RUN_ID');
  if(args.undo) {
    console.log(JSON.stringify(await undoBatch({root,runId:args.undo}),null,2));return;
  }
  if(!args.rules) throw Error('missing --rules=rules.json');
  const rules=validateRules(JSON.parse(await fs.readFile(args.rules,'utf8')));
  const result=await runBatch({root,rules,apply:argv.includes('--apply'),progress:s=>console.error('Processed '+s.scanned+' files')});
  console.log(JSON.stringify(result,null,2));
  if(result.errors) process.exitCode=2;
}
if(process.argv[1] && import.meta.url===pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).catch(e=>{console.error(e.message);process.exitCode=1;});
}
