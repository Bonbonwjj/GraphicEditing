"""Run an original plotting entry from a disposable, editable source copy.

The worker installs this module as trusted platform code.  Original project
sources stay read-only; optional exact replacements are applied only below the
renderer's writable runtime directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import shutil
import sys


OUTPUT_PROVENANCE = {}


class FigureComplete(BaseException):
    """Stop the original script immediately after its selected output."""


def _apply_edits(root, edits):
    if not isinstance(edits, dict):
        raise ValueError('UNIVERSAL_SOURCE_EDITS must be a path-to-replacements object')
    for relative, replacements in edits.items():
        if not isinstance(relative, str) or not relative or '\\' in relative:
            raise ValueError('Universal source edit path is invalid')
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or path.suffix != '.py':
            raise ValueError('Universal source edits may target only copied Python sources')
        content = path.read_text(encoding='utf-8-sig')
        if not isinstance(replacements, list):
            raise ValueError('Universal source replacements must be a list')
        for edit in replacements:
            if not isinstance(edit, dict) or not isinstance(edit.get('old'), str) or not isinstance(edit.get('new'), str):
                raise ValueError('Universal source replacement is invalid')
            old = edit['old']
            if not old or content.count(old) != 1:
                raise ValueError('Universal source replacement anchor must occur exactly once')
            content = content.replace(old, edit['new'], 1)
        path.write_text(content, encoding='utf-8', newline='\n')


def _safe_previous_path(root, destination, index):
    if isinstance(destination, (str, os.PathLike)):
        raw = Path(destination)
        candidate = raw if raw.is_absolute() else root / raw
        try:
            candidate = candidate.resolve()
        except OSError:
            candidate = root / ('previous-output-' + str(index) + '.png')
        if candidate.is_relative_to(root.resolve()):
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate
    return destination


def render_original(figure_id, customize, source_edits=None):
    """Execute one registered entry and capture its selected save/show event."""
    from matplotlib.figure import Figure
    import matplotlib
    import matplotlib.pyplot as plt

    project = Path(os.environ['CHART_PROJECT_DIR']).resolve()
    registry = json.loads((project / 'universal-project.json').read_text(encoding='utf-8'))
    if registry.get('schema') != 'plot-forge-universal/1':
        raise ValueError('Unsupported universal project registry')
    settings = registry.get('figures', {}).get(figure_id)
    if not settings:
        raise ValueError('Unknown universal figure: ' + str(figure_id))
    occurrence = settings.get('output_index')
    if type(occurrence) is not int or not 1 <= occurrence <= 100:
        raise ValueError('Universal output index is invalid')

    source = project / registry['source_root']
    runtime = Path(os.environ['CHART_OUTPUT']).resolve().parent / 'universal-work' / figure_id
    if runtime.exists():
        raise ValueError('Universal figure may run only once per isolated render')
    shutil.copytree(source, runtime)
    _apply_edits(runtime, source_edits or {})
    entry = (runtime / settings['entry_path']).resolve()
    if not entry.is_relative_to(runtime.resolve()) or not entry.is_file() or entry.suffix != '.py':
        raise ValueError('Universal entry path is unavailable')

    output = Path(os.environ['CHART_OUTPUT']).resolve()
    original_save = Figure.savefig
    original_show = plt.show
    original_use = matplotlib.use
    def headless_use(backend,*args,**kwargs):
        if str(backend).lower() in {'tkagg','qtagg','qt5agg','wxagg','gtk3agg','gtk4agg','macosx'}:
            return original_use('Agg')
        return original_use(backend,*args,**kwargs)
    count = 0
    completed = False

    def record_output(kind):
        OUTPUT_PROVENANCE.clear()
        OUTPUT_PROVENANCE.update(kind=kind,entry_path=settings['entry_path'],
                                 entry_symbol=settings.get('entry_symbol'),output_index=count)
        frame=sys._getframe(1)
        while frame is not None:
            file=Path(frame.f_code.co_filename)
            if file.is_absolute() and file.is_relative_to(runtime):
                OUTPUT_PROVENANCE.update(source_path=file.relative_to(runtime).as_posix(),
                                         line=frame.f_lineno,symbol=frame.f_code.co_name)
                break
            frame=frame.f_back

    def selected_save(figure, destination, *args, **kwargs):
        nonlocal count
        count += 1
        if count != occurrence:
            # Earlier outputs are intentionally suppressed.  They are captured
            # by their own adapters and may not mutate the read-only project.
            return None
        record_output('savefig')
        customize(figure)
        options = dict(kwargs)
        options['format'] = 'png'
        original_save(figure, output, *args, **options)
        raise FigureComplete()

    def selected_show(*args, **kwargs):
        nonlocal count
        figures = [plt.figure(number) for number in plt.get_fignums()]
        if not figures:
            return None
        for figure in figures:
            count += 1
            if count == occurrence:
                record_output('show')
                customize(figure)
                original_save(figure, output, format='png', dpi=figure.dpi)
                raise FigureComplete()
        return None

    old_cwd = Path.cwd()
    old_path = list(sys.path)
    old_argv = sys.argv[:]
    Figure.savefig = selected_save
    plt.show = selected_show
    matplotlib.use = headless_use
    try:
        os.chdir(runtime)
        sys.path.insert(0, str(runtime))
        sys.path.insert(0, str(entry.parent))
        sys.argv = [str(entry), *settings.get('argv', [])]
        try:
            symbol=settings.get('entry_symbol')
            namespace=runpy.run_path(str(entry), run_name='__main__' if not symbol else '_plot_forge_original_')
            if symbol:
                function=namespace.get(symbol)
                if not callable(function):
                    raise ValueError('Registered plotting function is unavailable: '+str(symbol))
                method=settings.get('entry_method')
                if method:
                    instance=function()
                    function=getattr(instance,method)
                returned=function(**settings.get('entry_kwargs',{}))
                if settings.get('capture_return'):
                    values=returned if isinstance(returned,(list,tuple)) else [returned]
                    figures=[]
                    for value in values:
                        if isinstance(value,Figure):
                            figures.append(value)
                        elif hasattr(value,'figure') and isinstance(value.figure,Figure):
                            figures.append(value.figure)
                        elif hasattr(value,'fig') and isinstance(value.fig,Figure):
                            figures.append(value.fig)
                    for figure in dict.fromkeys(figures):
                        count += 1
                        if count == occurrence:
                            record_output('return')
                            customize(figure)
                            original_save(figure,output,format='png',dpi=figure.dpi)
                            raise FigureComplete()
            elif settings.get('capture_open_figures') and count == 0:
                for number in plt.get_fignums():
                    figure=plt.figure(number)
                    count += 1
                    if count == occurrence:
                        record_output('open_figure')
                        customize(figure)
                        original_save(figure,output,format='png',dpi=figure.dpi)
                        raise FigureComplete()
        except FigureComplete:
            completed = True
        except SystemExit as error:
            if error.code not in (None,0):
                raise ValueError('绘图入口退出，可能缺少命令行参数；退出码：'+str(error.code)) from error
    finally:
        Figure.savefig = original_save
        plt.show = original_show
        matplotlib.use = original_use
        sys.path[:] = old_path
        sys.argv[:] = old_argv
        os.chdir(old_cwd)
    if not completed or not output.is_file():
        raise ValueError(f'Selected plotting output {occurrence} was not reached; observed {count}')
