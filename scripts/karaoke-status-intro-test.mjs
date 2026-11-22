import fs from 'node:fs';
import assert from 'node:assert/strict';
const read=p=>fs.readFileSync(new URL('../'+p,import.meta.url),'utf8');
const app=read('app.js'),html=read('karaoke.html'),stageUI=read('stage-ui.js'),css=read('xstage-ux.css');
const ver=JSON.parse(read('version.json'));
assert.equal(ver.build,1141);
assert.ok(html.includes('xstage-ux.css?v=1164-mobile-controls-lights'));
assert.ok(html.includes('stage-ui.js?v=1164-bottom-menu'));
assert.ok(html.includes('app.js?v=1174-auto-migrate-mid'));
const titleRow=html.indexOf('class="transport-song-title"');
const name=html.indexOf('id="now-playing"',titleRow);
const key=html.indexOf('id="toolbar-song-key"',titleRow);
assert.ok(titleRow>=0&&name>titleRow&&key>name&&key<name+500,
  'The key belongs immediately after the title in the Song Status row');
assert.ok(stageUI.includes("if(stack.parentNode!==titleRow)titleRow.append(stack)"));
assert.ok(app.includes('state.preparingSong=song'));
assert.ok(app.includes('state.loading?state.preparingSong:state.current'));
assert.ok(app.includes('if(idx<0){'));
assert.ok(css.includes('env(safe-area-inset-top,0px)'));
assert.ok(css.includes('.search-dock.pc-expanded{')&&css.includes('position:fixed!important'));
assert.ok(css.includes('grid-template-columns:56px minmax(0,1fr)'));
const start=app.indexOf('function transposeSongKey('),end=app.indexOf('function setSongKeyDisplay(',start);
const fn=new Function(app.slice(start,end)+';return transposeSongKey;')();
assert.equal(fn('C',0),'C');
assert.equal(fn('C',2),'D');
assert.equal(fn('B♭',2),'C');
assert.equal(fn('Am',3),'Cm');
assert.equal(fn('F♯',-1),'F');
assert.equal(fn('unknown',2),'unknown');
const drawStart=app.indexOf('function drawLyrics(){'),drawEnd=app.indexOf('let lyricsFrame=0;',drawStart);
assert.ok(drawStart>=0&&drawEnd>drawStart);
const painted=[];
const song={title:'ทดสอบเพลง',artist:'ทดสอบศิลปิน',code:'100'};
const state={loading:true,preparingSong:song,current:{title:'เพลงก่อน'},lyrics:{lines:[{startTime:0,text:'เนื้อเพลงเดิม'}]},visualScale:1};
const player={currentTime:0,paused:true,ended:false};
const ui={stage:{querySelector:()=>null,classList:{contains:()=>false}},lyrics:{getBoundingClientRect:()=>({width:380,height:670})}};
const pen={clearRect(){}};
const paint=new Function('ui','state','player','window','document','pen','resizeCanvas','drawLine','lineProgress','matchMedia','scheduleLyricsDraw',
 app.slice(drawStart,drawEnd)+';return drawLyrics;')(
 ui,state,player,{devicePixelRatio:1},{body:{classList:{contains:()=>false}}},pen,()=>({w:380,h:670}),
 (...args)=>painted.push(args[0]),()=>0,()=>({matches:false}),()=>{});
paint();
assert.deepEqual(painted,[song.title,song.artist],'Song selection paints title/artist, not previous lyrics');
painted.length=0;
state.loading=false;state.current=song;state.lyrics={lines:[
 {startTime:12,endTime:18,text:'เริ่มร้อง',syllables:[]},
 {startTime:19,endTime:25,text:'บรรทัดต่อไป',syllables:[]}]};
paint();
assert.deepEqual(painted,[song.title,song.artist],'Instrumental intro keeps title and artist');
painted.length=0;player.currentTime=14;pen.measureText=()=>({width:100});
paint();
assert.deepEqual(painted,['เริ่มร้อง','บรรทัดต่อไป'],'Timed lyrics replace intro without overlap');
console.log('PASS: inline transposed key, stage title/artist intro, safe-area full-width mobile search');
