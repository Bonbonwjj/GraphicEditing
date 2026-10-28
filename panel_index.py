"""Static panel/source navigation. Never import user code to discover its panels."""
import ast
import hashlib
import json
import re
from pathlib import Path


def source_files(project, chart):
    project = Path(project)
    entry = project/'charts'/f'{chart}.py'
    from native_project import selection
    ident = selection(project, entry.relative_to(project).as_posix())
    roots = [project/'lib/native'/ident] if ident else [project/'lib']
    paths = [entry, *project.glob('*.py')]
    for root in roots:
        if root.exists():
            paths.extend(root.rglob('*.py'))
    result = {}
    for path in sorted(set(paths)):
        if '__pycache__' in path.parts:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
            raise ValueError('源码不能指向项目外部')
        result[path.relative_to(project).as_posix()] = path.read_text(encoding='utf-8-sig')
    return effective_sources(result)


def effective_sources(sources):
    result = dict(sources)
    for path, content in sources.items():
        if not path.startswith('charts/'):
            continue
        try:
            tree = ast.parse(content)
            values = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
                      if isinstance(n, ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0], ast.Name)
                      and n.targets[0].id in ('NATIVE_FIGURE', 'NATIVE_SOURCE_EDITS')}
            for relative, edits in values.get('NATIVE_SOURCE_EDITS', {}).items():
                target = 'lib/native/'+values['NATIVE_FIGURE']+'/'+relative
                if target not in result:
                    continue
                for edit in edits:
                    if not edit['old'] or result[target].count(edit['old'])!=1:
                        raise ValueError('局部源码锚点已失效')
                    result[target] = result[target].replace(edit['old'], edit['new'], 1)
        except (SyntaxError, ValueError, TypeError, KeyError, AttributeError):
            # Runtime will report invalid overrides. Never execute code for navigation.
            continue
    return result


def sections(path, content):
    lines = content.splitlines(keepends=True)
    try:
        tree = ast.parse(content)
    except SyntaxError:
        tree = None
    result = []
    # Contiguous chunks preserve the entire source, including comments and imports.
    for start in range(0, len(lines), 90):
        end = min(start+90, len(lines))
        names = []
        if tree:
            names = [node.name for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and node.lineno <= end and node.end_lineno > start]
        result.append({'path': path, 'start_line': start+1, 'end_line': end,
                       'symbols': names, 'id': f'{path}:{start+1}-{end}'})
    return result


def build_from_sources(sources, chart):
    catalog = []
    mappings = []
    reverse_mappings = []
    labels = set()
    function_labels = {}
    binding_lines = {}
    for path, content in sources.items():
        catalog.extend(sections(path, content))
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue
        for function in (n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            owned = {n.args[0].value for n in ast.walk(function) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == 'set_label' and n.args
                     and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)}
            function_labels[(path, function.name)] = owned
        binding_lines[path] = [(n.lineno, n.elts[0].value) for n in ast.walk(tree)
                               if isinstance(n, ast.Tuple) and len(n.elts)>=4
                               and isinstance(n.elts[0], ast.Constant) and isinstance(n.elts[0].value,str)
                               and isinstance(n.elts[1], ast.Constant) and isinstance(n.elts[1].value,str)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = {n.id for n in node.targets if isinstance(n, ast.Name)}
                if 'PUBLIC_PANEL_MEMBERS' in names:
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, (list, tuple))
                                and v and all(isinstance(a, str) for a in v) for k, v in value.items()):
                            mappings.append((path, value))
                    except (ValueError, TypeError):
                        pass
                elif names & {'DISPLAY_PANEL_MAP', 'PUBLIC_PANEL_MAP'}:
                    try:
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict) and value and all(isinstance(k,str) and isinstance(v,str) for k,v in value.items()):
                            public = {}
                            for axis, label in value.items():
                                public.setdefault(label, []).append(axis)
                            reverse_mappings.append((path, public))
                    except (ValueError, TypeError):
                        pass
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'set_label':
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    label = node.args[0].value
                    if re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,20}', label):
                        labels.add(label)
    panels = []
    if not mappings:
        mappings = reverse_mappings
    # Multiple conflicting declarations are ambiguous; never silently pick one.
    if mappings and all(value == mappings[0][1] for _, value in mappings):
        for public, members in mappings[0][1].items():
            refs = []
            for section in catalog:
                try:
                    snippet = read_range(sources, section)
                except ValueError:
                    continue
                if section['path'] == mappings[0][0] and (
                        'PUBLIC_PANEL_MEMBERS' in snippet or any(re.search(r"['\"]"+re.escape(axis)+r"['\"]", snippet) for axis in members)):
                    direct = any(function_labels.get((section['path'], name), set()) & set(members) for name in section['symbols'])
                    score = (100 if direct else 0)+sum(len(re.findall(r"['\"]"+re.escape(axis)+r"['\"]", snippet)) for axis in members)
                    if any(section['start_line']<=line<=section['end_line'] and axis in members for line,axis in binding_lines.get(section['path'], [])):
                        score += 80
                    if 'PUBLIC_PANEL_MEMBERS' in snippet or 'DISPLAY_PANEL_MAP =' in snippet:
                        score -= 50
                    refs.append((score, section['id']))
            panels.append({'id': public, 'label': '图 '+public, 'axis_labels': list(members),
                           'status': 'confirmed', 'mapping_source': mappings[0][0], 'source_sections': [ref for _,ref in sorted(refs,key=lambda r:-r[0])],
                           'note': '源码明确声明的可见面板映射；代码段可能包含共用逻辑。'})
    warning = '' if panels else '未找到可靠的可见面板映射。可查看完整源码；请手动指定面板与轴标签的对应关系。'
    return {'chart': chart, 'panels': panels, 'sections': catalog,
            'axis_label_candidates': sorted(labels), 'warning': warning,
            'source_hashes': {p: hashlib.sha256(c.encode()).hexdigest() for p, c in sources.items()}}


