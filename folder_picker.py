"""Visible native directory chooser for the local desktop server."""
import os
import base64
from pathlib import Path
import subprocess
import sys


def choose_folder():
    if sys.platform == 'win32':
        script = Path(__file__).with_name('native_folder_dialog.ps1').read_text(encoding='utf-8')
        command = ['powershell.exe', '-NoProfile', '-STA', '-EncodedCommand',
                   base64.b64encode(script.encode('utf-16-le')).decode('ascii')]
    else:
        script = ('import tkinter as t; from tkinter import filedialog; r=t.Tk(); r.withdraw(); '
                  'r.attributes("-topmost",True); r.update(); '
                  'print(filedialog.askdirectory(parent=r,title="选择代码、数据或工程文件夹",mustexist=True)); r.destroy()')
        command = [sys.executable, '-c', script]
    env = {k:v for k,v in os.environ.items() if k.upper() in ('PATH','DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','SYSTEMROOT','WINDIR','LANG','LC_ALL','TEMP','TMP','TCL_LIBRARY','TK_LIBRARY','PSMODULEPATH','COMSPEC','USERPROFILE','APPDATA','LOCALAPPDATA')}
    env['PYTHONIOENCODING'] = 'utf-8'
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=600, env=env,
                                **({'creationflags':getattr(subprocess,'CREATE_NO_WINDOW',0)} if sys.platform=='win32' else {}))
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError('文件夹选择窗口未完成，请重试或直接粘贴完整路径。') from None
    if result.returncode:
        raise ValueError('无法打开文件夹选择窗口，请直接粘贴完整路径。')
    return result.stdout.strip()
