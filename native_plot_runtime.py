"""Host runtime for reviewed, already-separated frozen plotting packages.

Original modules and inputs remain immutable in the project. Legacy renderers
run against a disposable copy with their original relative directory layout.
Generated entries use ordinary imports; this host adds no eval/exec or runpy.
"""
import os
from pathlib import Path
import shutil
import sys

SAVE_TARGET = None
SAVE_INTERMEDIATE = None


class FigureComplete(BaseException):
    pass


def _compose_native_results(figure, settings):
    """Keep Fig.1's native quantitative axes and approved raster task panels."""
    import numpy as np
    from PIL import Image
    root=Path(os.environ['CHART_OUTPUT']).parent/'native-work/fig1'
    with Image.open(root/settings['approved_top']) as image:
        top=np.asarray(image.convert('RGB')).copy()
    width, old_height=figure.get_size_inches()*figure.dpi
    bottom_height=round(old_height)-settings['cut_px']
    if bottom_height <= 0 or int(width) != top.shape[1]:
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


def prepare_native(figure_id):
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
        customize(figure)
        # Original target saves do not crop. Preserve their exact DPI/size/style.
        SAVE_TARGET(figure, output, *args, **kwargs)
        raise FigureComplete()

    Figure.savefig = save
    try:
        produce()
    except FigureComplete:
        completed = True
    finally:
        Figure.savefig = previous
    if not completed or not Path(output).is_file():
        raise ValueError('The declared native figure save boundary was not reached')