def build(project, chart):
    sources = source_files(project, chart)
    result = build_from_sources(sources, chart)
    manual = Path(project)/'panel-mappings'/f'{chart}.json'
    if manual.is_file():
        value = validate_mapping(json.loads(manual.read_text(encoding='utf-8')))
        result['panels'] = [{'id': k, 'label': '图 '+k, 'axis_labels': v, 'status': 'manual',
                             'source_sections': [s['id'] for s in result['sections']],
                             'note': '用户指定的对应关系，请结合预览核对。'} for k, v in value.items()]
        result['warning'] = ''
    target = Path(project)/'panel-index'/f'{chart}.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def validate_mapping(value):
    if not isinstance(value, dict) or len(value)>40 or not value:
        raise ValueError('请输入面板到轴标签的 JSON 对象，例如 {"a":["a","b"]}')
    for key, labels in value.items():
        if not isinstance(key, str) or not re.fullmatch(r'[\w-]{1,30}', key) or not isinstance(labels, list) or not labels:
            raise ValueError('面板名称和轴标签列表无效')
        if any(not isinstance(label, str) or not label or len(label)>80 for label in labels):
            raise ValueError('轴标签无效')
    return value


def read_range(sources, request):
    path = request.get('path')
    if path not in sources:
        raise ValueError('只能读取当前图已索引的源码')
    lines = sources[path].splitlines(keepends=True)
    start, end = request.get('start_line', 1), request.get('end_line', min(90, len(lines)))
    if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines) or end-start >= 240:
        raise ValueError('源码范围无效，每次最多读取 240 行')
    content = ''.join(lines[start-1:end])
    if len(content)>16000:
        raise ValueError('该代码段过长，请缩小读取范围')
    return content


def model_source_reads(sources, requests, budget=24000):
    """Normalize model ranges and page large reads without ending the edit turn."""
    result, feedback, remaining = [], [], []
    if not isinstance(requests, list):
        return [], ['source_requests must be an array of {path,start_line,end_line} objects.'], []
    if len(requests)>4:
        feedback.append('Only the first 4 source requests were processed; request others next.')
    for request in requests[:4]:
        if not isinstance(request, dict):
            feedback.append('Each source request must be an object.')
            continue
        path = request.get('path')
        if not isinstance(path, str):
            feedback.append('Source request is missing a string path from panel_index.sections.')
            continue
        if path not in sources:
            matches = [p for p in sources if p.endswith('/'+path)]
            if len(matches)==1:
                path = matches[0]
            else:
                feedback.append('Unknown or ambiguous source path: '+path+'. Choose an indexed path; no file was read.')
                continue
        lines = sources[path].splitlines(keepends=True)
        if not lines:
            feedback.append(path+' is an empty source file.')
            continue
        def number(value, default):
            if value is None:
                return default
            if type(value) is int:
                return value
            if isinstance(value, str) and re.fullmatch(r'\d+',value.strip()):
                return int(value.strip())
            raise ValueError('Line numbers must be integers or numeric strings.')
        try:
            start = max(1, number(request.get('start_line'), 1))
            end = number(request.get('end_line'), min(start+89, len(lines)))
            if request.get('symbol'):
                tree = ast.parse(sources[path])
                matches = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))
                           and n.name==request['symbol']]
                if len(matches)!=1:
                    raise ValueError('Symbol not uniquely found; choose a line range from the source index.')
                start, end = matches[0].lineno, matches[0].end_lineno
            if end<start or start>len(lines):
                raise ValueError(f'Invalid range {start}-{end}; file has {len(lines)} lines. Choose a range inside the file.')
            if end>len(lines):
                feedback.append(f'{path}: end_line {end} was clamped to actual EOF {len(lines)}.')
                end=len(lines)
        except (ValueError, SyntaxError) as error:
            feedback.append(path+': '+str(error))
            continue
        while start<=end:
            stop=start-1
            used=0
            while stop<end and stop-start+1<240:
                size=len(lines[stop])
                if used+size>min(16000,budget):
                    break
                used+=size
                stop+=1
            if stop<start:
                remaining.append({'path':path,'start_line':start,'end_line':end})
                feedback.append(f'{path}:{start}-{end} remains unread due to the per-call character budget; request a narrower range next.')
                break
            result.append({'path':path,'start_line':start,'end_line':stop,
                           'content':''.join(lines[start-1:stop]),'read_only':True,
                           'source_line_count':len(lines)})
            budget-=used
            start=stop+1
    return result,feedback,remaining


