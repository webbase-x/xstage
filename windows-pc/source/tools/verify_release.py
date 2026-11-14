"""Release metadata/environment gate and listed distribution file hash manifest."""
import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import re
import sys


def check_source(home):
    home = Path(home)
    tree = ast.parse((home/'karaoke/__init__.py').read_text(encoding='utf-8'))
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='__version__' for t in node.targets))
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('Invalid semantic release version')
    parts=tuple(int(x) for x in version.split('.'))+(0,)
    info=(home/'version_info.txt').read_text(encoding='utf-8')
    for key in ('filevers','prodvers'):
        match=re.search(key+r'=\(([^)]+)\)',info)
        if not match or tuple(int(x.strip()) for x in match.group(1).split(','))!=parts:
            raise ValueError('EXE/source version mismatch: '+key)
    for key,expected in (('FileVersion',version+'.0'),('ProductVersion',version)):
        match=re.search(r"StringStruct\('"+key+r"', '([^']+)'\)",info)
        if not match or match.group(1)!=expected:raise ValueError('Version mismatch: '+key)
    return version


def check_environment(home):
    if sys.version_info[:2]!=(3,13):raise ValueError('Locked release requires CPython 3.13')
    result={}
    for line in (Path(home)/'requirements-build.lock.txt').read_text(encoding='utf-8').splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        name,expected=line.split('==',1)
        actual=importlib.metadata.version(name)
        if actual!=expected:raise ValueError(f'Build dependency mismatch: {name}: {actual} != {expected}')
        result[name]=actual
    return result


def file_hash(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def make_manifest(package, version):
    package=Path(package)
    files={}
    for path in sorted(package.rglob('*')):
        if path.is_symlink():raise ValueError('Symlink in release package')
        if not path.is_file() or '__pycache__' in path.parts or path.name=='release-manifest.json':continue
        files[path.relative_to(package).as_posix()]=file_hash(path)
    return {'version':version,'algorithm':'sha256','files':files}


def unique_pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate manifest key: '+key)
        result[key]=value
    return result


def verify_manifest(package):
    package=Path(package).resolve()
    manifest=json.loads((package/'release-manifest.json').read_text(encoding='utf-8'),object_pairs_hook=unique_pairs)
    if not isinstance(manifest,dict) or manifest.get('algorithm')!='sha256':
        raise ValueError('Invalid manifest algorithm or root')
    version=manifest.get('version')
    if not isinstance(version,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):
        raise ValueError('Invalid release version')
    files=manifest.get('files')
    if not isinstance(files,dict) or 'XStageKaraoke.exe' not in files:
        raise ValueError('Manifest must include the main executable')
    seen=set()
    for name,expected in files.items():
        if not isinstance(name,str) or not name or any(char in name for char in ('\\',':','\x00')):
            raise ValueError('Invalid manifest path')
        relative=PurePosixPath(name)
        if relative.is_absolute() or relative.as_posix()!=name or any(p in ('.','..') for p in relative.parts):
            raise ValueError('Unsafe manifest path: '+name)
        if name.casefold() in seen:raise ValueError('Duplicate Windows path: '+name)
        seen.add(name.casefold())
        if not isinstance(expected,str) or not re.fullmatch(r'[0-9a-f]{64}',expected):
            raise ValueError('Invalid SHA256: '+name)
        path=package.joinpath(*relative.parts)
        for component in (path,*path.parents):
            if component==package:break
            if component.is_symlink() or getattr(component,'is_junction',lambda: False)():raise ValueError('Link in release path: '+name)
        resolved=path.resolve()
        if not resolved.is_relative_to(package) or not path.is_file() or file_hash(path)!=expected:
            raise ValueError('Release file missing or modified: '+name)
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--home',type=Path)
    parser.add_argument('--package',type=Path)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.verify:
        report=verify_manifest(args.package)
    else:
        version=check_source(args.home)
        dependencies=check_environment(args.home)
        report={'version':version,'python':sys.version,'dependencies':dependencies}
        (args.home/'release-environment.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if args.package:
            report=make_manifest(args.package,version)
            (args.package/'release-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Release gate passed:',report['version'])

if __name__=='__main__':main()
