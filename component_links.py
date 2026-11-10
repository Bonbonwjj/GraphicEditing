"""Presentation links between distributions, observations and paired strokes."""
import numpy as np
from matplotlib.transforms import Transform


class LinkedVertexTransform(Transform):
    input_dims = output_dims = 2
    has_inverse = False
    is_separable = False
    pass_through = True

    def __init__(self, base, figure, vertices, shifts):
        super().__init__()
        self.base, self.figure = base, figure
        self.vertices, self.shifts = np.asarray(vertices), np.asarray(shifts)
        self.set_children(base, figure.dpi_scale_trans)

    def transform_non_affine(self, values):
        result = self.base.transform(values).copy()
        for vertex, shift in zip(self.vertices, self.shifts):
            matched = np.all(np.isclose(values, vertex, rtol=1e-10, atol=1e-12), axis=1)
            result[matched] += shift * self.figure.dpi / 72
        return result


def links(figure):
    from component_groups import component_groups, artist_key, summary_group_regions
    from point_components import layers
    groups = component_groups(figure)
    points = layers(figure)
    attached, regions = {}, {}
    for ai, axis in enumerate(figure.axes):
        categories = []
        for kind, field in (('box', '_component_point_regions'), ('violin', '_component_violin_point_regions')):
            for i, region in enumerate(getattr(axis, field, [])):
                identity = (region['dimension'], float(region['position']))
                if identity not in categories: categories.append(identity)
                key = f'axes_{ai}.{kind}_{i}'
                if key in groups: regions.setdefault((ai, categories.index(identity)), []).append((key, region))
        for name, entries in summary_group_regions(axis).items():
            for region in entries:
                identity = (region['dimension'], region['position'])
                if identity not in categories: categories.append(identity)
                key = f'axes_{ai}.{name}'
                if key in groups: regions.setdefault((ai,categories.index(identity)), []).append((key,region))
        for layer in points:
            if not layer['owner_key'].startswith(f'axes_{ai}.'): continue
            category = layer['point_group'].rsplit('.category_', 1)
            if len(category) == 2:
                for key, region in regions.get((ai, int(category[1])), []):
                    if layer['owner'] not in groups[key]: attached.setdefault(key, []).append(layer)
    excluded = {artist_key(figure, obj) for members in groups.values() for obj in members}
    candidates = []
    for ai, axis in enumerate(figure.axes):
        clouds = {}
        for layer in points:
            if layer['owner'].axes is not axis: continue
            owner = layer['owner']
            data = owner.get_offsets() if hasattr(owner, 'get_offsets') else owner.get_xydata()
            cloud = clouds.setdefault(layer['point_group'], [])
            cloud.extend(np.asarray(data)[layer['indices']])
        clouds = {identity: np.asarray(cloud) for identity, cloud in clouds.items()}
        for line in axis.lines:
            key = artist_key(figure, line)
            if key in excluded or getattr(line, '_component_point_overlay', False) or not line.get_visible(): continue
            if str(line.get_linestyle()).lower() in ('none', '', ' '): continue
            vertices = line.get_xydata()
            if not 2 <= len(vertices) <= 32 or not np.isfinite(vertices).all(): continue
            if len(vertices) == 4 and vertices[0,0] == vertices[1,0] and vertices[2,0] == vertices[3,0] and vertices[1,1] == vertices[2,1]: continue
            summary = any(layer['owner'] is line and layer['point_role'] == 'mean' for layer in points)
            identities = []
            for vertex in vertices:
                matches = []
                for identity, cloud in clouds.items():
                    # Category membership tolerates horizontal jitter, while
                    # the measured value must match a real observation.
                    category = identity.rsplit('.category_', 1)
                    if len(category) == 2:
                        info = regions.get((ai, int(category[1])), [])
                        if not info: continue
                        r = info[0][1]; d = r['dimension']
                        peers = [v[0][1]['position'] for (a, _), v in regions.items() if a == ai and v[0][1]['dimension'] == d]
                        spacing = min(np.diff(sorted(set(peers)))) if len(set(peers)) > 1 else 1
                        if abs(vertex[1-d]-r['position']) > spacing*.45: continue
                        if np.isclose(vertex[d], cloud[:,d], rtol=1e-8, atol=1e-10).any(): matches.append(identity)
                    elif np.isclose(vertex, cloud, rtol=1e-8, atol=1e-10).all(axis=1).any(): matches.append(identity)
                if not matches: break
                identities.append(matches[0])
            if len(identities) != len(vertices): continue
            # Marked Line2D objects can each contain an entire paired row.
            # Repeated category coordinates identify their common cohorts.
            if len(set(identities)) < 2:
                own = [p for p in points if p['owner'] is line and p['point_role'] == 'regular']
                if not own: continue
                coordinates = vertices[:,0]
                if len(set(coordinates)) < 2: continue
                identities = [f'axes_{ai}.x={x:g}' for x in coordinates]
            label = line.get_label()
            from matplotlib.colors import to_hex
            candidates.append({'key': key, 'artist': line, 'vertices': vertices.copy(), 'groups': identities,
                               'axis': ai, 'color': to_hex(line.get_color()), 'summary': summary,
                               'label': label if label and not label.startswith('_') else ''})
    named = {}
    for item in candidates:
        if item['summary']: continue
        if item['label']: named.setdefault((item['axis'], item['color']), set()).add(item['label'])
    families = []
    for item in candidates:
        if item['summary']: continue
        names = named.get((item['axis'], item['color']), set())
        cohort = item['label'] or (next(iter(names)) if len(names) == 1 else '')
        matching = [f for f in families if f['axis'] == item['axis'] and f['cohort'] == cohort and f['groups'].intersection(item['groups'])]
        family = matching[0] if matching else {'axis': item['axis'], 'cohort': cohort, 'groups': set(), 'items': []}
        if not matching: families.append(family)
        for other in matching[1:]:
            family['groups'].update(other['groups']); family['items'].extend(other['items']); families.remove(other)
        family['groups'].update(item['groups']); family['items'].append(item)
    return attached, regions, candidates, [f['items'] for f in families if len(f['items']) > 1]


