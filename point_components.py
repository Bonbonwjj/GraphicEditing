"""Selectable mean/sample/outlier layers. Styling never rewrites observations."""
import copy
import re
import numpy as np
from matplotlib.collections import PathCollection
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.colors import to_rgba,to_rgba_array

MARKERS=('o','s','D','d','^','v','<','>','P','X','+','x','*','.')


def _marked(obj):
    return str(obj.get_marker()).lower() not in ('none','',' ','null')


def _owners(axis):
    for prefix,items in (('line',axis.lines),('collection',axis.collections)):
        for index,obj in enumerate(items):
            if getattr(obj,'_component_point_overlay',False):continue
            if isinstance(obj,Line2D):
                if not _marked(obj) or obj.get_marker() in ('_','|',0,1,2,3):continue
                data=np.column_stack((obj.get_xdata(orig=False),obj.get_ydata(orig=False)))
            elif isinstance(obj,PathCollection):data=np.ma.asarray(obj.get_offsets()).filled(np.nan)
            else:continue
            if obj.get_visible() and len(data):yield f'{prefix}_{index}',obj,np.asarray(data,dtype=float)


def layers(figure):
    result=[]
    for ai,axis in enumerate(figure.axes):
        owners=list(_owners(axis))
        from component_groups import summary_group_regions
        regions=(getattr(axis,'_component_point_regions',[]) or getattr(axis,'_component_violin_point_regions',[])
                 or [r for items in summary_group_regions(axis).values() for r in items])
        categories=[];category_indexes=[]
        for region in regions:
            identity=(region['dimension'],float(region['position']))
            if identity not in categories:categories.append(identity)
            category_indexes.append(categories.index(identity))
        # Standalone scatter means are common in publication violin plots.
        # Exact summary coordinates distinguish them from full sample series;
        # same-style singleton sample artists are deliberately not reclassified.
        for key,obj,data in owners:
            if not isinstance(obj,PathCollection) or hasattr(obj,'_component_inferred_mean'):continue
            summary=bool(regions and len(data)<=len(regions))
            for p in data:
                if not summary or not np.isfinite(p).all():summary=False;break
                r=min(regions,key=lambda r:abs(p[1-r['dimension']]-r['position']))
                summary=bool(r.get('mean') is not None and np.isclose(p[r['dimension']],r['mean'],rtol=1e-6,atol=1e-8)
                    and np.isclose(p[1-r['dimension']],r['position'],atol=1e-6))
            if summary and len(data)==1:
                for other_key,other,other_data in owners:
                    if other is obj or not isinstance(other,PathCollection) or len(other_data)!=1:continue
                    same_category=abs(other_data[0,1-r['dimension']]-r['position'])<.25
                    a,b=obj.get_paths()[0].vertices,other.get_paths()[0].vertices
                    same_style=(a.shape==b.shape and np.allclose(a,b) and np.array_equal(obj.get_sizes(),other.get_sizes()))
                    if same_category and same_style:summary=False;break
            obj._component_inferred_mean=summary
        buckets={i:[] for i in range(len(regions))}
        assigned={}
        for key,obj,data in owners:
            indexes=np.full(len(data),-1,dtype=int)
            for j,p in enumerate(data):
                if not np.isfinite(p).all() or not regions:continue
                distances=[abs(p[1-r['dimension']]-r['position']) for r in regions]
                indexes[j]=int(np.argmin(distances))
                r=regions[indexes[j]]
                mean_marker=(isinstance(obj,Line2D) and r.get('mean') is not None and len(data)<=max(1,len(regions))
                    and np.isclose(p[r['dimension']],r['mean'],rtol=1e-6,atol=1e-8)
                    and np.isclose(p[1-r['dimension']],r['position'],atol=1e-6))
                if len(data)>1 and not getattr(obj,'_component_point_role',None) and not mean_marker and not getattr(obj,'_component_inferred_mean',False):
                    buckets[indexes[j]].append(p[regions[indexes[j]]['dimension']])
            assigned[key]=indexes
        for key,obj,data in owners:
            role=getattr(obj,'_component_point_role',None);roles=[]
            for j,p in enumerate(data):
                if not np.isfinite(p).all():roles.append(None);continue
                r=regions[assigned[key][j]] if assigned[key][j]>=0 else None
                is_mean=(isinstance(obj,Line2D) and r and r.get('mean') is not None and len(data)<=max(1,len(regions))
                    and np.isclose(p[r['dimension']],r['mean'],rtol=1e-6,atol=1e-8)
                    and np.isclose(p[1-r['dimension']],r['position'],atol=1e-6))
                current=role or ('mean' if is_mean or getattr(obj,'_component_inferred_mean',False) else 'regular')
                if current=='regular' and r:
                    lo,hi=r.get('low'),r.get('high')
                    if lo is None and len(buckets[assigned[key][j]])>=4:
                        q1,q3=np.percentile(buckets[assigned[key][j]],[25,75]);lo=q1-1.5*(q3-q1);hi=q3+1.5*(q3-q1)
                    if lo is not None and (p[r['dimension']]<lo-1e-10 or p[r['dimension']]>hi+1e-10):current='outliers'
                roles.append(current)
            owner_key=f'axes_{ai}.{key}'
            for current in ('regular','outliers','mean'):
                indexes=[i for i,r in enumerate(roles) if r==current]
                grouped={}
                for index in indexes:
                    region_index=assigned[key][index]
                    category=category_indexes[region_index] if region_index>=0 else None
                    grouped.setdefault(category,[]).append(index)
                # Artist ownership is not group identity: one scatter call can
                # contain multiple categories, or a category can span artists.
                subsets=[(category,[i]) for category,items in grouped.items() for i in items] if current=='mean' else list(grouped.items())
                for category,selected in subsets:
                    if not selected:continue
                    suffix=current+('_'+str(selected[0]) if current=='mean' else '')
                    if current!='mean' and len(grouped)>1:suffix+='_g'+str(category)
                    group=owner_key if category is None else f'axes_{ai}.category_{category}'
                    label=str(obj.get_label()) if not str(obj.get_label()).startswith('_') else ''
                    if category is not None:
                        dimension,position=categories[category]
                        ticks=axis.get_yticks() if dimension==0 else axis.get_xticks()
                        labels=axis.get_yticklabels() if dimension==0 else axis.get_xticklabels()
                        label=next((text.get_text() for value,text in zip(ticks,labels) if np.isclose(value,position)),str(position))
                    result.append({'key':owner_key+'.points_'+suffix,'owner_key':owner_key,'owner':obj,
                        'indices':np.asarray(selected,dtype=int),'point_role':current,
                        'point_group':group,'point_group_label':label,
                        'rule':'original_whiskers' if getattr(axis,'_component_point_regions',[]) else 'display_iqr' if regions else None})
    return result


