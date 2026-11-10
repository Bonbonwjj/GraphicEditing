"""Host runtime for reviewed, already-separated frozen plotting packages.

Original modules and inputs remain immutable in the project. Legacy renderers
run against a disposable copy with their original relative directory layout.
Generated entries use ordinary imports; this host adds no eval/exec or runpy.
"""
import ast
import os
from pathlib import Path
import shutil
import sys

SAVE_TARGET = None
SAVE_INTERMEDIATE = None
DIAGNOSTICS = []
INTERACTIVE_SEED_INPUT = None
INTERACTIVE_SEED_OUTPUT = None
INTERACTIVE_SEED_HASHES = {}
INTERACTIVE_SEED_REUSED = False
INTERACTIVE_SEED_PREPARE = None
INTERACTIVE_PREVIEW_DPI = None


def _capture_interactive_seed(figure_id, figure, args, kwargs):
    if not INTERACTIVE_SEED_OUTPUT: return
    import cloudpickle
    import gzip
    import random
    import numpy as np
    import matplotlib
    try:
        if INTERACTIVE_SEED_PREPARE: INTERACTIVE_SEED_PREPARE(figure)
        payload={'version':2,'figure_id':figure_id,'figure':figure,'args':args,'kwargs':kwargs,
                 'native_root':str(Path(os.environ['CHART_OUTPUT']).parent/'native-work'/figure_id),
                 'inputs':INTERACTIVE_SEED_HASHES,'diagnostics':list(DIAGNOSTICS),
                 'rc_params':dict(matplotlib.rcParams),'numpy_random_state':np.random.get_state(),
                 'random_state':random.getstate()}
        data=gzip.compress(cloudpickle.dumps(payload),compresslevel=1)
        if len(data)<=30*1024*1024: Path(INTERACTIVE_SEED_OUTPUT).write_bytes(data)
    except Exception as error:
        # Custom artists may not be serializable. Keep ordinary isolated
        # rendering available; final saves always use that original path.
        print('Interactive figure cache unavailable:',type(error).__name__,str(error),flush=True)


def _replay_interactive_seed(figure_id, customize):
    import pickle
    import gzip
    global INTERACTIVE_SEED_REUSED
    # Only the isolated, read-only chart worker deserializes the figure. The
    # HTTP server treats the bounded cache as opaque bytes.
    root=prepare_native(figure_id)
    with gzip.open(INTERACTIVE_SEED_INPUT,'rb') as stream: payload=pickle.load(stream)
    if payload.get('version')!=2 or payload.get('figure_id')!=figure_id or payload.get('inputs')!=INTERACTIVE_SEED_HASHES:
        raise ValueError('交互图形缓存与当前数据不一致')
    figure=payload['figure'];old_root=Path(payload['native_root'])
    import matplotlib
    import numpy as np
    import random
    matplotlib.rcParams.update(payload.get('rc_params',{}))
    if 'numpy_random_state' in payload: np.random.set_state(payload['numpy_random_state'])
    if 'random_state' in payload: random.setstate(payload['random_state'])
    if INTERACTIVE_PREVIEW_DPI:
        figure.set_dpi(min(figure.dpi, INTERACTIVE_PREVIEW_DPI))
    from matplotlib.text import Text
    for text in figure.findobj(match=Text):
        props=text.get_fontproperties();file=props.get_file()
        if file and Path(file).is_relative_to(old_root): props.set_file(str(root/Path(file).relative_to(old_root)))
    DIAGNOSTICS[:]=payload.get('diagnostics',[])
    customize(figure)
    SAVE_TARGET(figure,os.environ['CHART_OUTPUT'],*payload['args'],**payload['kwargs'])
    INTERACTIVE_SEED_REUSED=True


