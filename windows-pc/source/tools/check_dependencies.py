from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from karaoke.dependency_check import run
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--home',type=Path,required=True)
    parser.add_argument('--report',type=Path)
    args=parser.parse_args();raise SystemExit(run(args.home,args.report))
