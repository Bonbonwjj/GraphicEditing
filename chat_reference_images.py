"""Immutable, project-local visual references for chart edit turns."""
import base64
import hashlib
import io
import json
import re
import uuid
import warnings
from pathlib import Path

MAX_REFERENCE_IMAGES=3
MAX_FILE_BYTES=6_000_000
MAX_PIXELS=20_000_000
MAX_MODEL_IMAGES=4


def _folder(directory):
    folder=Path(directory)/'uploaded_references'
    if folder.is_symlink():raise ValueError('参考图目录不能是符号链接')
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def store(directory,project,body):
    from PIL import Image,ImageOps
    if not isinstance(body,dict):raise ValueError('参考图上传请求无效')
    data=body.get('data_url')
    if not isinstance(data,str) or len(data)>MAX_FILE_BYTES*4//3+100:
        raise ValueError('请选择不超过 6 MB 的 PNG、JPEG 或 WebP 参考图')
    match=re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=\r\n]+)',data)
    if not match:raise ValueError('参考图仅支持 PNG、JPEG 或 WebP 图片')
    try:
        raw=base64.b64decode(match[1],validate=True)
        if not raw or len(raw)>MAX_FILE_BYTES:raise ValueError('参考图超过 6 MB')
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG','JPEG','WEBP'):raise ValueError('不支持的参考图片格式')
                if image.width*image.height>MAX_PIXELS:raise ValueError('参考图像素过大，请缩小后上传')
                image=ImageOps.exif_transpose(image)
                image.thumbnail((1024,1024),Image.Resampling.LANCZOS)
                image=image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
                clean=Image.new(image.mode,image.size);clean.paste(image)
        while True:
            encoded=io.BytesIO();clean.save(encoded,format='PNG',optimize=True);payload=encoded.getvalue()
            if len(payload)<=1_500_000:break
            clean.thumbnail((int(clean.width*.8),int(clean.height*.8)),Image.Resampling.LANCZOS)
    except Exception as error:
        # Pillow decoder/bomb errors are input failures, without exposing paths.
        if isinstance(error,ValueError):raise
        raise ValueError('参考图片无法读取，请使用有效的 PNG、JPEG 或 WebP 图片') from error
    ident='refimg_'+str(uuid.uuid4());sha='sha256:'+hashlib.sha256(payload).hexdigest()
    name=body.get('name','参考图')
    if not isinstance(name,str):raise ValueError('参考图片名称无效')
    name=re.sub(r'[\x00-\x1f\x7f]','',name.replace('\\','/').rsplit('/',1)[-1])[:120] or '参考图'
    meta={'reference_id':ident,'revision_id':sha,'name':name,'width':clean.width,'height':clean.height,
          'read_only':True,'source':'uploaded_image','image_url':f'/api/projects/{project}/chat/reference-images/{ident}/image'}
    folder=_folder(directory)
    with (folder/(ident+'.png')).open('xb') as out:out.write(payload)
    with (folder/(ident+'.json')).open('x') as out:json.dump(meta,out,ensure_ascii=False)
    return meta


def resolve(directory,ident):
    if not isinstance(ident,str) or not re.fullmatch(r'refimg_[0-9a-f-]{36}',ident):raise ValueError('无效的参考图片 ID')
    try:uuid.UUID(ident[7:])
    except ValueError:raise ValueError('无效的参考图片 ID')
    folder=_folder(directory);metadata=folder/(ident+'.json');image=folder/(ident+'.png')
    if metadata.is_symlink() or image.is_symlink():raise ValueError('参考图不能是符号链接')
    if not metadata.is_file() or not image.is_file():raise ValueError('参考图片不存在，请重新上传')
    meta=json.loads(metadata.read_text());payload=image.read_bytes()
    if meta.get('reference_id')!=ident or meta.get('revision_id')!='sha256:'+hashlib.sha256(payload).hexdigest():
        raise ValueError('参考图片内容已变化，请重新上传')
    return {**meta,'_image':str(image)}


def select(directory,ids):
    if not isinstance(ids,list) or len(ids)>MAX_REFERENCE_IMAGES or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('最多添加 3 张不重复的参考图片')
    return [resolve(directory,i) for i in ids]


def public(items):
    return [{k:v for k,v in item.items() if not k.startswith('_')} for item in items]


def inferred_distribution(context,proposal):
    """Only broad visual imitation may authorize an explicitly declared type change.

    This selects the existing full-sample verification path; it never waives it.
    """
    refs=context.get('reference_images') or []
    message=context.get('user_message','')
    if not refs or not all(r['reference_id'] in context.get('image_order',[]) for r in refs):return None
    if not re.search(r'类似|一样|模仿|照着|相似|similar|like|(?:参考|参照).{0,15}图',message,re.I):return None
    if re.search(r'(?:图型|图表类型|图类型).{0,4}(?:不变|保持|不要改)|只(?:参考|借鉴|调整|改).{0,8}(?:配色|颜色|字号|字体|布局)',message):return None
    kinds=set()
    for op in (proposal.get('interpreted_request') or {}).get('operations',[]):
        if op.get('property') not in ('chart_type','plot_type','type','图型','图表类型','图类型'):continue
        value=op.get('desired_change')
        if not isinstance(value,str):continue
        key=value.lower().replace('_','').replace(' ','')
        kind={'violin':'violinplot','violinplot':'violinplot','小提琴图':'violinplot','box':'boxplot','boxplot':'boxplot','箱线图':'boxplot','箱型图':'boxplot'}.get(key)
        if not kind and re.search(r'half.?violin|split.?violin|半小提琴',value,re.I):kind='violinplot'
        if kind:kinds.add(kind)
    return next(iter(kinds)) if len(kinds)==1 else None