def _layout_failure(error):
    """Recognize geometry-only stops; never downgrade data/scientific checks."""
    from matplotlib.figure import Figure
    root=(Path(os.environ['CHART_OUTPUT']).parent/'native-work').resolve()
    frames=[];trace=error.__traceback__;finding=None
    anchors={'internal_gaps','row_balance','compound_layout','public_vertical_gap',
             'task_gap_clearance','gap_mm','tick_gap_mm','legend_bounds','frame_bounds','category_gap','alignment'}
    allowed=anchors|{'abs','min','max','all','any','len','float','np','math','WIDTH_MM','HEIGHT_MM','DPI'}
    while trace:
        frame=trace.tb_frame;path=Path(frame.f_code.co_filename)
        if path.is_file() and path.resolve().is_relative_to(root):
            frames.append(frame)
            if isinstance(error,AssertionError):
                try:tree=ast.parse(path.read_text(encoding='utf-8-sig'))
                except (OSError,SyntaxError,UnicodeError):return None
                for node in ast.walk(tree):
                    if isinstance(node,ast.Assert) and node.lineno<=trace.tb_lineno<=node.end_lineno:
                        names={n.id for n in ast.walk(node.test) if isinstance(n,ast.Name)}
                        if names&anchors and names<=allowed:
                            finding={'source':path.name,'line':node.lineno,'condition':ast.unparse(node.test),'message':str(error)}
            elif type(error).__name__=='PanelAlignmentError' and path.name=='audit_panel_alignment.py' and frame.f_code.co_name=='require_matplotlib_panel_alignment':
                finding={'source':path.name,'line':trace.tb_lineno,'condition':'panel alignment','message':str(error)}
        trace=trace.tb_next
    if not finding:return None
    figure=next((frame.f_locals['fig'] for frame in reversed(frames)
                 if isinstance(frame.f_locals.get('fig'),Figure) and frame.f_locals['fig'].axes),None)
    if figure is None:return None
    return figure,finding


class FigureComplete(BaseException):
    pass


def _compose_native_results(figure, settings):
    """Keep Fig.1's native quantitative axes and approved raster task panels."""
    import numpy as np
    from PIL import Image
    root=Path(os.environ['CHART_OUTPUT']).parent/'native-work/fig1'
    scale = figure.dpi / settings.get('source_dpi', 600)
    with Image.open(root/settings['approved_top']) as image:
        image = image.convert('RGB')
        if scale != 1:
            image = image.resize((round(image.width*scale), round(image.height*scale)),
                                 Image.Resampling.LANCZOS)
        top=np.asarray(image).copy()
    width, old_height=figure.get_size_inches()*figure.dpi
    bottom_height=round(old_height)-round(settings['cut_px']*scale)
    # Authored millimetres produce fractional pixel widths. PNG dimensions
    # are integers, so a sub-pixel difference is expected at the source DPI.
    if bottom_height <= 0 or abs(width - top.shape[1]) > 1:
        raise ValueError('Fig.1 native crop boundary differs from its approved source')
    new_height=bottom_height+top.shape[0]
    axes=[]
    for axis in list(figure.axes):
        bounds=axis.get_position().bounds
        if bounds[1]*old_height >= bottom_height:
            axis.remove()
        else:
            axes.append((axis,bounds))
    texts=[]
    for text in list(figure.texts):
        x,y=text.get_position()
        if y*old_height > bottom_height:
            text.remove()
        else:
            texts.append((text,x,y))
    figure.set_size_inches(width/figure.dpi,new_height/figure.dpi,forward=True)
    for axis,(x,y,w,h) in axes:
        axis.set_position((x,y*old_height/new_height,w,h*old_height/new_height))
    for text,x,y in texts:
        text.set_position((x,y*old_height/new_height))
    figure.figimage(top,xo=0,yo=bottom_height,origin='upper',resize=False)


def _apply_source_edits(root, source_edits):
    """Apply chart-local edits only to the disposable Python renderer copy."""
    for relative, edits in (source_edits or {}).items():
        path = root/relative
        if (not isinstance(relative, str) or not relative.startswith('code/') or path.suffix != '.py'
                or not path.resolve().is_relative_to((root/'code').resolve()) or not path.is_file()):
            raise ValueError('局部修改只能指向本图 code/ 下的 Python 源码')
        content = path.read_text(encoding='utf-8-sig')
        for edit in edits:
            old, new = edit['old'], edit['new']
            if not isinstance(old, str) or not old or not isinstance(new, str) or content.count(old)!=1:
                raise ValueError('局部源码锚点不唯一或已改变，请重新读取对应代码段')
            content = content.replace(old, new, 1)
        ast.parse(content)
        path.write_text(content, encoding='utf-8', newline='\n')


