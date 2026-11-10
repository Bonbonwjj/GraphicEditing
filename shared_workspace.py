"""Direct shared project paths and reentrant cross-process file locks."""
import hashlib
import os
from pathlib import Path
import threading
import time

SHARED_ROOT=None


def projects_path(root,target):
    return Path(target['path'])/'projects' if (target or {}).get('mode')=='direct' else Path(root)/'projects'


def register_shared_root(path):
    global SHARED_ROOT
    SHARED_ROOT=Path(path).absolute() if path is not None else None


def shared_lock_path(key):
    if SHARED_ROOT is None:return None
    try:relative=Path(key).absolute().relative_to(SHARED_ROOT).as_posix()
    except (ValueError,TypeError):return None
    if os.name=='nt':relative=relative.lower()
    return SHARED_ROOT/'.write-locks'/(hashlib.sha256(relative.encode()).hexdigest()+'.lock')


class SharedFileLock:
    def __init__(self,path):
        self.path=Path(path);self.mutex=threading.RLock();self.depth=0;self.stream=None

    def acquire(self,blocking=True,timeout=-1):
        if not self.mutex.acquire(blocking,timeout):return False
        if self.depth:self.depth+=1;return True
        stream=None
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            stream=self.path.open('a+b')
            if self.path.stat().st_size==0:stream.write(b'0');stream.flush()
            deadline=time.monotonic()+(60 if timeout<0 else timeout)
            while True:
                try:
                    stream.seek(0)
                    if os.name=='nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    self.stream=stream;self.depth=1;return True
                except (BlockingIOError,PermissionError,OSError):
                    if not blocking:stream.close();self.mutex.release();return False
                    if time.monotonic()>=deadline:raise ValueError('另一位协作者正在写入该工程，请稍后重试') from None
                    time.sleep(.05)
        except BaseException:
            if stream is not None:stream.close()
            self.mutex.release();raise

    def release(self):
        if self.depth==1:
            try:
                self.stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
            finally:self.stream.close();self.stream=None;self.depth=0
        else:self.depth-=1
        self.mutex.release()

    def __enter__(self):self.acquire();return self
    def __exit__(self,*args):self.release()
