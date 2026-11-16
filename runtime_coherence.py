"""Track the exact local source executed; require restart rather than mix releases."""

import importlib.abc
import importlib.machinery
import sys
from hashlib import sha256
from pathlib import Path
from threading import RLock

_ROOTS = set()
_NAMES = set()
_LOADED = {}
_LOCK = RLock()


def _in_scope(location, root):
    if not location.is_relative_to(root):
        return False
    relative = location.relative_to(root)
    return relative.parts[0] not in {
        ".venv",
        "venv",
        ".git",
        ".superpowers",
        "tmp",
        "outputs",
        "data",
        "tests",
    }


class _TrackedLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # Compile these bytes directly: timestamp/size-based pyc reuse can miss an update.
        raw = Path(self.path).read_bytes()
        code = compile(raw, self.path, "exec", dont_inherit=True)
        with _LOCK:
            _LOADED[fullname] = (Path(self.path).resolve(), sha256(raw).digest())
        return code


class _LocalFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] not in _NAMES:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader) and spec.origin:
            location = Path(spec.origin).resolve()
            if any(_in_scope(location, root) for root in _ROOTS):
                spec.loader = _TrackedLoader(fullname, str(location))
                return spec
        return None


_FINDER = _LocalFinder()


def install_local_tracking(root):
    root = Path(root).resolve()
    with _LOCK:
        _NAMES.update(path.stem for path in root.glob("*.py"))
        _NAMES.update(path.parent.name for path in root.glob("*/__init__.py") if _in_scope(path, root))
        if root in _ROOTS:
            return
        _ROOTS.add(root)
        # Modules predating tracking cannot be attested. A clean process will capture them.
        for name, module in tuple(sys.modules.items()):
            location = getattr(module, "__file__", None)
            if location and name != __name__:
                location = Path(location).resolve()
                if location.suffix == ".py" and _in_scope(location, root) and name not in _LOADED:
                    _LOADED[name] = (location, None)
        if _FINDER not in sys.meta_path:
            sys.meta_path.insert(0, _FINDER)


def loaded_module_changes(root):
    root = Path(root).resolve()
    changed = []
    with _LOCK:
        items = tuple(_LOADED.items())
    for name, (location, digest) in items:
        if not _in_scope(location, root):
            continue
        try:
            if digest is None or sha256(location.read_bytes()).digest() != digest:
                changed.append(name)
        except OSError:
            changed.append(name)
    return sorted(changed)


# Attest this module itself from its executing code, including first hot installation.
_SOURCE = Path(__file__).read_bytes()
_SELF_CODE = sys._getframe().f_code
_LOADED[__name__] = (
    Path(__file__).resolve(),
    sha256(_SOURCE).digest() if _SELF_CODE == compile(_SOURCE, __file__, "exec", dont_inherit=True) else None,
)
