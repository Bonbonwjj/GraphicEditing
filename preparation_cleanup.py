"""Bound preparation workspace lifetime and remove caches after verified install."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import time


def _sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def completed_project(project):
    """A ready flag alone is not sufficient proof that outputs were installed."""
    import project_preparation as prep
    project=Path(project)
    try:
        return (not project.is_symlink() and prep.read_state(project).get('status')=='ready'
                and prep.can_open(project))
    except (OSError,ValueError):
        return False


def cleanup_completed_cache(project):
    project=Path(project)
    result={'removed':[],'errors':[]}
    if not completed_project(project):
        return result
    preparation=project/'.preparation'
    if preparation.is_symlink():
        result['errors'].append('Refused symlinked preparation directory')
        return result
    for name in ('universal-cache','native-cache'):
        target=preparation/name
        if target.is_symlink():
            result['errors'].append('Refused symlinked cache: '+name)
            continue
        if not target.exists():
            continue
        try:
            shutil.rmtree(target)
            result['removed'].append(str(target))
        except FileNotFoundError:
            pass  # Another completion cleanup may have already removed it.
        except OSError as error:
            result['errors'].append(str(error))
    return result


def release_render_workspaces(work, figure_id):
    """Called only after _one_render has finished reading its complete result."""
    work=Path(work)
    if not re.fullmatch(r'[A-Za-z0-9_]+',figure_id):
        raise ValueError('Invalid generated figure ID')
    errors=[]
    for prefix in ('render_','repeat_'):
        target=work/(prefix+figure_id)
        if target.is_symlink():
            errors.append('Refused symlinked render workspace: '+str(target))
            continue
        if target.exists():
            try:shutil.rmtree(target)
            except FileNotFoundError:pass
            except OSError as error:errors.append(str(error))
    return errors


def release_verified_live_workspaces(project, work):
    """Adopt cleanup for an old running worker without interrupting it.

    Only workspaces with both a durable verified cache and matching staged PNG
    are eligible. The current, unverified render and source staging are retained.
    """
    project,work=Path(project),Path(work)
    if work.is_symlink() or not work.name.startswith('plot-universal-prepare-'):
        raise ValueError('Not a preparation task workspace')
    if not work.exists():
        return {'released':[],'errors':[]}
    staged=work/'project'
    metadata=json.loads((staged/'project.json').read_text(encoding='utf-8'))
    if metadata.get('name')!=project.name:
        raise ValueError('Preparation workspace belongs to another project')
    registry=json.loads((staged/'universal-project.json').read_text(encoding='utf-8'))
    if registry.get('schema')!='plot-forge-universal/1':
        raise ValueError('Unknown preparation registry')
    verified=set()
    cache=project/'.preparation/universal-cache'
    for record_path in cache.glob('*.json'):
        try:
            if record_path.is_symlink() or record_path.stat().st_size>6*1024**2:
                continue
            record=json.loads(record_path.read_text(encoding='utf-8'))
            image=record_path.with_suffix('.png')
            if (image.is_symlink() or record.get('key')!=record_path.stem
                    or record.get('report',{}).get('output_count')!=1
                    or _sha(image)!=record.get('image_sha256')):
                continue
            origin=record['report'].get('output_provenance',{})
            verified.add((origin.get('entry_path'),origin.get('entry_symbol'),
                          origin.get('output_index'),record['image_sha256']))
        except (OSError,ValueError,KeyError,TypeError):
            continue
    result={'released':[],'errors':[]}
    for ident,settings in registry.get('figures',{}).items():
        if not re.fullmatch(r'[A-Za-z0-9_]+',ident):
            continue
        image=staged/'previews'/(ident+'.png')
        if image.is_symlink() or not image.is_file():
            continue
        signature=(settings.get('entry_path'),settings.get('entry_symbol'),
                   settings.get('output_index'),_sha(image))
        if signature not in verified:
            continue
        present=any((work/(prefix+ident)).exists() for prefix in ('render_','repeat_'))
        errors=release_render_workspaces(work,ident)
        result['errors'].extend(errors)
        if present and not errors:result['released'].append(ident)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',required=True)
    parser.add_argument('--work',required=True)
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    import project_preparation as prep
    project=Path(args.project).resolve()
    work=Path(args.work).resolve()
    while True:
        if prep.read_state(project).get('status')!='working':
            print(json.dumps(cleanup_completed_cache(project),ensure_ascii=False),flush=True)
            return
        if work.exists():
            try:
                result=release_verified_live_workspaces(project,work)
                if result['released'] or result['errors']:
                    print(json.dumps(result,ensure_ascii=False),flush=True)
            except (OSError,ValueError) as error:
                print('Cleanup deferred: '+str(error),flush=True)
        if not args.watch:return
        time.sleep(20)


if __name__=='__main__':
    main()