def point_movement_links(figure, linkage):
    """Use the same cohort identities for point and paired-line movement."""
    from point_components import layers
    samples=[p for p in layers(figure) if p['point_role'] in ('regular','outliers')]
    by_group={}
    for point in samples: by_group.setdefault(point['point_group'],[]).append(point['key'])
    connectors=[item for item in linkage[2] if not item['summary']]
    families=list(linkage[3])
    covered={item['key'] for family in families for item in family}
    families.extend([item] for item in connectors if item['key'] not in covered)
    point_members={p['key']:by_group[p['point_group']] for p in samples}
    connector_members={};vertices={}
    for family in families:
        owners={item['key'] for item in family}
        standalone=any('.x=' in identity for item in family for identity in item['groups'])
        identities={identity for item in family for identity in item['groups']}
        points=[p['key'] for p in samples if p['point_group'] in identities or (standalone and p['owner_key'] in owners)]
        for item in family:
            connector_members[item['key']]=[other['key'] for other in family]
            point_members[item['key']]=points
            vertices[item['key']]=[by_group.get(identity,points if standalone else []) for identity in item['groups']]
        if standalone:
            for key in points: point_members[key]=points
    return point_members,connector_members,vertices


def expand_point_movement(figure, styles, point_specs, linkage):
    candidates={item['key'] for item in linkage[2] if not item['summary']}
    if not any({'dx','dy'}.intersection(spec) for key,spec in {**styles,**point_specs}.items() if key in candidates or key in point_specs):
        return set()
    members,connectors,_=point_movement_links(figure,linkage)
    sources={**styles,**point_specs}
    for key,spec in sources.items():
        motion={field:spec[field] for field in ('dx','dy') if field in spec}
        if not motion: continue
        for peer in members.get(key,[]):
            point_specs[peer]={**point_specs.get(peer,{}),**motion}
    return set(connectors)


