"""Descriptor-relative atomic rename without replacement."""

from __future__ import annotations

import ctypes
import errno
import os
import sys

from idfrepair.domain.errors import SessionStateError


def _invoke_rename_noreplace(
    source_directory: int,
    source_leaf: str,
    target_directory: int,
    target_leaf: str,
) -> tuple[int, int]:
    """Invoke the platform syscall and return its result plus captured errno."""

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renameatx_np"):
        function = library.renameatx_np
        flag = 0x00000004  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        function = library.renameat2
        flag = 0x1  # RENAME_NOREPLACE
    else:
        raise NotImplementedError
    function.argtypes = (
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        source_directory, os.fsencode(source_leaf),
        target_directory, os.fsencode(target_leaf), flag,
    )
    return result, ctypes.get_errno() if result != 0 else 0


def rename_noreplace(
    source_directory: int,
    source_leaf: str,
    target_directory: int,
    target_leaf: str,
) -> None:
    """Rename one descriptor-relative leaf, never replacing its target."""

    try:
        result, observed = _invoke_rename_noreplace(
            source_directory, source_leaf, target_directory, target_leaf,
        )
    except NotImplementedError as exc:
        raise SessionStateError("atomic_rename_unsupported") from exc
    except (OSError, UnicodeError, ValueError) as exc:
        raise SessionStateError("atomic_rename_failed") from exc
    if result == 0:
        return
    if observed == errno.ENOENT:
        raise SessionStateError("atomic_rename_source_missing")
    if observed in {errno.EEXIST, errno.ENOTEMPTY}:
        raise SessionStateError("atomic_rename_target_exists")
    raise SessionStateError("atomic_rename_failed")
