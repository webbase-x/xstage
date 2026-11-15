"""Compare cold, unchanged, mixed and full imports with disposable demo files."""
from pathlib import Path
import argparse,json,platform,sys,tempfile,time
from unittest.mock import patch
HOME=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HOME))
from karaoke import __version__
from karaoke.library import SongLibrary
from karaoke.lister import build_list
from karaoke.jobs import JobReporter
from karaoke.ingest import Inspector
import karaoke.incremental as incremental

class Sink:
    def put(self,message):pass

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--songs',type=int,default=500)
    count=parser.parse_args().songs
    if not 10<=count<=10000:parser.error('Use 10..10000 demo copies')
    sample=next((HOME/'samples').glob('*.mid')).read_bytes()
    with tempfile.TemporaryDirectory(prefix='xstage-incremental-') as temp:
        root=Path(temp);old=root/'old';new=root/'new';old.mkdir();new.mkdir()
        for i in range(count):(old/f'{i:06} - Demo Song - Demo Artist.mid').write_bytes(sample)
        library=SongLibrary(root/'data/songs.db');results=[]
        def run(name,folders,force=False):
            report=JobReporter(Sink(),root/'logs');real_hash=incremental.content_key;real_inspect=Inspector.inspect
            def inspect(instance,path):return real_inspect(instance,path)
            start=time.perf_counter()
            with patch('karaoke.incremental.content_key',wraps=real_hash) as hashes, \
                 patch.object(Inspector,'inspect',autospec=True,side_effect=inspect) as parses:
                build_list(library,[{'path':str(p),'type':'ทุกประเภท'} for p in folders],force=force,events=report.event)
            report.finish()
            result=dict(stage=name,seconds=round(time.perf_counter()-start,4),
                        content_hash_calls=hashes.call_count,metadata_parse_calls=parses.call_count,
                        target=report.state['target'],processed=report.state['processed'],visible=library.count())
            for key in ('unchanged','added','updated','duplicates','failed'):result[key]=report.state.get(key,0)
            results.append(result)
        run('cold_import',[old]);run('unchanged_import',[old])
        assert results[-1]['content_hash_calls']==results[-1]['metadata_parse_calls']==0
        assert results[-1]['unchanged']==count
        extra=max(10,count//5);unique=max(1,extra//10)
        for i in range(extra):
            padding=b'\0'*(i+1) if i<unique else b''
            (new/f'{count+i:06} - New Demo Song - Demo Artist.mid').write_bytes(sample+padding)
        run('old_plus_new_and_duplicates',[old,new])
        assert results[-1]['unchanged']==count and results[-1]['added']==unique
        assert results[-1]['duplicates']==extra-unique and results[-1]['metadata_parse_calls']==unique
        run('full_verification',[old,new],force=True)
        output=dict(release=__version__,platform=platform.platform(),synthetic=True,old_files=count,new_files=extra,new_unique=unique,
            results=results,caveat='Small disposable demo MIDI files; no GUI/audio. Timings do not predict real Windows or network-drive performance.')
        (HOME/'INCREMENTAL_BENCHMARK.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
        print(json.dumps(output,ensure_ascii=False))

if __name__=='__main__':main()
