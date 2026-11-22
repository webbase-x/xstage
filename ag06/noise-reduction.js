// X-Stage Audio Studio: original offline spectral noise attenuation.
// Hann-window STFT + overlap-add, estimated quiet-frame noise floor.
// No external model, cloud upload, Yamaha/Steinberg code or plugins.
const N=512,HOP=256;
export function fft(real,imag,inverse=false){
 const n=real.length;if(n!==imag.length||(n&(n-1)))throw new Error("FFT ต้องมีขนาดยกกำลังสอง");
 for(let i=1,j=0;i<n;i++){
  let bit=n>>1;for(;j&bit;bit>>=1)j^=bit;j^=bit;
  if(i<j){[real[i],real[j]]=[real[j],real[i]];[imag[i],imag[j]]=[imag[j],imag[i]];}
 }
 for(let size=2;size<=n;size<<=1){
  const angle=(inverse?2:-2)*Math.PI/size;
  const stepR=Math.cos(angle),stepI=Math.sin(angle);
  for(let i=0;i<n;i+=size){
   let wr=1,wi=0;
   for(let j=0;j<size/2;j++){
    const a=i+j,b=a+size/2,r=wr*real[b]-wi*imag[b],v=wr*imag[b]+wi*real[b];
    real[b]=real[a]-r;imag[b]=imag[a]-v;real[a]+=r;imag[a]+=v;
    const next=wr*stepR-wi*stepI;wi=wr*stepI+wi*stepR;wr=next;
   }
  }
 }
 if(inverse)for(let i=0;i<n;i++){real[i]/=n;imag[i]/=n;}
}
const window=Float32Array.from({length:N},(_,i)=>.5-.5*Math.cos(2*Math.PI*i/(N-1)));
function frameSpectrum(samples,offset){
 const re=new Float32Array(N),im=new Float32Array(N);let energy=0;
 for(let i=0;i<N;i++){
  const value=samples[offset+i]||0;energy+=value*value;re[i]=value*window[i];
 }
 fft(re,im);
 return {re,im,energy:energy/N};
}
export function reduceSpectralNoise(samples,sampleRate,amount=.8){
 if(!(samples instanceof Float32Array)||!Number.isFinite(sampleRate)||sampleRate<8000)throw new Error("ข้อมูลเสียงไม่ถูกต้อง");
 if(samples.length>sampleRate*60)throw new Error("Spectral Reduction จำกัดแทร็กเสียงไม่เกิน 60 วินาที");
 const output=new Float32Array(samples.length);
 if(samples.length<N)return new Float32Array(samples);
 // Estimate noise from the quietest windows throughout the clip; assumes some noise-only sections.
 const candidates=[],positions=Math.min(100,Math.max(1,Math.floor(samples.length/N)));
 for(let i=0;i<positions;i++){
  const offset=Math.min(samples.length-N,Math.floor(i/Math.max(1,positions-1)*(samples.length-N)));
  const frame=frameSpectrum(samples,offset);
  candidates.push({frame,offset});
 }
 candidates.sort((a,b)=>a.frame.energy-b.frame.energy);
 // Without quiet reference material do not infer noise from continuous foreground audio.
 if(candidates[0].frame.energy>0.0025)return new Float32Array(samples);
 const selected=candidates.slice(0,Math.max(1,Math.min(12,Math.ceil(candidates.length*.12))));
 const floor=new Float32Array(N/2+1);
 for(const item of selected){const {re,im}=item.frame;for(let k=0;k<floor.length;k++)floor[k]+=Math.hypot(re[k],im[k])/selected.length;}
 const weights=new Float32Array(samples.length),lastMask=new Float32Array(N/2+1).fill(1);
 for(let offset=-HOP;offset<samples.length;offset+=HOP){
  const re=new Float32Array(N),im=new Float32Array(N);
  for(let i=0;i<N;i++){const idx=offset+i;if(idx>=0&&idx<samples.length)re[i]=samples[idx]*window[i];}
  fft(re,im);
  for(let k=0;k<=N/2;k++){
   const amplitude=Math.hypot(re[k],im[k]);
   const target=Math.max(.12,Math.min(1,1-(Math.max(0,Math.min(1.5,amount))*floor[k])/(amplitude+1e-7)));
   const gain=lastMask[k]=.50*lastMask[k]+.50*target;
   re[k]*=gain;im[k]*=gain;
   if(k>0&&k<N/2){re[N-k]*=gain;im[N-k]*=gain;}
  }
  fft(re,im,true);
  for(let i=0;i<N;i++){
   const idx=offset+i;if(idx>=0&&idx<samples.length){
    output[idx]+=re[i]*window[i];weights[idx]+=window[i]*window[i];
   }
  }
 }
 for(let i=0;i<output.length;i++)output[i]=Math.max(-1,Math.min(1,output[i]/Math.max(weights[i],1e-6)));
 return output;
}
