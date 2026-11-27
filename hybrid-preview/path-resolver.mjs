/* Resolve only canonical XMID paths under the currently verified library.
 * PC-local rows lack a trusted original hash: mapping is a preview until
 * package validation and explicit identity policy have been implemented. */
const folderMime='application/vnd.google-apps.folder';
const safeId=id=>typeof id==='string'&&/^[A-Za-z0-9_-]+$/.test(id);
const escapeQ=s=>String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
export function portableXmidPath(raw){
  const path=String(raw||'').replace(/\\/g,'/');
  // The PC producer may emit either a portable path or a Windows absolute
  // path with an XMID directory. Never allow traversal or extra components.
  if(path.split('/').some(p=>p==='.'||p==='..'||!p)||/[\u0000-\u001f]/.test(path))throw Error('Unsafe XMID path');
  const match=/(?:^|\/)xmid\/([0-9]+)\/([0-9A-Za-z_-]+\.xmid)$/i.exec(path);
  if(!match)throw Error('Unsupported XMID path');
  return ['SONGS','MIDI','XMID',match[1],match[2].toLowerCase()];
}
export function createPathResolver({rootId,list,current=()=>true,retiredRoots=[]}){
  if(!safeId(rootId)||retiredRoots.includes(rootId)||typeof list!=='function')throw Error('Invalid selected library');
  const folders=new Map();
  const assertCurrent=()=>{if(!current())throw new DOMException('Library changed','AbortError');};
  async function exact(parent,name,folder){
    assertCurrent();
    const query="'"+escapeQ(parent)+"' in parents and name='"+escapeQ(name)+"' and trashed=false"+(folder?" and mimeType='"+folderMime+"'":"");
    const files=await list(query);assertCurrent();
    if(!Array.isArray(files))throw Error('Invalid Drive listing');
    const candidates=files.filter(f=>f.name===name&&Array.isArray(f.parents)&&f.parents.includes(parent)&&
      f.trashed!==true&&(folder?f.mimeType===folderMime:f.mimeType!==folderMime));
    if(candidates.length!==1)throw Error(candidates.length?'Duplicate Drive path':'Drive path not found or not authorized');
    if(!safeId(candidates[0].id))throw Error('Invalid Drive file identity');
    return candidates[0];
  }
  return async function resolve(raw){
    const parts=portableXmidPath(raw);let parent=rootId;
    for(const name of parts.slice(0,-1)){
      const key=parent+'/'+name;let id=folders.get(key);
      if(!id){id=(await exact(parent,name,true)).id;if(folders.size>=128)folders.clear();folders.set(key,id);}
      assertCurrent();parent=id;
    }
    const file=await exact(parent,parts.at(-1),false);
    const size=Number(file.size),md5=String(file.md5Checksum||'').toLowerCase();
    if(!Number.isSafeInteger(size)||size<1||!/^[a-f0-9]{32}$/.test(md5))throw Error('Drive metadata has no valid size or MD5');
    return {fileId:file.id,path:parts.join('/'),size,md5Checksum:md5,identityVerified:false};
  };
}
