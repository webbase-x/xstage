"""Test installer locking and graceful shutdown using isolated release copies."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def invoke(package, target, close=False, expected=0):
    command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
               str(package/'install_to_D.ps1'), '-Destination', str(target)]
    if close:
        command += ['-CloseRunning', '-CloseTimeoutSeconds', '10']
    result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=900)
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    return result.stdout


def verify(package):
    package = Path(package).resolve()
    report = {'ok': False, 'checks': []}
    with tempfile.TemporaryDirectory(prefix='xstage-installer-test-') as temporary:
        root = Path(temporary).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        target, other = root/'Installed', root/'OtherInstalled'
        (target/'Data').mkdir(parents=True)
        sentinel = target/'Data'/'keep-existing.json'
        sentinel.write_text('{"preserved":true}')
        invoke(package, target)
        assert sentinel.read_text() == '{"preserved":true}'
        assert (target/'App'/'XStageKaraoke.exe').is_file()
        assert (target/'Source'/'main.py').is_file()
        report['checks'].append('Fresh installation and launchers succeed; existing Data preserved')

        # A native exclusive file handle reproduces a busy EXE without relying
        # on a particular Windows process or antivirus implementation.
        executable = target/'App'/'XStageKaraoke.exe'
        source_main = target/'Source'/'main.py'
        source_main.write_text('old-source-must-remain-on-busy-file', encoding='utf-8')
        before = hashlib.sha256(executable.read_bytes()).hexdigest()
        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p,
                                      w.DWORD, w.DWORD, c.c_void_p]
        kernel.CreateFileW.restype = c.c_void_p
        kernel.CloseHandle.argtypes = [c.c_void_p]
        handle = kernel.CreateFileW(str(executable), 0x80000000, 1, None, 3, 0, None)
        assert handle and handle != c.c_void_p(-1).value
        try:
            output = invoke(package, target, close=True, expected=20)
            assert 'File is in use' in output
            assert source_main.read_text(encoding='utf-8') == 'old-source-must-remain-on-busy-file'
            assert hashlib.sha256(executable.read_bytes()).hexdigest() == before
            assert sentinel.read_text() == '{"preserved":true}'
        finally:
            kernel.CloseHandle(handle)
        report['checks'].append('Locked EXE returns exit 20 before overwriting Source/App; Data unchanged')
        invoke(package, target)
        invoke(package, other)

        processes = []
        try:
            for destination in (target, other):
                settings = destination/'Data'/'settings.json'
                # Avoid importing the user's real song catalog during this test.
                settings.write_text(json.dumps({'legacy_root': str(root/'NoCatalog')}), encoding='utf-8')
                process = subprocess.Popen([str(destination/'App'/'XStageKaraoke.exe'),
                    '--data-dir', str(destination/'Data')], cwd=destination/'App')
                processes.append(process)
            user = c.WinDLL('user32')
            callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
            user.EnumWindows.argtypes = [callback_type, w.LPARAM]
            user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
            user.IsWindowVisible.argtypes = [w.HWND]
            def visible_pids():
                found = set()
                def collect(window, _):
                    pid = w.DWORD()
                    user.GetWindowThreadProcessId(window, c.byref(pid))
                    if user.IsWindowVisible(window):
                        found.add(pid.value)
                    return True
                callback = callback_type(collect)
                user.EnumWindows(callback, 0)
                return found
            deadline = time.monotonic()+20
            while not all(process.pid in visible_pids() for process in processes):
                assert all(process.poll() is None for process in processes), 'A test player exited during startup'
                if time.monotonic() > deadline:
                    raise AssertionError('Test players did not show a window')
                time.sleep(.15)
            output = invoke(package, target, expected=20)
            assert 'Close all X-Stage Karaoke windows' in output
            assert processes[0].poll() is None, 'Default installer closed a process without -CloseRunning'
            report['checks'].append('Running target is detected; direct PowerShell invocation stops before copying')
            output = invoke(package, target, close=True)
            processes[0].wait(timeout=10)
            assert 'Closing the installed X-Stage Karaoke normally' in output
            saved = json.loads((target/'Data'/'settings.json').read_text(encoding='utf-8'))
            assert 'auto_next' in saved and 'volume' in saved, 'Normal shutdown did not save application settings'
            assert processes[1].poll() is None, 'A player in a different installation was closed'
            assert sentinel.read_text() == '{"preserved":true}'
            assert source_main.read_text(encoding='utf-8') != 'old-source-must-remain-on-busy-file'
            report['checks'].append('Real installed player closes normally, saves settings, and updates successfully')
            report['checks'].append('Player from another executable path stays running; target Data remains intact')
        finally:
            for process in processes:
                if process.poll() is None:
                    # Only processes created above with owned temporary data.
                    process.terminate()
                process.wait(timeout=10)

        output = invoke(package, package/'NestedTarget', expected=1)
        assert not (package/'NestedTarget').exists()
        report['checks'].append('Overlapping package/destination paths are rejected before writes')
        report['ok'] = True
    return report


if __name__ == '__main__':
    print(json.dumps(verify(sys.argv[1]), ensure_ascii=True, indent=2))