def apply_linked_moves(figure, styles, point_specs, linkage, annotations=None):
    attached, regions, connectors, _families = linkage
    from matplotlib.transforms import ScaledTranslation
    # Category ticks stay on their axis baseline, following only the movement
    # along that axis. Numerical ticks and the neighboring categories stay put.
    for (ai, _category), entries in regions.items():
        active = [styles[key] for key, _ in entries if styles.get(key, {}).get('dx') or styles.get(key, {}).get('dy')]
        if not active: continue
        region = entries[0][1]
        vertical = region['dimension'] == 1
        delta = active[-1].get('dx' if vertical else 'dy', 0)
        if not delta: continue
        axis_obj = figure.axes[ai].xaxis if vertical else figure.axes[ai].yaxis
        shift = ScaledTranslation(delta/72 if vertical else 0, 0 if vertical else delta/72, figure.dpi_scale_trans)
        for tick in axis_obj.get_major_ticks():
            if not np.isclose(tick.get_loc(), region['position'], rtol=1e-8, atol=1e-10): continue
            for artist in (tick.tick1line, tick.tick2line, tick.label1, tick.label2, tick.gridline):
                artist.set_transform(artist.get_transform() + shift)
    _move_category_spines(figure, styles, regions)
    if annotations: _move_annotations(figure,styles,annotations)
    moved = {}
    point_motion={key:{field:spec.get(field,0) for field in ('dx','dy')} for key,spec in point_specs.items() if {'dx','dy'}.intersection(spec)}
    point_vertices=point_movement_links(figure,linkage)[2] if point_motion else {}
    connector_owners = {id(item['artist']) for item in connectors}
    for key, layers in attached.items():
        shift = {field: styles.get(key, {}).get(field, 0) for field in ('dx', 'dy')}
        if not any(shift.values()): continue
        for layer in layers:
            if id(layer['owner']) in connector_owners: continue
            # Box and violin layers may describe the same category.
            if moved.get(layer['key']) == shift: continue
            moved[layer['key']] = shift
            spec = point_specs.setdefault(layer['key'], {})
            for field, value in shift.items(): spec[field] = spec.get(field, 0) + value
    for item in connectors:
        shifts = []
        for index,identity in enumerate(item['groups']):
            category = identity.rsplit('.category_', 1)
            keys = [key for key, _ in regions.get((item['axis'], int(category[1])), [])] if len(category) == 2 else []
            active = [styles[key] for key in keys if styles.get(key, {}).get('dx') or styles.get(key, {}).get('dy')]
            peers=point_vertices.get(item['key'],[])
            extra=[point_motion[key] for key in (peers[index] if index<len(peers) else []) if key in point_motion]
            shifts.append([(active[-1].get(field,0) if active else 0)+(extra[-1].get(field,0) if extra else 0) for field in ('dx','dy')])
        if not np.any(shifts): continue
        line = item['artist']
        line.set_transform(LinkedVertexTransform(line.get_transform(), figure, item['vertices'], shifts))
        line.set_clip_on(False)
    # Markers owned by paired Line2D objects already follow the vertex transform.
    # Preserve their independent style overrides without applying movement twice.
    from point_components import layers as point_layers
    for layer in point_layers(figure):
        if id(layer['owner']) in connector_owners and layer['point_role'] in ('regular','outliers'):
            for field in ('dx','dy'): point_specs.get(layer['key'],{}).pop(field,None)


