"""Cache pristine native figures for style previews, never for final saves."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

_LOCKS = {}
_GUARD = threading.Lock()
MAX_SEED_BYTES = 30 * 1024 * 1024


def _lock(project, chart):
    with _GUARD:
        return _LOCKS.setdefault((str(project.resolve()), chart), threading.RLock())


def _paths(project, chart):
    folder = project/'.preparation/interactive-figures'
    if not folder.resolve().is_relative_to(project.resolve()):
        raise ValueError('交互缓存目录必须位于当前工程内')
    folder.mkdir(parents=True, exist_ok=True)
    # The chart identifier has already passed chart_path, but do not use it as
    # a cache path component: the opaque digest also handles Unicode entries.
    name = hashlib.sha256(chart.encode()).hexdigest()[:24]
    return folder/(name+'.json'), folder/(name+'.pkl')


def _load(meta, seed, signature):
    try:
        if meta.is_symlink() or seed.is_symlink(): return None, False
        record = json.loads(meta.read_text(encoding='utf-8'))
        if record.get('signature') != signature: return None, False
        if record.get('unavailable'): return None, True
        if not seed.is_file() or seed.stat().st_size > MAX_SEED_BYTES: return None, False
        data = seed.read_bytes()
        if hashlib.sha256(data).hexdigest() == record.get('sha256'): return data, False
    except (OSError, ValueError): pass
    return None, False


def _save(meta, seed, signature, data):
    record = {'signature': signature, 'unavailable': data is None}
    if data is not None:
        if len(data) > MAX_SEED_BYTES: return
        temporary = seed.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_bytes(data); temporary.replace(seed)
        record['sha256'] = hashlib.sha256(data).hexdigest()
    temporary = meta.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(record), encoding='utf-8'); temporary.replace(meta)


def render_preview(project, chart, source, style, renderer, signature, preview_dpi=None, lightweight=False):
    from interactive_style import upsert_style
    candidate = upsert_style(source, style)
    from render_environment import describe
    from chat_runner import isolation_backend
    environment = describe(project, isolation_backend())
    normalized = upsert_style(source, {})
    def fingerprint():
        return hashlib.sha256(json.dumps(['native-interactive-figure-v1',
            signature(project, normalized), environment['fingerprint']]).encode()).hexdigest()
    with _lock(project, chart):
        revision = fingerprint()
        try: meta, seed_path = _paths(project, chart)
        except (OSError, ValueError): return renderer(project, candidate)
        seed, unavailable = _load(meta, seed_path, revision)
        started = time.monotonic()
        preview_options={'preview_dpi':preview_dpi} if preview_dpi is not None else {}
        if seed is not None:
            replay_options={**preview_options}
            if lightweight:replay_options['lightweight_preview']=True
            try: image = renderer(project, candidate, interactive_seed=seed, **replay_options)
            except ValueError:
                # Version-specific/custom artist problems fall back to the
                # original isolated renderer and refresh this chart's cache.
                seed = None
        if seed is None:
            # Build the reusable figure at its authored DPI. Some scientific
            # layouts validate pixel spacing while constructing the figure;
            # lowering DPI before that validation can change or reject layout.
            # Only seed replay uses the lower interactive output DPI.
            image = renderer(project, candidate,
                             **({} if unavailable else {'capture_interactive_seed': True}))
        if fingerprint() != revision or (project/'charts'/(chart+'.py')).read_text(encoding='utf-8') != source:
            raise ValueError('绘图代码或数据在预览期间发生变化，请重新加载后重试')
        if seed is None and not unavailable:
            try: _save(meta, seed_path, revision, getattr(image, 'interactive_seed', None))
            except OSError: pass
        report = getattr(image, 'render_report', None)
        if report is not None: report['interactive_preview_seconds'] = round(time.monotonic()-started, 3)
        return image
