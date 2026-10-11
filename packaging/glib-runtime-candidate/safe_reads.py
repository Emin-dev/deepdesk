"""Bounded, no-follow regular-file reads under explicit first-party roots."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat


class ReadContractError(Exception):
    pass


def need(value):
    if not value:
        raise ReadContractError()


def identity(st):
    return st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns


@contextmanager
def regular_file(path, roots, maximum):
    path = Path(path)
    roots = tuple(Path(root) for root in roots)
    need(path.is_absolute() and '..' not in path.parts and 0 <= maximum <= 128 * 1024**2)
    need(roots and all(root.is_absolute() and '..' not in root.parts for root in roots))
    need(any(path.is_relative_to(root) and path != root for root in roots))
    directories, file_fd, stream = [], None, None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent = os.open('/', flags)
        directories.append(parent)
        for component in path.parts[1:-1]:
            parent = os.open(component, flags, dir_fd=parent)
            directories.append(parent)
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(file_fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= maximum)
        stream = os.fdopen(file_fd, 'rb')
        file_fd = None
        yield stream, before.st_size
        need(identity(os.fstat(stream.fileno())) == identity(before))
    finally:
        if stream is not None:
            stream.close()
        if file_fd is not None:
            os.close(file_fd)
        for directory in reversed(directories):
            os.close(directory)


def read(path, roots, maximum):
    with regular_file(path, roots, maximum) as (stream, size):
        data = stream.read(maximum + 1)
        need(len(data) == size and len(data) <= maximum)
    return data