def capture_annotation_links(figure, regions):
    """Bind statistical labels and brackets by their rendered category anchors."""
    import re
    from component_groups import artist_key, component_groups
    statistical_members={id(obj) for members in component_groups(figure).values() for obj in members}
    result=[]
    for ai,axis in enumerate(figure.axes):
        anchors={}
        for (owner,index),entries in regions.items():
            if owner!=ai: continue
            r=entries[0][1];d=1-r['dimension']
            p=np.array([axis.get_xlim()[0],axis.get_ylim()[0]],dtype=float);p[d]=r['position']
            anchors.setdefault(d,[]).append((axis.transData.transform(p)[d],[key for key,_ in entries]))
        texts=[]
        for i,text in enumerate(axis.texts):
            value=re.sub(r'\\(?:mathrm|mathregular|text)\s*','',text.get_text())
            value=value.replace('$','').replace('\\ast','*').replace('{','').replace('}','').replace('^','').strip()
            if re.fullmatch(r'[*✱✳]+|n\s*\.?\s*s\.?|[pP]\s*(?:[<=>≤≥]|\\[lg]eq).+',value,re.I):
                texts.append((text,f'axes_{ai}.annotation_{i}',text.get_transform().transform(text.get_position())))
        if not texts:continue
        used=set()
        for d,items in anchors.items():
            q=1-d;items=sorted(items,key=lambda item:item[0])
            spacing=min(np.diff(sorted(set(p for p,_ in items)))) if len(set(p for p,_ in items))>1 else axis.bbox.size[d]
            tolerance=max(3,spacing*.22)
            def closest(value):
                anchor=min(items,key=lambda item:abs(item[0]-value))
                return anchor[1] if abs(anchor[0]-value)<=tolerance else None
            def priority(line):
                vertices=line.get_xydata()
                if len(vertices) not in (2,4):return (2,float('inf'))
                p=line.get_transform().transform(vertices).mean(axis=0)
                distance=min(abs(pos[q]-p[q])+abs(pos[d]-p[d]) for _,_,pos in texts)
                return (0 if len(vertices)==4 else 1,distance)
            for line in sorted(axis.lines,key=priority):
                if id(line) in statistical_members or getattr(line,'_component_point_overlay',False) or not line.get_visible():continue
                vertices=line.get_xydata()
                if len(vertices) not in (2,4) or not np.isfinite(vertices).all():continue
                p=line.get_transform().transform(vertices)
                bracket=(len(p)==4 and np.isclose(p[0,d],p[1,d]) and np.isclose(p[2,d],p[3,d]) and np.isclose(p[1,q],p[2,q]))
                horizontal=len(p)==2 and np.isclose(p[0,q],p[1,q])
                if not (bracket or horizontal) or np.ptp(p[:,d])<1:continue
                left,right=p[:,d].min(),p[:,d].max();ends=[closest(left),closest(right)]
                if not all(ends):continue
                center=(left+right)/2;level=p[:,q].mean()
                near=[(abs(pos[q]-level)+abs(pos[d]-center),text,key) for text,key,pos in texts
                      if key not in used and abs(pos[d]-center)<=max(8,np.ptp(p[:,d])*.18)
                      and abs(pos[q]-level)<=figure.dpi*.6]
                if not near:continue
                _,text,text_key=min(near,key=lambda item:item[0]);used.add(text_key)
                side=1 if level>=axis.bbox.min[q]+axis.bbox.size[q]/2 else -1
                weights=((p[:,d]-left)/(right-left)).tolist()
                model={'category_dimension':d,'participants':ends,'quantitative_side':side,'shared_quantitative':True}
                result.append({'artist':line,'key':artist_key(figure,line),'vertices':vertices.copy(),'weights':weights,**model})
                result.append({'artist':text,'key':text_key,'weights':[.5],**model})
            for text,key,pos in texts:
                if key in used:continue
                group=closest(pos[d])
                if group:
                    used.add(key)
                    result.append({'artist':text,'key':key,'weights':[0.], 'category_dimension':d,
                        'participants':[group,group],'quantitative_side':1,'shared_quantitative':False})
    return result


def _annotation_model(item, styles):
    model={key:item[key] for key in ('key','weights','category_dimension','participants','quantitative_side','shared_quantitative')}
    shifts=[]
    for keys in item['participants']:
        active=[styles[key] for key in keys if styles.get(key,{}).get('dx') or styles.get(key,{}).get('dy')]
        shifts.append([active[-1].get(field,0) if active else 0 for field in ('dx','dy')])
    model['participant_shifts']=shifts
    return model


def _move_annotations(figure,styles,annotations):
    from matplotlib.text import Text
    from matplotlib.transforms import ScaledTranslation
    for item in annotations:
        model=_annotation_model(item,styles);shifts=np.asarray(model['participant_shifts']);d=item['category_dimension'];q=1-d
        item['artist']._component_annotation_link=model
        if not np.any(shifts):continue
        quantitative=(shifts[:,q].max() if item['quantitative_side']>0 else shifts[:,q].min()) if item['shared_quantitative'] else shifts[0,q]
        moves=np.zeros((len(item['weights']),2))
        moves[:,d]=[(1-w)*shifts[0,d]+w*shifts[1,d] for w in item['weights']];moves[:,q]=quantitative
        artist=item['artist']
        if isinstance(artist,Text):
            artist.set_transform(artist.get_transform()+ScaledTranslation(moves[0,0]/72,moves[0,1]/72,figure.dpi_scale_trans))
        else:artist.set_transform(LinkedVertexTransform(artist.get_transform(),figure,item['vertices'],moves))
        artist.set_clip_on(False)


