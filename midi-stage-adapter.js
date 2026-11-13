/* Audio/MIDI transport facade: stable HTML media events for stage lyric rendering.
 * Audio remains a native HTMLMediaElement; MIDI is a separate WebAudio source. */
(function(global){
'use strict';
global.XStageCreatePlayerAdapter=function(audio){
  const midi=()=>global.XStageMidiEngine;
  const methods={
    play:()=>midi()?.active?midi().play():audio.play(),
    pause:()=>midi()?.active?midi().pause():audio.pause(),
    load:()=>midi()?.active?undefined:audio.load(),
    removeAttribute:(name)=>{
      if(name==='src'&&midi()?.active)midi().stop();
      return audio.removeAttribute(name);
    }
  };
  const attrs=['currentTime','duration','paused','ended','loop','playbackRate','volume'];
  return new Proxy(audio,{
    get(target,prop){
      const m=midi();
      if(Object.hasOwn(methods,prop))return methods[prop];
      if(prop==='src'&&m?.active)return 'midi://xstage-current';
      if(prop==='readyState'&&m?.active)return 4;
      if(attrs.includes(prop)&&m?.active)return m[prop];
      const val=Reflect.get(target,prop,target);
      return typeof val==='function'?val.bind(target):val;
    },
    set(target,prop,value){
      const m=midi();
      if(attrs.includes(prop)&&m?.active){m[prop]=value;return true;}
      return Reflect.set(target,prop,value,target);
    }
  });
};
})(window);