"""Windows GUI/audio integration test. Does not capture microphone input."""
import json
import sys
import tempfile
import tkinter as tk
import io
import base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from karaoke.performer import PlaybackApp
from karaoke import __version__, DISPLAY_NAME
from karaoke.legacy import DEFAULT_LEGACY
from karaoke.library import QueueItem


def run():
    results={'ok':False,'errors':[],'checks':[]}
    with tempfile.TemporaryDirectory() as temporary:
        home=Path(__file__).resolve().parents[1]
        app=PlaybackApp(home,Path(temporary),auto_catalog=False)
        app.show_error=lambda error: results['errors'].append(str(error))
        app.report_callback_exception=lambda kind,value,trace: results['errors'].append(str(value))
        app.volume_var.set(2)
        def start():
            try:
                file=DEFAULT_LEGACY/'Songs'/'MIDI'/'EMK'/'0'/'0.emk'
                song_id=app.library.add_files([file])[0]
                assert app.start_song(QueueItem(song_id))
                results['checks'].append('EMK native MIDI output started')
                app.open_mixer()
                app.stage_settings()
                app.audio_settings()
                app.record_window()
                app.lyric_editor()
                app.search_popup()
                app.show_controls()
                app.remote_window()
                app.toggle_stage()
                app.update_idletasks()
                assert app.stage_canvas.winfo_exists()
                results['checks'].append('Mixer / settings / recorder devices / LRC editor / remote dialog / search / singer window')
            except Exception as error:
                results['errors'].append(str(error))
            app.after(500,check)
        def check():
            try:
                assert app.engine and app.engine.position>0
                assert app.lyrics.lines
                assert app.engine._scheduler and app.engine._scheduler.is_alive()
                assert app.stage_canvas._cache is not None,'Pillow lyric rendering missing'
                assert app.play_button.winfo_rooty()+app.play_button.winfo_height()<=app.winfo_screenheight(),'Transport controls below screen'
                app.engine.seek(20)
                app.engine.set_key(2)
                app.engine.set_speed(1.1)
                app.engine.set_pan(0,32)
                app.engine.set_solo(0,True)
                app.engine.set_solo(0,False)
                app.engine.set_drum_muted(36,True)
                app.engine.set_loop(20,20.2)
                results['checks'].append('MIDI scheduler / EMK lyric raster / visible transport / seek-key-speed-pan-solo-drums-loop')
            except Exception as error:
                results['errors'].append(str(error))
            app.after(400,finish)
        def finish():
            try:
                assert 20<=app.engine.position<=20.25,'Loop did not repeat'
                file=DEFAULT_LEGACY/'Songs'/'MIDI'/'NCN'/'Song'/'1'/'10002.mid'
                song_id=app.library.add_files([file])[0]
                assert app.start_song(QueueItem(song_id))
                assert app.lyrics.lines,'NCN with un-timed footer lost all lyrics'
                assert all(line.text!='นิค_คาราโอเกะ' for line in app.lyrics.lines)
                line=next(line for line in app.lyrics.lines if len(line.words)>3)
                app.engine.seek(line.start+.02)
                app.paint_lyrics()
                assert app.preview.state[0] not in ('X-Stage Karaoke','ยังไม่มีเนื้อร้องสำหรับเพลงนี้')
                assert app.title() == DISPLAY_NAME
                assert app.preview.state==app.stage_canvas.state,'Preview and singer lyrics diverged'
                from PIL import Image, ImageChops
                def frame():
                    data=app.preview.tk.call(str(app.preview._images[0]),'data','-format','png')
                    if isinstance(data,str):
                        data=base64.b64decode(data)
                    return Image.open(io.BytesIO(data)).convert('RGB')
                interval=None
                for candidate in app.lyrics.lines:
                    for (start,text),(end,_) in zip(candidate.words,candidate.words[1:]):
                        if end-start>.08 and text.strip(' .>-_') and app.lyrics.at((start+end)/2)[0] is candidate:
                            interval=(start,end)
                            break
                    if interval:
                        break
                assert interval,'No lyric interval to check'
                app.engine.pause()
                start,end=interval
                app.engine.seek(start+(end-start)*.15)
                app.paint_lyrics()
                before=frame()
                app.engine.seek(start+(end-start)*.85)
                app.paint_lyrics()
                after=frame()
                assert ImageChops.difference(before,after).getbbox(),'Lyric color wipe did not advance between CUR anchors'
                results['checks'].append('Rendered lyric color wipe advances between real CUR timing anchors')
                diagnostic=json.loads((Path(temporary)/'last-playback.json').read_text(encoding='utf-8'))
                assert diagnostic['lyric_lines']>0 and diagnostic['removed_footer_lines']>0
                results['checks'].append('NCN 10002 footer regression: synchronized text on preview and singer window')
                app.close_stage()
                assert not results['errors'],results['errors']
                results['ok']=True
            except Exception as error:
                results['errors'].append(str(error))
            finally:
                app.close_app()
        app.after(100,start)
        app.mainloop()
    return results

if __name__=='__main__':
    result=run()
    print(json.dumps(result,ensure_ascii=True,indent=2))
    raise SystemExit(0 if result['ok'] else 1)