def prepare_native(figure_id, source_edits=None):
    import json
    from matplotlib import font_manager
    project = Path(os.environ['CHART_PROJECT_DIR'])
    registry = json.loads((project/'native-project.json').read_text())
    if figure_id not in registry['figures']:
        raise ValueError('Unknown native figure')
    root = Path(os.environ['CHART_OUTPUT']).parent/'native-work'/figure_id
    if root.exists():
        raise ValueError('Native figure may run only once per isolated render')
    root.mkdir(parents=True)
    for source in (project/'data/native'/figure_id, project/'lib/native'/figure_id):
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Native package may not contain symlinks')
            if path.is_file():
                destination = root/path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
    _apply_source_edits(root, source_edits)
    (root/'output').mkdir(exist_ok=True)
    (root/'output/qa').mkdir(exist_ok=True)
    (root/'qa').mkdir(exist_ok=True)
    # Original entry points register their bundled fonts before importing code.
    for font in sorted((root/'assets/fonts').glob('*.ttf')):
        font_manager.fontManager.addfont(str(font))
    if figure_id == 'fig3':
        fonts = (root/'assets/fonts').resolve()
        font_manager.fontManager.ttflist = [f for f in font_manager.fontManager.ttflist
            if f.name != 'DejaVu Sans' or Path(f.fname).resolve().is_relative_to(fonts)]
        font_manager.fontManager._findfont_cached.cache_clear()
    sys.path.insert(0, str(root/'code'))
    return root


def panel_axes(figure, panel_id, mapping):
    """Resolve visible panels through explicit labels, never through axis order."""
    labels = mapping.get(panel_id)
    if not labels:
        raise ValueError('所选子图没有明确的轴标签映射')
    result = [axis for axis in figure.axes if axis.get_label() in labels]
    missing = set(labels)-{axis.get_label() for axis in result}
    if missing:
        raise ValueError('未找到所选子图的轴标签：'+', '.join(sorted(missing)))
    return result


def render_native(figure_id, customize, produce):
    """Capture exactly the final native save; preserve intermediate drawing."""
    import json
    from matplotlib.figure import Figure
    project = Path(os.environ['CHART_PROJECT_DIR'])
    settings = json.loads((project/'native-project.json').read_text())['figures'][figure_id]
    if SAVE_TARGET is None or SAVE_INTERMEDIATE is None:
        raise RuntimeError('Native charts require the isolated Plot Forge renderer')
    previous = Figure.savefig
    output = os.environ['CHART_OUTPUT']
    completed = False
    matches = 0
    DIAGNOSTICS.clear()
    if INTERACTIVE_SEED_INPUT:
        _replay_interactive_seed(figure_id,customize)
        return

    def save(figure, destination, *args, **kwargs):
        nonlocal matches
        frame = sys._getframe(1)
        match = (Path(frame.f_code.co_filename).name == settings['save_file']
                 and frame.f_code.co_name == settings['save_function'])
        if not match:
            return SAVE_INTERMEDIATE(figure, destination, *args, **kwargs)
        matches += 1
        if matches != settings.get('save_occurrence',1):
            return SAVE_INTERMEDIATE(figure,destination,*args,**kwargs)
        if settings.get('compose') == 'native_results_with_approved_top':
            _compose_native_results(figure,settings)
        _capture_interactive_seed(figure_id,figure,args,kwargs)
        customize(figure)
        from interactive_style import finalize_conversion_ranges
        finalize_conversion_ranges(figure)
        # Original target saves do not crop. Preserve their exact DPI/size/style.
        SAVE_TARGET(figure, output, *args, **kwargs)
        raise FigureComplete()

    Figure.savefig = save
    try:
        produce()
    except FigureComplete:
        completed = True
    except Exception as error:
        diagnostic=_layout_failure(error)
        if diagnostic is None:raise
        figure,finding=diagnostic
        DIAGNOSTICS.append({**finding,'figure_id':figure_id,
            'warning':'布局检查未通过：显示中止时的实际画布，后续原程序检查未完成；此预览不代表完整验证通过。'})
        if settings.get('compose')=='native_results_with_approved_top':_compose_native_results(figure,settings)
        _capture_interactive_seed(figure_id,figure,(),{'dpi':figure.dpi,'facecolor':'white','transparent':False})
        customize(figure)
        SAVE_TARGET(figure,output,dpi=figure.dpi,facecolor='white',transparent=False)
        completed=True
    finally:
        Figure.savefig = previous
    if not completed or not Path(output).is_file():
        raise ValueError('The declared native figure save boundary was not reached')
