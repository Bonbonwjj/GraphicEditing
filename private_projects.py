"""Local research projects must never enter team publication or desktop seeds."""
import json
from pathlib import Path


def names(root):
    path = Path(root) / '.private-projects.json'
    # Fail closed on a corrupt registry; do not accidentally publish private work.
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise ValueError('本地私有工程登记损坏，已停止同步。')
    return set(value)
