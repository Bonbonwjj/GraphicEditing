"""Shared data-source descriptors, adapter selection, and path policy helpers."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol


class UnsupportedDataSourceError(ValueError):
    """Raised when no configured adapter recognises a source."""


@dataclass(frozen=True)
class DataSourceDescriptor:
    source_id: str
    kind: str
    mode: str
    location: str
    read_only: bool = True
    trusted: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["id"] = data.pop("source_id")
        return data


class DataSourceAdapter(Protocol):
    kind: str

    def can_handle(self, source: Path) -> bool:
        ...

    def inspect(
        self, source: Path, *, mode: str, trusted: bool
    ) -> DataSourceDescriptor:
        ...


class DataSourceRegistry:
    def __init__(self, adapters: Iterable[DataSourceAdapter] = ()) -> None:
        self._adapters: List[DataSourceAdapter] = list(adapters)

    def register(self, adapter: DataSourceAdapter) -> None:
        self._adapters.append(adapter)

    def adapter_for(self, source: Path) -> DataSourceAdapter:
        source = Path(source)
        for adapter in self._adapters:
            if adapter.can_handle(source):
                return adapter
        raise UnsupportedDataSourceError("不支持的数据源：{}".format(source))

    def inspect(
        self, source: Path, *, mode: str, trusted: bool = False
    ) -> DataSourceDescriptor:
        source = Path(source)
        return self.adapter_for(source).inspect(
            source, mode=mode, trusted=trusted
        )


def resolve_allowed_path(requested: Path, allowed_roots: Iterable[Path]) -> Path:
    """Resolve *requested* and ensure it is inside one configured shared root."""
    roots = [Path(root).resolve(strict=True) for root in allowed_roots]
    if not roots:
        raise ValueError("未配置允许的共享目录")
    resolved = Path(requested).resolve(strict=True)
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    raise ValueError("路径不在允许的共享目录中：{}".format(resolved))