def _expand(values,count,default):
    values=np.asarray(values)
    if not len(values):values=np.asarray([default])
    return np.asarray([values[i%len(values)] for i in range(count)])


def _marker_name(path):
    for name in MARKERS:
        marker=MarkerStyle(name);candidate=marker.get_path().transformed(marker.get_transform())
        if path.vertices.shape==candidate.vertices.shape and np.allclose(path.vertices,candidate.vertices):return name
    return 'o'


def _line_color(obj,field):
    value=getattr(obj,'get_marker'+field+'color')()
    if isinstance(value,str) and value=='auto':value=obj.get_color()
    return to_rgba(value,obj.get_alpha())


def targets(figure,records):
    output=[];lookup={r['key']:r for r in records}
    for layer in layers(figure):
        obj=layer['owner'];index=layer['indices'];display=getattr(obj,'_component_point_displays',{}).get(layer['key'],obj)
        if isinstance(display,Line2D):
            xy=np.column_stack((display.get_xdata(orig=False),display.get_ydata(orig=False)))
            points=display.get_transform().transform(xy)
            if display is obj:points=points[index]
            style={'marker_shape':display.get_marker(),'marker_size':display.get_markersize(),
                'fill_color':_line_color(display,'face'),'edge_color':_line_color(display,'edge'),
                'linewidth':display.get_markeredgewidth()}
        else:
            points=display.get_offset_transform().transform(display.get_offsets())
            ii=index if display is obj else np.arange(len(points))
            points=points[ii];colors=_expand(display.get_facecolors(),len(display.get_offsets()),(0,0,0,0))
            edges=_expand(display.get_edgecolors(),len(display.get_offsets()),(0,0,0,0))
            paths=display.get_paths();sizes=_expand(display.get_sizes(),len(display.get_offsets()),36)
            style={'marker_shape':_marker_name(paths[int(ii[0])%len(paths)]),'marker_size':float(np.sqrt(sizes[ii[0]])),
                'fill_color':colors[ii[0]].tolist(),'edge_color':edges[ii[0]].tolist(),
                'linewidth':float(_expand(display.get_linewidths(),len(display.get_offsets()),0)[ii[0]])}
        owner=lookup.get(layer['owner_key'],{})
        output.append({k:layer[k] for k in ('key','owner_key','point_role','point_group','point_group_label','rule')}|{
            'kind':'scatter','label':{'mean':'均值点','regular':'普通散点','outliers':'离群点'}[layer['point_role']],
            'group_key':owner.get('group_key'),'hit_path_px':np.asarray(points)[np.linspace(0,len(points)-1,min(5000,len(points)),dtype=int)].tolist(),
            'style':style,'point_count':len(points)})
    return output


