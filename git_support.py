"""Best-effort Git integration that never makes platform operations depend on Git."""
import subprocess
from pathlib import Path
from typing import Dict, Iterable


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def git_status(repo: Path) -> Dict[str, object]:
    repo = Path(repo).resolve()
    try:
        result = _run(repo, "rev-parse", "--show-toplevel")
    except (FileNotFoundError, OSError) as exc:
        return {"enabled": False, "reason": "git-unavailable", "error": str(exc)}
    if result.returncode != 0:
        return {"enabled": False, "reason": "not-a-repository"}
    return {
        "enabled": True,
        "repository": result.stdout.strip(),
        "reason": None,
    }


def record_change(
    repo: Path,
    paths: Iterable[Path],
    message: str,
    *,
    push: bool = False,
) -> Dict[str, object]:
    repo = Path(repo).resolve()
    status = git_status(repo)
    response: Dict[str, object] = dict(status)
    response.update({"committed": False, "pushed": False})
    if not status["enabled"]:
        return response

    relative_paths = []
    for path in paths:
        resolved = Path(path).resolve()
        try:
            relative_paths.append(str(resolved.relative_to(repo)))
        except ValueError:
            response.update({"reason": "path-outside-repository"})
            return response
    if not relative_paths:
        response.update({"reason": "no-paths"})
        return response

    add = _run(repo, "add", "--", *relative_paths)
    if add.returncode != 0:
        response.update({"reason": "git-add-failed", "error": add.stderr[-700:]})
        return response
    staged = _run(repo, "diff", "--cached", "--quiet", "--", *relative_paths)
    if staged.returncode == 0:
        response.update({"reason": "no-changes"})
        return response
    if staged.returncode != 1:
        response.update({"reason": "git-diff-failed", "error": staged.stderr[-700:]})
        return response

    commit = _run(
        repo,
        "-c",
        "user.name=Chart Studio",
        "-c",
        "user.email=chart-studio@localhost",
        "commit",
        "-m",
        message,
    )
    if commit.returncode != 0:
        response.update({"reason": "git-commit-failed", "error": commit.stderr[-700:]})
        return response
    response.update({"committed": True, "reason": None})
    if push:
        pushed = _run(repo, "push")
        response["pushed"] = pushed.returncode == 0
        if pushed.returncode != 0:
            response.update({"reason": "git-push-failed", "error": pushed.stderr[-700:]})
    return response
