"""Associate local figure-level labels with their nearest plot rectangle."""
import re


def panel_text_links(figure):
    result = {}
    for index, text in enumerate(figure.texts):
        label = text.get_text().strip().replace('$', '')
        if not text.get_visible() or not label or text in [getattr(figure,name,None) for name in ('_suptitle','_supxlabel','_supylabel')]:
            continue
        letter=bool(re.fullmatch(r'[\[(]?[A-Za-z]{1,2}[)\].:]?',label))
        letter_name=label.strip('[]().:').lower()
        named_axes=[axis for axis in figure.axes if letter and re.match(re.escape(letter_name)+r'(?:\d|_|$)',axis.get_label().lower())]
        point = text.get_transform().transform(text.get_position())
        candidates = []
        for ai, axis in enumerate(figure.axes):
            if not axis.get_visible() or axis.get_label().startswith('source_') or hasattr(axis,'_source_panel'):
                continue
            if named_axes and axis not in named_axes: continue
            box = axis.bbox
            if not letter:
                text_box=text.get_window_extent(figure.canvas.get_renderer())
                if text_box.width>box.width*1.15 or not (box.x0-figure.dpi*.1<=point[0]<=box.x1+figure.dpi*.1 and box.y0<=point[1]<=box.y1+figure.dpi*.4):
                    continue
            dx = box.x0-point[0] if letter else max(box.x0-point[0], 0, point[0]-box.x1)
            dy = box.y1-point[1] if letter else max(box.y0-point[1], 0, point[1]-box.y1)
            candidates.append((dx*dx+dy*dy, ai))
        if candidates:
            distance, ai = min(candidates)
            if distance <= (figure.dpi*(.75 if letter else .4))**2:
                result[f'figure.text_{index}'] = f'axes_{ai}'
    return result
