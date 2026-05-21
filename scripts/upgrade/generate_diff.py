#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Generate unified diff between src and upstream.

This script recursively compares the modified files in src/
against the original Blender files in upstream/, identifying
added and modified files and generating a unified diff/patch that can
be applied to other upstream branches.

Usage:
    python generate_diff.py [--src SRC_PATH] [--upstream UPSTREAM_PATH] [--output OUTPUT_PATH]

Examples:
    # Use default paths
    python generate_diff.py

    # Custom paths
    python generate_diff.py --src /path/to/src --upstream /path/to/upstream

    # Custom output location
    python generate_diff.py --output /path/to/output.patch
"""

import os
import sys
import argparse
import difflib
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Set


# Patterns to ignore during comparison
IGNORE_PATTERNS = {
    '__pycache__',
    '.pyc',
    '.pyo',
    '.DS_Store',
    '.git',
    '.gitignore',
    '__MACOSX',
    '.rej',  # Reject files from failed patch attempts
    '.orig',  # Original files from patch
}


def should_ignore(path: str) -> bool:
    """Check if a path should be ignored based on ignore patterns."""
    path_parts = Path(path).parts
    for pattern in IGNORE_PATTERNS:
        if pattern in path_parts or path.endswith(pattern):
            return True
    return False


def is_binary_file(filepath: str) -> bool:
    """Check if a file is binary by reading a sample of bytes."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            # Check for null bytes which indicate binary content
            if b'\x00' in chunk:
                return True
            # Check if content is mostly text
            text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
            return bool(chunk.translate(None, text_chars))
    except (IOError, OSError):
        return False


def get_all_files(root_dir: str) -> Set[str]:
    """Recursively get all non-ignored files relative to root_dir."""
    files = set()
    root_path = Path(root_dir)

    if not root_path.exists():
        return files

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Remove ignored directories from traversal
        dirnames[:] = [d for d in dirnames if not should_ignore(d)]

        for filename in filenames:
            if should_ignore(filename):
                continue

            filepath = Path(dirpath) / filename
            relative_path = filepath.relative_to(root_path)
            files.add(str(relative_path))

    return files


