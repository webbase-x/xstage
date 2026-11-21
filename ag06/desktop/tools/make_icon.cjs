"use strict";
// Generate a deterministic X-Stage AG06 icon with only Node.js built-ins.
const fs=require("node:fs");
const path=require("node:path");
const zlib=require("node:zlib");
function crc32(bytes){
  let c=0xffffffff;
  for(const value of bytes){
    c^=value;
    for(let j=0;j<8;j++)c=(c>>>1)^((c&1)?0xedb88320:0);
  }
  return (c^0xffffffff)>>>0;
}
function chunk(type,data){
  const name=Buffer.from(type,"ascii"),length=Buffer.alloc(4),crc=Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  crc.writeUInt32BE(crc32(Buffer.concat([name,data])));
  return Buffer.concat([length,name,data,crc]);
}
function colorAt(x,y,size){
  const u=(x+.5)/size,v=(y+.5)/size;
  const radius=.19;
  const px=Math.max(Math.abs(u-.5)-(.5-radius),0);
  const py=Math.max(Math.abs(v-.5)-(.5-radius),0);
  if(px*px+py*py>radius*radius)return [0,0,0,0];
  let col=[17,26,43,255];
  if(u>.13&&u<.87&&v>.13&&v<.87)col=[31,44,66,255];
  const xs=[.25,.416,.583,.75],stops=[.53,.36,.65,.44];
  for(let i=0;i<4;i++){
    if(Math.abs(u-xs[i])<.018&&v>.22&&v<.79)col=[72,97,123,255];
    if(Math.abs(u-xs[i])<.055&&Math.abs(v-stops[i])<.065)col=[84,235,197,255];
  }
  return col;
}
function png(size){
  const rowBytes=size*4+1,raw=Buffer.alloc(rowBytes*size);
  for(let y=0;y<size;y++){
    const offset=y*rowBytes;
    raw[offset]=0;
    for(let x=0;x<size;x++){
      const c=colorAt(x,y,size);
      for(let k=0;k<4;k++)raw[offset+1+x*4+k]=c[k];
    }
  }
  const ihdr=Buffer.alloc(13);
  ihdr.writeUInt32BE(size,0);ihdr.writeUInt32BE(size,4);ihdr[8]=8;ihdr[9]=6;
  return Buffer.concat([
    Buffer.from([137,80,78,71,13,10,26,10]),
    chunk("IHDR",ihdr),chunk("IDAT",zlib.deflateSync(raw,{level:9})),chunk("IEND",Buffer.alloc(0))
  ]);
}
const sizes=[16,32,48,256],images=sizes.map(png);
const head=Buffer.alloc(6+16*images.length);head.writeUInt16LE(1,2);head.writeUInt16LE(images.length,4);
let offset=head.length;
images.forEach((data,i)=>{
  const pos=6+i*16,size=sizes[i];
  head[pos]=size===256?0:size;head[pos+1]=size===256?0:size;
  head[pos+2]=0;head[pos+3]=0;
  head.writeUInt16LE(1,pos+4);head.writeUInt16LE(32,pos+6);
  head.writeUInt32LE(data.length,pos+8);head.writeUInt32LE(offset,pos+12);
  offset+=data.length;
});
const target=path.join(__dirname,"..","icon.ico");
fs.writeFileSync(target,Buffer.concat([head,...images]));
console.log("Generated Windows icon:",target);
