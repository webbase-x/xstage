"""Attempt every shutdown step and report failures after resource cleanup."""
import logging


class ShutdownError(OSError):
    pass


def step(app,label,action):
    try:action();return True
    except Exception as error:
        app.__dict__.setdefault('_shutdown_errors',[]).append((label,error))
        logging.exception('SHUTDOWN_STEP_FAILED step=%s',label)
        return False


def finish(app):
    errors=app.__dict__.setdefault('_shutdown_errors',[])
    if errors:
        show=getattr(app,'show_error',None)
        if callable(show):
            step(app,'แจ้งข้อผิดพลาด',lambda:show('ปิดโปรแกรมพบข้อผิดพลาด โปรดตรวจ Log\n'+'\n'.join(f'{label}: {error}' for label,error in errors)))
    step(app,'ยกเลิก callback หน้าต่าง',lambda:cancel_callbacks(app))
    done=step(app,'ปิดหน้าต่าง',app.destroy)
    if done:step(app,'ยกเลิก callback หลังปิด',lambda:cancel_callbacks(app))
    app.__dict__['_shutdown_done']=done
    if errors:
        raise ShutdownError('ปิดโปรแกรมพบข้อผิดพลาด: '+', '.join(label for label,_ in errors)) from errors[0][1]


def wait_for_index(app):
    """Cancel and wait without destroying Tk while a file job still owns resources."""
    if app.__dict__.get('_cloud_backup_busy',False):
        # A completed/idle online dialog is not an active Drive operation.
        # Close that dialog and release its old busy state when the PC quits;
        # only wait for a genuinely live sync worker.
        worker = app.__dict__.get('_online_sync_thread')
        dialog = app.__dict__.get('_cloud_progress_window')
        if worker is None or not worker.is_alive():
            if dialog is not None:
                try:
                    if dialog.winfo_exists():
                        dialog.destroy()
                except Exception:
                    logging.exception('SHUTDOWN_ONLINE_DIALOG_CLOSE_FAILED')
            app.__dict__['_cloud_progress_window'] = None
            app.__dict__['_cloud_backup_busy'] = False
            app.__dict__['_online_sync_thread'] = None
        else:
            try:app.status_var.set('กำลังรอการซิงก์ X-Stage Karaoke Online ให้เสร็จก่อนปิดโปรแกรม…')
            except Exception:logging.exception('SHUTDOWN_WAIT_BACKUP_STATUS_FAILED')
            if app.__dict__.get('_close_wait_timer') is None:
                def again_backup():
                    app._close_wait_timer=None;app.close_app()
                app._close_wait_timer=app.after(250,again_backup)
            return True
    worker=app.__dict__.get('_index_thread')
    if worker is None:return False
    alive=worker.is_alive()
    if not alive and not getattr(app,'scanning',False):return False
    if alive:app.cancel_scan.set()
    try:app.status_var.set('กำลังยกเลิกงานและรอให้ไฟล์/บันทึกงานปลอดภัยก่อนปิดโปรแกรม…')
    except Exception:logging.exception('SHUTDOWN_WAIT_STATUS_FAILED')
    if app.__dict__.get('_close_wait_timer') is None:
        def again():
            app._close_wait_timer=None;app.close_app()
        app._close_wait_timer=app.after(100,again)
    return True


def cancel_callbacks(app):
    """A Tk interpreter owns all its after callbacks, including utility windows."""
    interpreter=app.__dict__.get('tk')
    if interpreter is None:return
    for timer in interpreter.call('after','info'):
        interpreter.call('after','cancel',timer)