def apply_points(figure,specs):
    definitions={p['key']:p for p in layers(figure)}
    # Keep previously saved broad styles as the baseline, then apply the new
    # category-specific overrides. Opening an old project must not restyle it.
    expanded={}
    for key,spec in specs.items():
        match=re.fullmatch(r'(axes_\d+\.(?:line|collection)_\d+)\.points_(regular|outliers)',key)
        if key not in definitions and match:
            for layer in definitions.values():
                if layer['owner_key']==match[1] and layer['point_role']==match[2]:expanded[layer['key']]=dict(spec)
    for key,spec in specs.items():
        if key in definitions:expanded[key]={**expanded.get(key,{}),**spec}
    specs=expanded
    for key,spec in specs.items():
        layer=definitions.get(key)
        if not layer:continue
        obj=layer['owner'];indices=layer['indices'];color=spec.get('color')
        if isinstance(obj,Line2D):
            # Separate marker presentation from the original connecting stroke.
            xy=np.column_stack((obj.get_xdata(orig=False),obj.get_ydata(orig=False)))
            display=Line2D(xy[indices,0],xy[indices,1],linestyle='None',marker=obj.get_marker(),
                markersize=obj.get_markersize(),markerfacecolor=_line_color(obj,'face'),markeredgecolor=_line_color(obj,'edge'),
                markeredgewidth=obj.get_markeredgewidth(),transform=obj.get_transform(),zorder=obj.get_zorder()+.001)
            display._component_point_overlay=True;display.set_label('_nolegend_');obj.axes.add_line(display)
            hidden=set(getattr(obj,'_component_hidden_marker_indices',set()))|set(indices.tolist())
            obj._component_hidden_marker_indices=hidden
            obj.set_markevery([i for i in range(len(xy)) if i not in hidden])
            if 'marker_shape' in spec:display.set_marker(spec['marker_shape'])
            display.set_markersize(spec.get('marker_size',display.get_markersize())*spec.get('scale',1))
            for field,setter in (('fill_color',display.set_markerfacecolor),('edge_color',display.set_markeredgecolor)):
                value=spec.get(field,color)
                base=_line_color(obj,'face' if field=='fill_color' else 'edge')
                alpha=spec.get('fill_alpha' if field=='fill_color' else 'edge_alpha',spec.get('alpha',base[3]))
                if value is not None:setter(to_rgba(value,alpha))
                elif 'alpha' in spec or ('fill_alpha' if field=='fill_color' else 'edge_alpha') in spec:setter((*base[:3],alpha))
            if 'linewidth' in spec:display.set_markeredgewidth(spec['linewidth'])
            if 'alpha' in spec:display.set_alpha(spec['alpha'])
        else:
            count=len(obj.get_offsets());display=obj
            faces=_expand(obj.get_facecolors(),count,(0,0,0,0));edges=_expand(obj.get_edgecolors(),count,(0,0,0,0))
            for field,values in (('fill_color',faces),('edge_color',edges)):
                value=spec.get(field,color)
                if value is not None:values[indices,:3]=to_rgba(value)[:3]
                alpha=spec.get('fill_alpha' if field=='fill_color' else 'edge_alpha',spec.get('alpha'))
                if alpha is not None:values[indices,3]=alpha
            if spec.get('hidden'):faces[indices,3]=0;edges[indices,3]=0
            if any(name in spec for name in ('color','fill_color','edge_color','alpha','fill_alpha','edge_alpha','hidden','dx','dy')):
                obj.set_alpha(None);obj.set_facecolors(faces);obj.set_edgecolors(edges)
            if 'marker_size' in spec or 'scale' in spec:
                sizes=_expand(obj.get_sizes(),count,36);sizes[indices]=spec.get('marker_size',np.sqrt(sizes[indices]))**2*spec.get('scale',1)**2;obj.set_sizes(sizes)
            if 'linewidth' in spec:
                widths=_expand(obj.get_linewidths(),count,1);widths[indices]=spec['linewidth'];obj.set_linewidths(widths)
            if 'marker_shape' in spec:
                paths=list(obj.get_paths());paths=[paths[i%len(paths)] for i in range(count)]
                marker=MarkerStyle(spec['marker_shape']);path=marker.get_path().transformed(marker.get_transform())
                for i in indices:paths[i]=path
                obj.set_paths(paths)
            if spec.get('dx') or spec.get('dy'):
                # Overlay only the moved subset; the source offsets stay intact.
                display=copy.copy(obj);display._component_point_overlay=True;display.set_label('_nolegend_')
                display.set_offsets(np.asarray(obj.get_offsets())[indices].copy());display.set_sizes(_expand(obj.get_sizes(),count,36)[indices])
                display.set_paths([obj.get_paths()[i%len(obj.get_paths())] for i in indices])
                display.set_facecolors(faces[indices]);display.set_edgecolors(edges[indices]);display.set_linewidths(_expand(obj.get_linewidths(),count,1)[indices])
                obj.axes.add_collection(display,autolim=False);faces[indices,3]=0;edges[indices,3]=0
                obj.set_facecolors(faces);obj.set_edgecolors(edges)
        if spec.get('dx') or spec.get('dy'):
            from matplotlib.transforms import ScaledTranslation
            offset=ScaledTranslation(spec.get('dx',0)/72,spec.get('dy',0)/72,figure.dpi_scale_trans)
            display.set_clip_on(False)
            if isinstance(display,PathCollection):display.set_offset_transform(display.get_offset_transform()+offset)
            else:display.set_transform(display.get_transform()+offset)
        if isinstance(display,Line2D) or display is not obj:display.set_visible(not spec.get('hidden',False))
        displays=getattr(obj,'_component_point_displays',{});displays[key]=display;obj._component_point_displays=displays
