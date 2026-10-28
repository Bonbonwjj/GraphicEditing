"""Per-turn cancellation; never kill the shared application server."""
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
import queue
import socket
import threading


class Cancelled(BaseException):
    pass


CURRENT = ContextVar('chat_cancel', default=None)
ACTIVE = {}
GUARD = threading.Lock()


def check():
    event = CURRENT.get()
    if event is not None and event.is_set():
        raise Cancelled('已停止本轮改图，未应用未完成的候选。')


def call(function, *args, **kwargs):
    """Return control promptly even while a provider is connecting."""
    check()
    if CURRENT.get() is None:
        return function(*args, **kwargs)
    result = queue.Queue()
    context = copy_context()
    def run():
        try:
            result.put((True, context.run(function, *args, **kwargs)))
        except BaseException as error:
            result.put((False, error))
    threading.Thread(target=run, daemon=True).start()
    while True:
        check()
        try:
            ok, value = result.get(timeout=.1)
        except queue.Empty:
            continue
        check()
        if not ok:
            raise value
        return value


@contextmanager
def watching(stream):
    """Interrupt blocking reads on urllib HTTP streams when stopped."""
    event = CURRENT.get()
    done = threading.Event()
    def watch():
        while not done.wait(.1):
            if event.is_set():
                try:
                    stream.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except (AttributeError, OSError):
                    pass
                return
    if event is not None:
        threading.Thread(target=watch, daemon=True).start()
    try:
        check()
        yield stream
        check()
    finally:
        done.set()
