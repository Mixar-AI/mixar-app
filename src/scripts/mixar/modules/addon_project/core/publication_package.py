# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an explicit, single-add-on source archive without importing its code."""
import ast
import base64
import io
import os
from pathlib import Path
import re
import zipfile

from ..constants import IGNORED_PARTS
from ..links import is_link
from ..manifest import entrypoint_source_path, is_root_package_entrypoint

SUFFIXES = {'.py', '.pyi', '.json', '.toml', '.md', '.txt', '.yaml', '.yml',
            '.png', '.jpg', '.jpeg', '.webp'}
MAX_ARCHIVE = 16 * 1024 * 1024
MAX_UNPACKED = 32 * 1024 * 1024


def source_info(source):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'bl_info' for t in node.targets):
            try:
                value = ast.literal_eval(node.value)
                return value if isinstance(value, dict) else {}
            except (ValueError, TypeError):
                break
    return {}


def package(root, module, *, workspace=False):
    root = Path(root).resolve(strict=True)
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', module):
        raise ValueError('Choose one top-level add-on package')
    if workspace and is_root_package_entrypoint(root, module):
        raise ValueError('Choose an add-on inside the workspace')
    source = entrypoint_source_path(root, module)
    if is_link(source) or is_link(source.parent):
        raise ValueError('Linked source cannot be published; use the original package')
    source = source.resolve(strict=True)
    if root not in source.parents:
        raise ValueError('The add-on must be inside its linked project')
    info = source_info(source.read_bytes())
    entries = []
    if source.name != '__init__.py':
        entries.append((module + '/__init__.py', source))
    else:
        folder = source.parent
        for current, dirs, files in os.walk(folder, followlinks=False):
            here = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_PARTS and not d.startswith('.'))
            if any(is_link(here / d) for d in dirs):
                raise ValueError('Remove linked folders from this add-on before publishing')
            for name in sorted(files):
                if name.startswith('.') or name.endswith(('.pyc', '.pyo')):
                    continue
                path = here / name
                relative = path.relative_to(folder).as_posix()
                if is_link(path) or not path.is_file():
                    raise ValueError('Remove linked files from this add-on before publishing')
                if path.suffix.lower() not in SUFFIXES and name not in {'LICENSE', 'NOTICE', 'COPYING'}:
                    raise ValueError(f'Unsupported package file: {relative}. Publish source, documentation and images only')
                if any(not re.fullmatch(r'[A-Za-z0-9_ .-]+', p) for p in Path(relative).parts):
                    raise ValueError('Package filenames must use letters, numbers, spaces, dots, underscores or hyphens')
                entries.append((module + '/' + relative, path))
    if not 1 <= len(entries) <= 500:
        raise ValueError('Publish up to 500 files per add-on')
    stream, total, files, seen = io.BytesIO(), 0, [], set()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in entries:
            if len(name) > 240 or name.casefold() in seen:
                raise ValueError('Package filenames are too long or duplicate each other')
            seen.add(name.casefold())
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError('Each package file must be smaller than 8 MB')
            content = path.read_bytes()
            total += len(content)
            if total > MAX_UNPACKED:
                raise ValueError('An add-on can contain up to 32 MB of files')
            if path.suffix in {'.py', '.pyi'}:
                if len(content) > 1024 * 1024:
                    raise ValueError('Each Python source file must be smaller than 1 MB')
                ast.parse(content, filename=name)
            archive.writestr(name, content)
            files.append({'name': name, 'size': len(content)})
    raw = stream.getvalue()
    if len(raw) > MAX_ARCHIVE:
        raise ValueError('The ZIP must be smaller than 16 MB')
    return {'archive': base64.b64encode(raw).decode(), 'files': files,
            'size': len(raw), 'info': info, 'module': module}
