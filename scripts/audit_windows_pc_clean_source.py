#!/usr/bin/env python3
"""Windows-only online-integration inventory. Does not edit Web/Android/Song Studio."""
from pathlib import Path
import ast,re
base=Path(__file__).resolve().parents[1]/'windows-pc'/'source'
for file in sorted((base/'karaoke').glob('*.py')):
  lines=file.read_text(encoding='utf-8-sig').splitlines()
  hits=[]
  for i,line in enumerate(lines,1):
    if re.search(r'(?i)(online|cloud|google[_ ]account|google[_ ]drive|web[_ ]asset|web[_ ]sync|web[_ ]drive|web[_ ]environment|web[_ ]resume|webbase-x.github.io/xstage)',line):
      hits.append((i,line.strip()[:165]))
  if hits:
    print(file.name, 'references',len(hits))
    for n,s in hits[:25]: print(f'  {n} {s}')
print('Core UI menus:',[(p.name,p.read_text(encoding='utf-8-sig').count('Karaoke Online')) for p in [base/'karaoke/ui.py',base/'karaoke/classic.py',base/'karaoke/context_menu.py']])
for f in (base/'karaoke/ui.py',base/'karaoke/classic.py',base/'karaoke/performer.py'):
  ast.parse(f.read_text(encoding='utf-8-sig'),filename=str(f))
print('Windows PC UI AST parse passed')
