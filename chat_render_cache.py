"""Bounded, content-keyed native baseline audits and pristine figure seeds."""
import ast
import copy
import hashlib
import json
import threading
from collections import OrderedDict
from pathlib import Path

_CACHE = OrderedDict()
_GUARD = threading.Lock()
_LOCKS = {}
MAX_ENTRIES = 3


def native_replay_compatible(before, after):
    """Only the post-construction customize body and literal style may differ."""
    signatures = []
    for source in (before, after):
        try: tree = ast.parse(source)
        except (SyntaxError, TypeError): return False
        calls = [n for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                 and isinstance(n.value.func, ast.Name) and n.value.func.id == 'render_native']
        hooks = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'customize']
        if len(calls) != 1 or len(hooks) != 1 or calls[0] is not tree.body[-1]: return False
        call = calls[0].value
        if (len(call.args) != 3 or call.keywords or not isinstance(call.args[1], ast.Name)
                or call.args[1].id != 'customize'): return False
        if sum(isinstance(n, ast.Name) and n.id == 'customize' for n in ast.walk(tree)) != 1: return False
        # Project module globals may be initialized by produce(). They are not
        # guaranteed to exist after deserializing a pristine figure. Keep those
        # custom hooks on the full execution path.
        allowed = {'enumerate','zip','list','tuple','dict','set','len','range','getattr','hasattr',
                   'isinstance','float','int','str','bool','min','max','abs','sorted','reversed','sum','any','all'}
        hook = hooks[0]
        allowed.update(arg.arg for node in ast.walk(hook) if isinstance(node, (ast.FunctionDef, ast.Lambda))
                       for arg in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs])
        allowed.update(n.id for n in ast.walk(hook) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    if name.name.split('.')[0] in {'matplotlib','numpy','plot_modes','interactive_style','component_editor'}:
                        allowed.add(name.asname or name.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if (node.module or '').split('.')[0] in {'matplotlib','numpy','plot_modes','interactive_style','component_editor'}:
                    allowed.update(name.asname or name.name for name in node.names if name.name != '*')
                elif node.module == 'native_plot_runtime':
                    allowed.update(name.asname or name.name for name in node.names if name.name == 'panel_axes')
            elif isinstance(node, ast.Assign):
                try: ast.literal_eval(node.value)
                except (ValueError, TypeError): continue
                allowed.update(target.id for target in node.targets if isinstance(target, ast.Name))
        if any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in allowed for n in ast.walk(hook)):
            return False
        hooks[0].body = [ast.Pass()]
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'INTERACTIVE_STYLE':
                try: ast.literal_eval(node.value)
                except (ValueError, TypeError): return False
                node.value = ast.Constant(None)
            elif any(isinstance(n, ast.Name) and n.id == 'INTERACTIVE_STYLE' for n in ast.walk(node)):
                return False
        signatures.append(ast.dump(tree, include_attributes=False))
    return signatures[0] == signatures[1]


def identity(project, entry, files, dpi):
    import server
    from render_environment import describe
    from chat_runner import isolation_backend
    source = files.get(entry)
    if source is None: source = (project/entry).read_text(encoding='utf-8')
    environment = describe(project, isolation_backend())
    value = [str(project.resolve()), entry, files, source, dpi, server.preview_signature(project, source),
             environment['fingerprint'], hashlib.sha256(Path(__file__).read_bytes()).hexdigest()]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def peek(key):
    with _GUARD:
        if key not in _CACHE: return None
        _CACHE.move_to_end(key)
        return copy.deepcopy(_CACHE[key])


def remember(key, report):
    with _GUARD:
        _CACHE[key] = copy.deepcopy(report)
        _CACHE.move_to_end(key)
        while len(_CACHE) > MAX_ENTRIES:
            removed, _ = _CACHE.popitem(last=False)
            _LOCKS.pop(removed, None)


def baseline(project, entry, files, directory, dpi, renderer, key=None):
    import chat_cancellation as cancellation
    key = key or identity(project, entry, files, dpi)
    with _GUARD: guard = _LOCKS.setdefault(key, threading.Lock())
    while not guard.acquire(timeout=.1): cancellation.check()
    try:
        cancellation.check()
        cached = peek(key)
        if cached is not None: return cached
        options = {'capture_interactive_seed': True}
        if dpi is not None: options['preview_dpi'] = dpi
        report = renderer(project, entry, files, directory, **options)
        if identity(project, entry, files, dpi) != key:
            raise ValueError('准备原图期间绘图代码或依赖发生变化，请重试')
        remember(key, report)
        return report
    finally:
        guard.release()
