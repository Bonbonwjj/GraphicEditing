"""Route qualified project library imports to the selected validation copy."""
import importlib.util
from pathlib import Path
import sys
import types


def install_project_library(project, library):
    project, library = Path(project), Path(library)
    for name, path in [('projects', project.parent), ('projects.' + project.name, project)]:
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
    name = 'projects.' + project.name + '.lib'
    initializer = library / '__init__.py'
    if initializer.is_file():
        spec = importlib.util.spec_from_file_location(name, initializer, submodule_search_locations=[str(library)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
    else:
        package = types.ModuleType(name)
        package.__path__ = [str(library)]
        sys.modules[name] = package
