"""Synthetic core benchmark using disposable copies of the packaged demo MIDI."""
from pathlib import Path
import argparse,csv,json,platform,sys,tempfile,time
HOME=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(HOME))
from karaoke.library import SongLibrary
from karaoke.lister import build_list
from karaoke.duplicates import scan
from karaoke.jobs import JobReporter

class Sink:
    def __init__(self):self.packets=0;self.rows=0
    def put(self,item):self.packets+=1;self.rows+=len(item[1].get('rows',[]))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--songs',type=int,default=500)
    args=parser.parse_args()
    if not 1<=args.songs<=50000:parser.error('Use 1..50000 demo files')
    sample=next((HOME/'samples').glob('*.mid')).read_bytes()
    with tempfile.TemporaryDirectory(prefix='xstage-benchmark-') as temp:
        root=Path(temp);songs=root/'songs';songs.mkdir()
        for i in range(args.songs):(songs/f'{i:06}.mid').write_bytes(sample)
        library=SongLibrary(root/'data/songs.db');sink=Sink();reporter=JobReporter(sink,root/'data')
        started=time.perf_counter()
        result=build_list(library,[{'path':str(songs),'type':'ทุกประเภท'}],events=reporter.event)
        index_time=time.perf_counter()-started
        found,errors=scan(library,events=reporter.event);reporter.finish();elapsed=time.perf_counter()-started
        with reporter.log_path.open(encoding='utf-8-sig',newline='') as stream:logged_rows=sum(1 for _ in csv.reader(stream))-1
        stats=dict(platform=platform.platform(),synthetic=True,
            scope='Core indexing + CSV logging + exact duplicate scan; excludes GUI/audio and fixture creation',
            input_files=args.songs,bytes_per_file=len(sample),target=reporter.state['target'],processed=reporter.state['processed'],
            accepted=result[0],visible_songs=library.count(),hidden_duplicates=sum(len(g)-1 for g in found),
            indexing_seconds=round(index_time,3),total_seconds=round(elapsed,3),index_files_per_second=round(args.songs/index_time,1),
            progress_packets=sink.packets,recent_rows_sent=sink.rows,full_csv_rows=logged_rows,errors=len(errors),
            caveat='Tiny identical MIDI copies; does not predict GUI/audio, Windows, network-drive, large-media or user-collection throughput.')
        assert stats['target']==stats['processed']==stats['accepted']==stats['full_csv_rows']==args.songs
        assert stats['visible_songs']==1 and stats['hidden_duplicates']==args.songs-1
        (HOME/'PROGRESS_BENCHMARK.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
        print(json.dumps(stats,ensure_ascii=False))

if __name__=='__main__':main()
