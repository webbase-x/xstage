/* Deterministic self-hosted MIDI runtime asset builder.
 * Called by CI/build only: never downloads at user playback time. */
import {existsSync,mkdirSync,copyFileSync,readFileSync,writeFileSync,statSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
const root=process.cwd();
const vendor=join(root,'assets','vendor');
mkdirSync(vendor,{recursive:true});
const pkg=JSON.parse(readFileSync('node_modules/spessasynth_lib/package.json','utf8'));
if(pkg.version!=='4.4.8')throw Error('Pinned SpessaSynth version mismatch: '+pkg.version);
const worklet='node_modules/spessasynth_lib/dist/spessasynth_processor.min.js';
if(!existsSync(worklet))throw Error('SpessaSynth worklet missing in installed package');
const esbuild=process.platform==='win32'?'node_modules/.bin/esbuild.cmd':'node_modules/.bin/esbuild';
execFileSync(esbuild,['assets/midi/spessasynth-entry.js',
  '--bundle','--format=esm','--platform=browser','--target=es2020','--minify',
  '--outfile=assets/vendor/spessasynth-lib.min.js'],{stdio:'inherit'});
const outWorklet=join(vendor,'spessasynth_processor.min.js');
copyFileSync(worklet,outWorklet);
const output=join(vendor,'spessasynth-lib.min.js');
for(const p of [output,outWorklet]){
 if(statSync(p).size<3000)throw Error('Incomplete MIDI runtime bundle: '+p);
}
const fontPath=join(vendor,'FluidR3Mono_GM.sf3');
const EXPECTED_SHA='cfcd66d89e8386823400eca64934b14fbea7bf48ba1f00d21189af1262794ec2';
if(!existsSync(fontPath))throw Error('Bundled FluidR3Mono GM sound bank missing');
const font=readFileSync(fontPath);
if(createHash('sha256').update(font).digest('hex')!==EXPECTED_SHA)
 throw Error('Bundled FluidR3Mono GM SHA256 mismatch');
if(font.toString('ascii',0,4)!=='RIFF'||font.toString('ascii',8,12)!=='sfbk')
 throw Error('SoundFont has invalid RIFF sfbk header');
const files=[output,outWorklet,fontPath].map(path=>({
 path:path.replace(root+'/',''),
 size:statSync(path).size,
 sha256:createHash('sha256').update(readFileSync(path)).digest('hex')
}));
writeFileSync(join(vendor,'midi-assets.json'),JSON.stringify({
 schemaVersion:1,dependency:{name:pkg.name,version:pkg.version,license:'Apache-2.0'},
 soundFont:{name:'FluidR3Mono_GM',license:'MIT',source:'musescore/MuseScore v2.3.2'},
 files
},null,2)+'\n');
console.log('MIDI assets built, pinned and verified:',files.map(x=>x.path).join(', '));
