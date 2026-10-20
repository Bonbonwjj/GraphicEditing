"""Create a GitHub-ready data/code directory without publishing anything."""
from pathlib import Path
import argparse
from collaboration_sync import CollaborationSync
from project_storage import to_shared


def export(root, destination):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('导出目录已有文件，请选择空目录，避免覆盖现有内容')
    files=to_shared(CollaborationSync.files(Path(root)/'projects'))
    destination.mkdir(parents=True,exist_ok=True)
    CollaborationSync.write_files(destination,{},files)
    return len(files)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'dist/github-projects/projects')
    args=parser.parse_args()
    print(f'已导出 {export(Path(__file__).parent,args.output)} 个文件到 {args.output}，未上传 GitHub')
