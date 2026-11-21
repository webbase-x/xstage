import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync(new URL('../ios-midi-audio.js',import.meta.url),'utf8');
function setup({ios=true,allowPlay=true,bridge=true}={}){
  const calls=[];
  let audio=null;
  const navigator={userAgent:ios?'Mozilla/5.0 (iPhone; CPU iPhone OS 27_2)':'Mozilla/5.0 (Windows NT 10.0)',
    maxTouchPoints:ios?5:0,audioSession:{type:'auto'}};
  const document={
    body:{appendChild(element){calls.push('append');audio=element}},
    createElement(tag){
      assert.equal(tag,'audio');
      return {
        paused:true,srcObject:null,style:{},setAttribute(){},
        play(){calls.push('play');if(!allowPlay)return Promise.reject(Error('NotAllowedError'));
          this.paused=false;return Promise.resolve();},
        pause(){calls.push('pause');this.paused=true},
        remove(){calls.push('remove')}
      };
    }
  };
  const ctx={
    destination:{destination:true},
    createMediaStreamDestination:bridge?()=>({stream:{getAudioTracks:()=>[{}]},disconnect(){calls.push('destination-disconnect')}}):undefined
  };
  const sourceNode={
    connect(dest){calls.push(dest===ctx.destination?'connect-direct':'connect-stream')},
    disconnect(dest){calls.push(dest===ctx.destination?'disconnect-direct':'disconnect-stream')}
  };
  const scope={navigator,document};
  vm.runInNewContext(source,{window:scope,console,Promise});
  return {ios:scope.XStageIOSMidiAudio,navigator,ctx,sourceNode,calls,get audio(){return audio}};
}
{
  const fake=setup();
  assert.equal(fake.ios.isIOS,true);
  assert.equal(fake.ios.activate(),true);
  assert.equal(fake.navigator.audioSession.type,'playback');
  const out=fake.ios.attach(fake.ctx,fake.sourceNode);
  assert.equal(out.mode,'ios-media');
  assert.deepEqual(fake.calls,['append','connect-stream']);
  assert.equal(await out.start(),true);
  assert.equal(fake.calls.includes('connect-direct'),false,'Do not double output audio');
  out.pause();
  assert.equal(fake.audio.paused,true);
  out.dispose();
  fake.ios.release();
  assert.equal(fake.audio.srcObject,null);
  assert.ok(fake.calls.includes('disconnect-stream'));
}
{
  const fake=setup();
  // The iPhone tap must prime exactly one media element BEFORE the async
  // song/SoundFont download. Attaching the synth later must reuse it.
  await fake.ios.prime(fake.ctx);
  assert.equal(fake.navigator.audioSession.type,'playback');
  const before=fake.calls.filter(x=>x==='append').length;
  const out=fake.ios.attach(fake.ctx,fake.sourceNode);
  await out.start();
  assert.equal(fake.calls.filter(x=>x==='append').length,before,
    'The primed iPhone media output must be reused for MIDI playback');
  assert.equal(fake.calls.filter(x=>x==='connect-direct').length,0,
    'Successful media relay must not double the audio output');
  out.dispose();
  fake.ios.release();
  assert.equal(fake.audio.srcObject,null,'iPhone media track must be released on stop');
}
{
  const fake=setup({allowPlay:false});
  const out=fake.ios.attach(fake.ctx,fake.sourceNode);
  assert.equal(await out.start(),true,'Autoplay failure should not silence the app');
  assert.equal(out.mode,'ios-media');
  assert.equal(fake.calls.filter(x=>x==='connect-direct').length,1);
  assert.equal(fake.calls.filter(x=>x==='disconnect-stream').length,1);
  out.dispose();
  assert.equal(fake.calls.filter(x=>x==='disconnect-direct').length,1);
}
{
  const fake=setup({ios:false});
  const out=fake.ios.attach(fake.ctx,fake.sourceNode);
  assert.equal(out.mode,'direct');
  assert.deepEqual(fake.calls,['connect-direct']);
  out.dispose();
  assert.ok(fake.calls.includes('disconnect-direct'));
}
{
  const fake=setup({bridge:false});
  const out=fake.ios.attach(fake.ctx,fake.sourceNode);
  assert.equal(out.mode,'direct');
  out.dispose();
}
console.log('PASS: iPhone audio session, MediaStream output, single route, autoplay fallback, desktop isolation');
