"""Index on the worker, append to the latest live queue only on the UI thread."""
import logging
from .library import PlaylistImportError


def handle_message(app,kind,data):
    if kind!='playlist_ready':return False
    pending,missing,notes=data
    error=None
    try:app.song_queue._commit(app.song_queue.items+pending)
    except (OSError,ValueError) as failure:
        error=PlaylistImportError(len(pending),'บันทึกคิว',str(failure));notes=list(notes)+[str(error)]
        logging.exception('PLAYLIST_QUEUE_COMMIT_FAILED indexed=%s',len(pending))
    report_failure=None
    try:app.write_import_report((len(pending),missing,notes))
    except (OSError,ValueError) as failure:
        report_failure=str(failure);logging.exception('PLAYLIST_REPORT_WRITE_FAILED')
    app.refresh_library();app.refresh_queue()
    if error:
        app.status_var.set(str(error));app.show_error(error)
    elif report_failure:
        message=f'นำเข้าคิว {len(pending):,} เพลงแล้ว แต่บันทึกรายงานไม่สำเร็จ: '+report_failure
        app.status_var.set(message);app.show_error(message)
    else:app.status_var.set(f'นำเข้าคิว {len(pending):,} เพลง • ข้าม/ต้องตรวจเพิ่ม {missing:,} เพลง')
    return True
