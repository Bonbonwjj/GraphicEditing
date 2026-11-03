"""Add a pinned pure Python wheel to a checksum-verified relocatable runtime.

The existing conda-unpack metadata stays intact. No system installation or
credentials are copied. Used only to reproduce the Windows v0.2.2 package.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def augment(payload, wheel, destination, environment_history=None):
    manifest = json.loads((payload/'manifest.json').read_text(encoding='utf-8'))
    archive = payload/'runtime.tar.gz'
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['runtime_sha256']:
            raise ValueError('Previous runtime checksum mismatch')
    with zipfile.ZipFile(wheel) as package:
        names = [name for name in package.namelist() if not name.endswith('/')]
        if not names or any(PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                            or not name.startswith(('cloudpickle/', 'cloudpickle-')) for name in names):
            raise ValueError('Expected a pure Python cloudpickle wheel')
        additions = {'Lib/site-packages/'+name:package.read(name) for name in names}
    destination.mkdir(parents=True, exist_ok=True)
    target = destination/'runtime.tar.gz'
    if target.resolve() == archive.resolve():
        raise ValueError('Output must differ from the previous runtime')
    with tarfile.open(archive, 'r:gz') as source, tarfile.open(target, 'w:gz', compresslevel=3) as output:
        for member in source:
            if member.name.removeprefix('./') not in additions:
                output.addfile(member, source.extractfile(member) if member.isfile() else None)
        for name, data in sorted(additions.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            member.mtime = 0
            output.addfile(member, io.BytesIO(data))
    with target.open('rb') as stream:
        manifest['runtime_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest['runtime_additions'] = {'wheel':wheel.name, 'sha256':hashlib.sha256(wheel.read_bytes()).hexdigest()}
    if environment_history:
        manifest['environment_sha256'] = hashlib.sha256(environment_history.read_bytes()).hexdigest()
    (destination/'app').mkdir(exist_ok=True)
    (destination/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('payload', type=Path)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--environment-history', type=Path)
    args = parser.parse_args()
    print(json.dumps(augment(args.payload, args.wheel, args.destination, args.environment_history)))