def local_edit(entry, path, old, new):
    """Store exact native source patches in the chart entry; originals stay frozen."""
    tree = ast.parse(entry)
    edits = {}
    assignment = next((n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'NATIVE_SOURCE_EDITS' for t in n.targets)), None)
    if assignment:
        edits = ast.literal_eval(assignment.value)
    edits.setdefault(path, []).append({'old': old, 'new': new})
    # repr preserves all strings without executing or interpolating their content.
    value = 'NATIVE_SOURCE_EDITS = '+repr(edits)+'\n'
    lines = entry.splitlines(keepends=True)
    if assignment:
        lines[assignment.lineno-1:assignment.end_lineno] = [value]
    else:
        lines.insert(0, value)
    entry = ''.join(lines)
    tree = ast.parse(entry)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == 'prepare_native']
    if len(calls)!=1:
        raise ValueError('该绘图入口没有唯一的原生绘制修改入口')
    call = calls[0]
    if not any(k.arg == 'source_edits' for k in call.keywords):
        lines = entry.splitlines(keepends=True)
        # Use byte offsets from AST correctly even when the entry has Chinese text.
        line = lines[call.end_lineno-1].encode('utf-8')
        pos = call.end_col_offset-1
        lines[call.end_lineno-1] = (line[:pos]+b', source_edits=NATIVE_SOURCE_EDITS'+line[pos:]).decode('utf-8')
        entry = ''.join(lines)
    ast.parse(entry)
    return entry


def check_panel_scope(report, panel):
    """Pixel check outside selected labeled axis regions; advisory, never a gate."""
    from PIL import Image, ImageChops
    import math
    labels = set(panel['axis_labels'])
    signatures = [report.get('baseline_layout_signature') or {}, report.get('layout_signature') or {}]
    boxes = []
    for signature in signatures:
        axes = signature.get('axes', [])
        found = {a.get('axis_label') for a in axes if a.get('axis_label') in labels and a.get('bbox_px')}
        if found != labels:
            return {'status':'unverified', 'warning':'尚未完成所选子图以外区域的像素比较，请审阅整张图。'}
        boxes.extend(a['bbox_px'] for a in axes if a.get('axis_label') in labels)
    try:
        with Image.open(report['baseline_image_path']) as before, Image.open(report['image_path']) as after:
            if before.size != after.size:
                return {'status':'review_required', 'warning':'整图尺寸发生变化，请核对所选子图以外的布局。'}
            diff = ImageChops.difference(before.convert('RGB'), after.convert('RGB'))
            width, height = after.size
            for x0,y0,x1,y1 in boxes:
                bounds = (max(0,math.floor(x0)-3), max(0,height-math.ceil(y1)-3),
                          min(width,math.ceil(x1)+3), min(height,height-math.floor(y0)+3))
                diff.paste((0,0,0), bounds)
            outside = diff.getbbox()
            if outside:
                return {'status':'review_required', 'outside_change_bbox':list(outside),
                        'warning':'所选子图的轴区域之外也有像素变化，可能涉及共享布局或外部标注，请核对整图。'}
            return {'status':'pass', 'basis':'所选子图轴区域之外的像素未变；此检查不验证科学含义。'}
    except (OSError, KeyError, TypeError, ValueError, OverflowError):
        return {'status':'unverified', 'warning':'缺少可比较的基线或子图边界，请审阅整张图。'}
