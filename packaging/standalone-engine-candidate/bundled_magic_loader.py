"""Deepdesk overlay for python-magic 0.4.27: only the bundled native resources.

Installed as magic/loader.py. Each binding receives its own ctypes function
objects: modern c_void_p and compatibility POINTER(magic_set) must not collide.
No native library is loaded until load_lib() is explicitly called by a binding.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

# Pinned CPython ctypes parameter objects, without loading any native library.
_C_ARG_OBJECT = type(ctypes.c_char_p.from_param(b''))


def _root():
    prefix = Path(sys.prefix).resolve(strict=True)
    here = Path(__file__).resolve(strict=True)
    expected = prefix / 'lib/python3.12/site-packages/magic/loader.py'
    if here != expected:
        raise ImportError('Bundled magic loader origin differs')
    root = prefix / 'lib/deepdesk-native/libmagic'
    if not root.is_dir() or root.is_symlink() or root.resolve() != root:
        raise ImportError('Bundled magic native root is unavailable')
    return root


def _regular(root, relative):
    path = root / relative
    if not path.is_file() or path.is_symlink() or path.resolve() != path:
        raise ImportError('Bundled magic resource is unavailable')
    return path


def _database(root):
    return os.fsencode(_regular(root, 'share/misc/magic.mgc'))


def _text_sources(root):
    # FILE_COMPILE parses text; passing magic.mgc here is invalid. This directory
    # is the same flat 358-fragment input shape used by upstream's Makefile.
    manifest = _regular(root, 'share/misc/deepdesk-text-fragments.json')
    contract = json.loads(manifest.read_text(encoding='utf-8'))
    rows = contract.get('fragments', [])
    text = root / 'share/misc/magic'
    if (contract.get('count') != 358 or len(rows) != 358 or not text.is_dir()
            or text.is_symlink() or text.resolve() != text):
        raise ImportError('Bundled magic text sources are unavailable')
    expected = {row['name'] for row in rows}
    if len(expected) != 358 or {p.name for p in text.iterdir()} != expected:
        raise ImportError('Bundled magic text source set differs')
    for row in rows:
        if Path(row['name']).name != row['name']:
            raise ImportError('Bundled magic text source name differs')
        path = _regular(root, 'share/misc/magic/' + row['name'])
        data = path.read_bytes()
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ImportError('Bundled magic text source bytes differ')
    return os.fsencode(text)


class _FilenameParameter:
    """Resolve only when ctypes reaches filename, after freezing the cookie.

    ctypes retains converted argument owners and copies native pointer values
    from left to right. A per-call lazy parameter keeps that ordering without
    changing either binding's public/native argtypes or shared function state.
    """
    def __init__(self, value, converter, name, root):
        self._value = value
        self._converter = converter
        self._name = name
        self._root = root
        self._resolved = False
        self._converted = None
        self._pointer = None
        self._resource_error = None

    @property
    def _as_parameter_(self):
        if self._resolved:
            return self._pointer
        # Original caller conversion runs once, in ctypes' argument-2 slot.
        # ctypes itself supplies normal exception wrapping and error ordering.
        converted = self._converter.from_param(self._value)
        self._converted = converted  # Keep the conversion and its owner alive.
        owner = getattr(converted, '_obj', None) if type(converted) is _C_ARG_OBJECT else None
        if isinstance(owner, bytes):
            # Tagged bytes parameters cannot be fed through from_param again.
            # The immutable owner has a non-NULL address, including b''.
            pointer = ctypes.c_char_p(owner)
        else:
            # Freeze the address rather than passing a mutable typed pointer
            # through another conversion of the original caller's object.
            pointer = ctypes.c_char_p(ctypes.cast(converted, ctypes.c_void_p).value)
        if ctypes.cast(pointer, ctypes.c_void_p).value is None:
            try:
                path = (_text_sources(self._root) if self._name == 'magic_compile'
                        else _database(self._root))
            except ImportError as error:
                self._resource_error = error
                raise
            pointer = ctypes.c_char_p(path)
        self._pointer = pointer
        self._resolved = True
        return pointer


class _Function:
    def __init__(self, function, name, root):
        object.__setattr__(self, '_function', function)
        object.__setattr__(self, '_name', name)
        object.__setattr__(self, '_root', root)

    def __getattr__(self, name):
        return getattr(self._function, name)

    def __setattr__(self, name, value):
        setattr(self._function, name, value)

    def __call__(self, *args):
        if len(args) < 2:
            return self._function(*args)  # Keep ctypes' original arity failure.
        declared = self._function.argtypes
        converter = declared[1] if declared is not None else ctypes.c_char_p
        filename = _FilenameParameter(args[1], converter, self._name, self._root)
        arguments = list(args)
        arguments[1] = filename
        try:
            return self._function(*arguments)
        except ctypes.ArgumentError:
            # Preserve the overlay's existing fixed missing-resource exception;
            # caller conversion errors retain ctypes' original category/order.
            if filename._resource_error is not None:
                raise filename._resource_error from None
            raise



class _Library:
    def __init__(self, library, root):
        self._library = library
        self._root = root
        self._functions = {}

    def __getattr__(self, name):
        if name not in self._functions:
            function = getattr(self._library, name)
            if name in {'magic_load', 'magic_check', 'magic_list', 'magic_compile'}:
                function = _Function(function, name, self._root)
            self._functions[name] = function
        return self._functions[name]


def load_lib():
    root = _root()
    library = _regular(root, 'lib/libmagic.1.dylib')
    _database(root)
    try:
        return _Library(ctypes.CDLL(str(library)), root)
    except OSError:
        raise ImportError('Bundled libmagic could not be loaded') from None