def _move_category_spines(figure, styles, regions):
    """Follow the outer moved categories, preserving authored end margins."""
    from matplotlib.transforms import ScaledTranslation
    coordinates = {}
    for (ai, _), entries in regions.items():
        region = entries[0][1]
        dimension = 1-region['dimension']
        field = 'dx' if dimension == 0 else 'dy'
        active = [styles[key] for key, _ in entries if styles.get(key, {}).get('dx') or styles.get(key, {}).get('dy')]
        delta = active[-1].get(field, 0) if active else 0
        coordinates.setdefault((ai, dimension), []).append((region['position'], delta))
    for (ai, dimension), categories in coordinates.items():
        if not any(delta for _, delta in categories): continue
        axis = figure.axes[ai]
        # Use a valid reference coordinate on the numerical axis (also on log axes).
        reference = np.array([axis.get_xlim()[0], axis.get_ylim()[0]], dtype=float)
        points = np.tile(reference, (len(categories), 1))
        points[:,dimension] = [position for position, _ in categories]
        original = axis.transData.transform(points)[:,dimension]
        moved = original + np.array([delta for _, delta in categories])*figure.dpi/72
        end_shifts = np.array([moved.min()-original.min(), moved.max()-original.max()])
        for side in (('bottom', 'top') if dimension == 0 else ('left', 'right')):
            spine = axis.spines[side]
            bounds = spine.get_bounds()
            if bounds is None: bounds = axis.get_xlim() if dimension == 0 else axis.get_ylim()
            endpoints = np.tile(reference, (2, 1)); endpoints[:,dimension] = bounds
            display = axis.transData.transform(endpoints)
            order = np.argsort(display[:,dimension])
            display[order,dimension] += end_shifts
            updated = axis.transData.inverted().transform(display)[:,dimension]
            spine.set_bounds(*sorted(updated))
        # Keep the axis title centered relative to the changed visible line.
        offset = float(end_shifts.mean())/figure.dpi
        title = (axis.xaxis if dimension == 0 else axis.yaxis).label
        title.set_transform(title.get_transform() + ScaledTranslation(offset if dimension == 0 else 0,
                            offset if dimension == 1 else 0, figure.dpi_scale_trans))


def report_links(figure, records, grouped):
    linkage=links(figure)
    attached, regions, _connectors, families = linkage
    point_members,connector_members,vertices=point_movement_links(figure,linkage)
    for record in records:
        if record['key'] in point_members: record['point_move_members']=point_members[record['key']]
        if record['key'] in connector_members: record['move_connection_members']=connector_members[record['key']]
        if record['key'] in vertices: record['point_move_vertices']=vertices[record['key']]
    annotations={item['key']:_annotation_model(item,{}) for item in capture_annotation_links(figure,regions)}
    for axis in figure.axes:
        for artist in [*axis.lines,*axis.texts]:
            model=getattr(artist,'_component_annotation_link',None)
            if model:annotations[model['key']]=model
    for group in grouped:
        group['move_members'] = [layer['key'] for layer in attached.get(group['key'], [])]
        group['annotation_links']=[model for model in annotations.values() if any(group['key'] in keys for keys in model['participants'])]
        group['category_anchors']=[{'dimension':1-entries[0][1]['dimension'],'position':entries[0][1]['position']}
                                 for entries in regions.values() if any(key==group['key'] for key,_ in entries)]
        axis=figure.axes[int(group['key'].split('.')[0][5:])]
        for anchor in group['category_anchors']:
            d=anchor['dimension'];axis_obj=axis.xaxis if d==0 else axis.yaxis
            anchor['tick_keys']=[];anchor['tick_paths_px']=[]
            for i,tick in enumerate(axis_obj.get_major_ticks()):
                if not np.isclose(tick.get_loc(),anchor['position']):continue
                for side,label,line in ((1,tick.label1,tick.tick1line),(2,tick.label2,tick.tick2line)):
                    if label.get_visible():anchor['tick_keys'].append(f"{group['key'].split('.')[0]}.{'x' if d==0 else 'y'}tick_major_{i}_{side}")
                    if line.get_visible():
                        p=line.get_transform().transform(line.get_path().vertices)[0]
                        vector={0:(-1,0),1:(1,0),2:(0,1),3:(0,-1)}.get(line.get_marker(),(0,0))
                        anchor['tick_paths_px'].append([p.tolist(),(p+np.array(vector)*line.get_markersize()*figure.dpi/72).tolist()])
    lookup = {record['key']: record for record in records}
    for family in families:
        members = [item['key'] for item in family]
        for key in members:
            if key in lookup: lookup[key]['connection_members'] = members
    for axis in figure.axes:
        for line in axis.lines:
            members = getattr(line, '_component_connection_members', None)
            if members:
                from component_groups import artist_key
                key = artist_key(figure, line)
                if key in lookup: lookup[key]['connection_members'] = members
