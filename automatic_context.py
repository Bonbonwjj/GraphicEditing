"""Resolve technical context from the pinned local snapshot, not user guesses."""
import ast
import json
from pathlib import PurePosixPath
import re


def technical_context_request(response):
    if response.get('status')=='needs_context':return True
    if response.get('status')!='needs_clarification':return False
    text=str(response.get('reason',''))+' '+str(response.get('question',''))
    technical=bool(re.search(r'源码|源代码|函数|文件路径|数组变量|输入读取|读取映射|source code|function name|file path|source_requests',text,re.I))
    decision=bool(re.search(r'哪张图|哪个子图|研究问题|检验方法|检验方式|配对还是独立|颜色方案|which (?:chart|panel)|scientific intent',text,re.I))
    return technical and not decision


def input_mappings(files):
    result=[];remaining=16000
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('original','original_path','content','rows','samples','observations','values')}
        if isinstance(value,list):
            # Mapping descriptors/schema only; numerical arrays remain local.
            if all(isinstance(v,dict) for v in value):return [clean(v) for v in value if any(k in v for k in ('path','file','name','id','format','sha256'))]
            return value if all(isinstance(v,str) for v in value) else []
        return value
    for path,item in sorted(files.items()):
        if not re.search(r'(?:input.*map|data.*map|manifest|native-project|universal-project)\.json$',path,re.I):continue
        try:value=clean(json.loads(item['content']))
        except (ValueError,KeyError):continue
        text=json.dumps(value,ensure_ascii=False)
        if len(text)>remaining:continue
        result.append({'path':path,'sha256':item['sha256'],'mapping':value,'read_only':True})
        remaining-=len(text)
    return result


def infer_source_requests(context, reason, supplied=()):
    """Rank unseen real source ranges by entry dependencies and requested topic."""
    from panel_index import effective_sources
    reason=str(reason or '')
    sources=effective_sources({item['path']:item['content'] for item in context.get('source_files',[])})
    indexes={}
    for path in sources:indexes.setdefault(PurePosixPath(path).stem,[]).append(path)
    writable=set(context.get('allowed_write_paths',[]));distance={p:0 for p in writable if p in sources}
    queue=list(distance)
    while queue:
        path=queue.pop(0)
        if distance[path]>=4:continue
        try:tree=ast.parse(sources[path])
        except SyntaxError:continue
        modules=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):modules.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module:modules.append(node.module.split('.')[0])
            elif isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.endswith('.py'):
                modules.append(PurePosixPath(node.value).stem)
        for module in modules:
            for candidate in indexes.get(module,[]):
                if candidate not in distance:distance[candidate]=distance[path]+1;queue.append(candidate)
    text=str(reason)+' '+context.get('user_message','')
    distribution=bool(re.search(r'箱|提琴|样本|分组|box|violin|sample|group',text,re.I))
    limits=bool(re.search(r'范围|坐标|最终|绘制|range|limit|final|draw',text,re.I))
    readers=bool(re.search(r'读取|输入|数据|映射|read|input|data|mapping',text,re.I))
    seen={}
    for item in supplied:
        if isinstance(item,dict) and item.get('path') in sources:
            seen.setdefault(item['path'],[]).append((item.get('start_line',1),item.get('end_line',0)))
    ranked=[]
    for path,source in sources.items():
        if path in writable:continue
        try:tree=ast.parse(source)
        except SyntaxError:continue
        candidates=[(1,min(90,len(source.splitlines())),'imports',tree)]
        candidates += [(node.lineno,node.end_lineno,node.name,node) for node in tree.body
                       if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
        lines=source.splitlines()
        for start,end,name,node in candidates:
            # Existing read ranges may be pages; skip only completely read code.
            coverage=sorted(seen.get(path,[]));cursor=start
            for left,right in coverage:
                if left<=cursor<=right:cursor=right+1
            if cursor>end:continue
            names={n.attr if isinstance(n,ast.Attribute) else n.id for n in ast.walk(node) if isinstance(n,(ast.Attribute,ast.Name))}
            score=35-6*distance.get(path,6)
            if distribution and ('boxplot' in name.lower() or 'violin' in name.lower()):score+=65
            if distribution and names&{'boxplot','violinplot','_publication_boxplot_source_groups'}:score+=30
            if limits and names&{'set_ylim','set_xlim','bound_spines_to_ticks'}:score+=35
            if limits and re.search(r'figure|final|save|build|assemble',name,re.I):score+=20
            if readers and (names&{'read_csv','read_json','read_text'} or re.search(r'^(read|load|capture)',name,re.I)):score+=30
            if name=='imports':score+=8
            if name=='imports':score=12-2*distance.get(path,6)
            if name in reason:score+=40
            if len('\n'.join(lines[start-1:end]))>24000:
                end=min(end,cursor+239);start=cursor
            ranked.append((-score,path,start,end))
    result=[];selected=[]
    for _,path,start,end in sorted(ranked):
        if any(p==path and left<=start and end<=right for p,left,right in selected):continue
        selected.append((path,start,end));result.append({'path':path,'start_line':start,'end_line':end})
        if len(result)>=4:break
    return result