def read_file_lines(filepath: str) -> List[str]:
    """Read file and return lines without trailing newlines.

    This is important for difflib.unified_diff to generate correct patches.
    Empty lines should become '' not '\n', so difflib adds '+ ' not just '+'.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # Strip trailing newlines from each line for proper diff generation
            return [line.rstrip('\n\r') for line in f.readlines()]
    except UnicodeDecodeError:
        # Try with latin-1 as fallback
        try:
            with open(filepath, 'r', encoding='latin-1') as f:
                return [line.rstrip('\n\r') for line in f.readlines()]
        except Exception:
            return []
    except Exception:
        return []


def generate_file_diff(src_file: str, upstream_file: str, relative_path: str) -> List[str]:
    """Generate unified diff for a single file."""
    src_lines = read_file_lines(src_file)
    upstream_lines = read_file_lines(upstream_file)

    # Quote filenames with spaces for proper patch handling
    from_path = f'"a/{relative_path}"' if ' ' in relative_path else f'a/{relative_path}'
    to_path = f'"b/{relative_path}"' if ' ' in relative_path else f'b/{relative_path}'

    diff = difflib.unified_diff(
        upstream_lines,
        src_lines,
        fromfile=from_path,
        tofile=to_path,
        lineterm=''
    )

    # Fix difflib bug: empty added/removed lines should be '+ ' or '- ', not '+' or '-'
    fixed_diff = []
    for line in diff:
        if line == '+' or line == '-':
            fixed_diff.append(line + ' ')
        else:
            fixed_diff.append(line)

    return fixed_diff


def generate_new_file_diff(src_file: str, relative_path: str) -> List[str]:
    """Generate diff for a newly added file."""
    src_lines = read_file_lines(src_file)

    # Quote filenames with spaces for proper patch handling
    to_path = f'"b/{relative_path}"' if ' ' in relative_path else f'b/{relative_path}'

    diff = difflib.unified_diff(
        [],
        src_lines,
        fromfile='/dev/null',
        tofile=to_path,
        lineterm=''
    )

    # Fix difflib bug: empty added lines should be '+ ', not '+'
    fixed_diff = []
    for line in diff:
        if line == '+':
            fixed_diff.append('+ ')
        else:
            fixed_diff.append(line)

    return fixed_diff


def main():
    """Main entry point for the diff generation script."""
    # Set up argument parser
    parser = argparse.ArgumentParser(
        description='Generate unified diff between src and upstream',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    # Get default paths relative to this script
    script_dir = Path(__file__).parent.parent.parent  # Go up to project root
    default_src = script_dir / 'src'
    default_upstream = script_dir / 'upstream'
    default_output_dir = script_dir / 'scripts' / 'upgrade' / 'patches'

    parser.add_argument(
        '--src',
        type=str,
        default=str(default_src),
        help=f'Path to src directory (default: {default_src})'
    )
    parser.add_argument(
        '--upstream',
        type=str,
        default=str(default_upstream),
        help=f'Path to upstream directory (default: {default_upstream})'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output patch file path (default: auto-generated in patches/)'
    )
    parser.add_argument(
        '--custom-files-output',
        type=str,
        default=None,
        help='Output JSON file for custom files list (default: auto-generated in patches/)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    # Validate input directories
    src_dir = Path(args.src)
    upstream_dir = Path(args.upstream)

    if not src_dir.exists():
        print(f"Error: Source directory does not exist: {src_dir}", file=sys.stderr)
        return 1

    if not upstream_dir.exists():
        print(f"Error: Upstream directory does not exist: {upstream_dir}", file=sys.stderr)
        return 1

    # Determine output files
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')

    if args.output:
        output_file = Path(args.output)
    else:
        output_file = default_output_dir / f'mixar_modifications_{timestamp}.patch'

    if args.custom_files_output:
        custom_files_output = Path(args.custom_files_output)
    else:
        custom_files_output = default_output_dir / f'custom_files_{timestamp}.json'

    # Ensure output directory exists
    output_file.parent.mkdir(parents=True, exist_ok=True)
    custom_files_output.parent.mkdir(parents=True, exist_ok=True)

    print(f"Comparing directories:")
    print(f"  Source:   {src_dir}")
    print(f"  Upstream: {upstream_dir}")
    print(f"  Modifications patch: {output_file}")
    print(f"  Custom files list:   {custom_files_output}")
    print()

    # Get current upstream commit for 3-way merge
    upstream_commit = None
    try:
        import subprocess
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=str(upstream_dir),
            capture_output=True,
            text=True,
            check=True
        )
        upstream_commit = result.stdout.strip()
        print(f"  Upstream commit: {upstream_commit[:12]}")
    except Exception as e:
        print(f"Warning: Could not get upstream commit: {e}", file=sys.stderr)
    print()

    # Get all files from both directories
    src_files = get_all_files(str(src_dir))
    upstream_files = get_all_files(str(upstream_dir))

    # Categorize files
    # Custom files: exist in src/ but NOT in upstream/ (these are Mixar-specific additions)
    custom_files = sorted(src_files - upstream_files)

    # Removed files: exist in upstream/ but not in src/ (shouldn't be many)
    removed_files = sorted(upstream_files - src_files)

    # Common files: exist in both
    common_files = sorted(src_files & upstream_files)

    # Check for modifications in common files (these are upstream-modified files)
    upstream_modified_files = []
    for rel_path in common_files:
        src_file = src_dir / rel_path
        upstream_file = upstream_dir / rel_path

        # Skip if either file is binary
        if is_binary_file(str(src_file)) or is_binary_file(str(upstream_file)):
            if args.verbose:
                print(f"Skipping binary file: {rel_path}")
            continue

        # Compare file contents
        try:
            src_content = src_file.read_bytes()
            upstream_content = upstream_file.read_bytes()

            if src_content != upstream_content:
                upstream_modified_files.append(rel_path)
        except Exception as e:
            print(f"Warning: Could not compare {rel_path}: {e}", file=sys.stderr)

    # Print summary
    print("Summary:")
    print(f"  Upstream-modified files: {len(upstream_modified_files)} (will be patched with 3-way merge)")
    print(f"  Custom Mixar files:      {len(custom_files)} (will be preserved as-is)")
    print(f"  Removed from upstream:   {len(removed_files)} (manual review needed)")
    print()

    if not upstream_modified_files and not custom_files:
        print("No differences found. No output files generated.")
        return 0

    # Generate unified diff for UPSTREAM-MODIFIED files only
    diff_lines = []

    # Add header
    diff_lines.append(f"# Mixar Upstream Modifications Patch")
    diff_lines.append(f"# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    diff_lines.append(f"# Source: {src_dir}")
    diff_lines.append(f"# Upstream: {upstream_dir}")
    diff_lines.append("#")
    diff_lines.append(f"# Old upstream commit: {upstream_commit}")
    diff_lines.append(f"# This commit is used as the common ancestor for 3-way merge")
    diff_lines.append("#")
    diff_lines.append(f"# This patch contains ONLY modifications to upstream Blender files.")
    diff_lines.append(f"# Custom Mixar files are listed separately in: {custom_files_output.name}")
    diff_lines.append("#")
    diff_lines.append(f"# Summary: {len(upstream_modified_files)} upstream files modified")
    diff_lines.append("")

    # List modified files
    if upstream_modified_files:
        diff_lines.append("# Modified upstream files:")
        for rel_path in upstream_modified_files:
            diff_lines.append(f"#   M {rel_path}")
        diff_lines.append("")

    diff_lines.append("#" + "=" * 70)
    diff_lines.append("")

    # Generate diffs ONLY for upstream-modified files
    for rel_path in upstream_modified_files:
        src_file = src_dir / rel_path
        upstream_file = upstream_dir / rel_path

        print(f"Processing modified file: {rel_path}")
        file_diff = generate_file_diff(str(src_file), str(upstream_file), rel_path)

        if file_diff:
            diff_lines.extend(file_diff)
            diff_lines.append("")  # Blank line between files

    # Write patch file (upstream modifications only)
    if upstream_modified_files:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(diff_lines))

            print()
            print(f"✓ Upstream modifications patch generated: {output_file}")
            print(f"  Total lines in patch: {len(diff_lines)}")
        except Exception as e:
            print(f"Error writing patch file: {e}", file=sys.stderr)
            return 1
    else:
        print()
        print("No upstream modifications found. Patch file not created.")

    # Write custom files list as JSON
    if custom_files:
        try:
            import json
            custom_files_data = {
                "metadata": {
                    "generated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "src_dir": str(src_dir),
                    "upstream_dir": str(upstream_dir),
                    "total_count": len(custom_files)
                },
                "custom_files": list(custom_files),
                "note": "These files exist in src/ but not in upstream/. They are Mixar-specific and should be preserved as-is during migration."
            }

            with open(custom_files_output, 'w', encoding='utf-8') as f:
                json.dump(custom_files_data, f, indent=2)

            print(f"✓ Custom files list generated: {custom_files_output}")
            print(f"  Total custom files: {len(custom_files)}")
        except Exception as e:
            print(f"Error writing custom files list: {e}", file=sys.stderr)
            return 1
    else:
        print("No custom files found. Custom files list not created.")

    print()
    print("=" * 70)
    print("Generation complete!")
    print()
    print("Next steps:")
    print(f"  1. Review the patch: less {output_file}")
    if custom_files:
        print(f"  2. Review custom files: cat {custom_files_output}")
    print(f"  3. Use migrate_upstream.py to apply changes to new Blender version")
    print()

    return 0


if __name__ == '__main__':
    sys.exit(main())
