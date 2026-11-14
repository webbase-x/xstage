"""Run: python main.py. Windows, Python 3.10+, Pillow for lyric rendering."""
from pathlib import Path
import argparse
import logging
import sys


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    home = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Independent Python karaoke player")
    parser.add_argument("--data-dir", type=Path, help="Alternate writable directory for index/settings")
    parser.add_argument("--self-test", action="store_true", help="Run packaged GUI/audio checks and write self-test.json; use a fresh --data-dir")
    parser.add_argument("--setup", action="store_true", help="Open local audio setup")
    parser.add_argument('--check-dependencies', action='store_true', help='Check packaged runtime without opening the player')
    parser.add_argument('--dependency-report', type=Path)
    parser.add_argument('--system-report',type=Path)
    parser.add_argument('--quality-scan',type=Path,help='Read-only quality report for a song database')
    parser.add_argument('--quality-output',type=Path)
    parser.add_argument('--quality-workers',type=int,default=4)
    parser.add_argument('--probe-media',type=Path)
    parser.add_argument('--probe-result',type=Path)
    args = parser.parse_args()
    if args.probe_media:
        if not args.probe_result:parser.error('--probe-result required')
        from karaoke.media_probe import main as probe_main
        raise SystemExit(probe_main(args.probe_media,args.probe_result))
    if args.quality_scan:
        if not args.quality_output:parser.error('--quality-output required')
        import json
        from karaoke.library_hygiene import scan
        folder=scan(args.quality_scan,args.quality_output,workers=max(1,min(8,args.quality_workers)))
        (args.quality_output/'quality-scan-result.json').write_text(json.dumps({'folder':str(folder)},ensure_ascii=False),encoding='utf-8')
        return 0
    if args.system_report:
        from karaoke.support_report import run
        raise SystemExit(run(home,args.data_dir or home/'data',args.system_report))
    if args.check_dependencies:
        from karaoke.dependency_check import run
        raise SystemExit(run(home,args.dependency_report))
    data = args.data_dir or home / "data"
    data.mkdir(parents=True, exist_ok=True)
    from karaoke.instance_lock import DataDirectoryLock
    lock = DataDirectoryLock(data)
    try:
        lock.acquire()
    except (OSError, RuntimeError) as error:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk(); root.withdraw()
        messagebox.showerror('X-Stage Karaoke', str(error), parent=root)
        root.destroy()
        return
    from karaoke.startup_hygiene import quarantine_stale
    try:
        quarantined=quarantine_stale(data)
        if quarantined: logging.warning('STARTUP_HYGIENE_QUARANTINED count=%s',len(quarantined))
    except OSError:
        logging.exception('STARTUP_HYGIENE_FAILED')
    from karaoke.runtime_diagnostics import start
    diagnostics = None
    try:
        diagnostics = start(data)
        if sys.platform != "win32":
            parser.error("This version supports Windows only.")
        # DPI awareness before Tk creates a window. Ignore unsupported versions.
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
        from karaoke.restore import apply_pending
        try:restored=apply_pending(data)
        except Exception as error:
            import tkinter as tk
            from tkinter import messagebox
            root=tk.Tk();root.withdraw()
            messagebox.showerror('กู้คืนข้อมูลไม่สำเร็จ',str(error),parent=root)
            root.destroy()
            raise
        from karaoke.json_recovery import preflight
        if not preflight(data):
            return
        from karaoke.library_hygiene import pending_cleanup_plans
        pending_cleanup=pending_cleanup_plans(data/'quality-reports')
        import tkinter as tk
        tk.Tk.report_callback_exception = lambda _root, *error: diagnostics.callback_exception(*error)
        from karaoke.performer import PlaybackApp
        from karaoke import APP_NAME, __version__
        app = PlaybackApp(home, data, auto_catalog=not (args.self_test or args.setup) and not restored)
        app.data_lock=lock
        diagnostics.attach(app)
        if pending_cleanup:
            app._pending_cleanup_plans=pending_cleanup
            def show_pending_cleanup():
                from tkinter import messagebox
                folders='\n'.join(item['folder'] for item in pending_cleanup[:3])
                extra='' if len(pending_cleanup)<=3 else f'\nและอีก {len(pending_cleanup)-3} แผน'
                messagebox.showwarning('พบงานตรวจ/ลบที่ค้าง',
                    'พบงานที่อาจหยุดกลางขั้นตอน จึงยังไม่ทำงานลบต่ออัตโนมัติ\n\n'
                    f'แผนที่ต้องตรวจ: {len(pending_cleanup)}\n{folders}{extra}\n\n'
                    'เปิดเมนูจัดการเพลงซ้ำเพื่อเปิดรายงานและกู้คืนรายการที่ค้าง',parent=app)
            app.after(350,show_pending_cleanup)
        if restored:
            from tkinter import messagebox
            app.after(200,lambda:messagebox.showinfo('กู้คืนข้อมูลสำเร็จ',
                f"เพลง {restored['songs']:,} • คิว {restored['queue']:,}\nสำรองก่อนกู้คืน: {restored['safety']}",parent=app))
        if args.self_test:
            import json
            from karaoke.library import QueueItem
            results = {"ok": False, "errors": [], "app_name": APP_NAME, "version": __version__, "window_title": app.title()}
            app.show_error = lambda error: results["errors"].append(str(error))
            def finish():
                try:
                    assert app.engine and app.engine.position > 0, "WAV did not advance"
                    assert app.lyrics.lines, "Timed lyrics missing"
                    app.toggle_stage()
                    app.update_idletasks()
                    assert app.stage.winfo_exists(), "Singer window missing"
                    from karaoke.legacy import DEFAULT_LEGACY
                    regression = DEFAULT_LEGACY / 'Songs' / 'MIDI' / 'NCN' / 'Song' / '1' / '10002.mid'
                    if regression.is_file():
                        song_id = app.library.add_files([regression])[0]
                        assert app.start_song(QueueItem(song_id)), 'NCN regression song failed'
                        assert app.lyrics.lines, 'Untimed footer hid the lyrics'
                        assert getattr(app.lyrics,'removed_footer_lines',0)>0, 'Footer not recognized'
                        app.engine.pause()
                        app.engine.seek(app.lyrics.lines[0].start+.01)
                        app.paint_lyrics()
                        assert app.preview.state[0] != 'ยังไม่มีเนื้อร้องสำหรับเพลงนี้'
                        results['lyric_regression'] = {'code':'10002','lines':len(app.lyrics.lines),'footer_removed':True}
                    app.close_stage()
                    assert not results["errors"], results["errors"]
                    results["ok"] = True
                except Exception as error:
                    results["errors"].append(str(error))
                finally:
                    (data / "self-test.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                    app.close_app()
            def switch_audio():
                try:
                    assert app.engine and app.engine.position > 0, "MIDI did not advance"
                    audio = next(song for song in app.library.search() if song["kind"] == "AUDIO")
                    assert app.start_song(QueueItem(audio["id"])), "WAV did not start"
                    app.engine.set_speed(1.1)
                except Exception as error:
                    results["errors"].append(str(error))
                app.after(250, finish)
            def begin():
                try:
                    app.volume_var.set(5)
                    midi = next(song for song in app.library.search() if song["kind"] == "MIDI")
                    assert app.start_song(QueueItem(midi["id"])), "MIDI did not start"
                except Exception as error:
                    results["errors"].append(str(error))
                app.after(250, switch_audio)
            app.after(100, begin)
        if not args.self_test:
            from karaoke.first_run_ui import schedule_startup
            schedule_startup(app, force=args.setup)
        app.mainloop()
        if args.self_test and not results["ok"]:
            raise SystemExit(1)
    except Exception:
        logging.exception("Application startup failed")
        from karaoke.library import JsonRecoveryError
        if isinstance(sys.exc_info()[1], JsonRecoveryError):
            from tkinter import messagebox
            root = tk.Tk(); root.withdraw()
            messagebox.showerror('Data recovery required', str(sys.exc_info()[1]), parent=root)
            root.destroy()
        raise
    finally:
        try:
            if diagnostics is not None:
                diagnostics.close()
        finally:
            lock.close()


if __name__ == "__main__":
    main()
