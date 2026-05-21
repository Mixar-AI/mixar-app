#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Checkout a specific commit/branch in the upstream submodule and update parent repo's reference.

Usage:
    python checkout_upstream.py <commit-sha|branch-name|tag>

Examples:
    python checkout_upstream.py main
    python checkout_upstream.py blender-v5.0-release
    python checkout_upstream.py e295cdea577771083794e0962a6aba18da229569
    python checkout_upstream.py v4.2.0

After running this script:
    git commit -m "Update upstream to <version>"
    git push

When others run ./scripts/unix/init.sh, they will get this exact commit.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, Optional


# ANSI color codes (works on Unix/Mac, Windows 10+ with ANSI support)
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

    @classmethod
    def disable(cls):
        """Disable colors for Windows compatibility if needed."""
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = cls.NC = ''


def run_command(cmd: list, cwd: Optional[str] = None, check: bool = True, capture: bool = True, env: Optional[dict] = None) -> Tuple[int, str, str]:
    """
    Run a command and return (returncode, stdout, stderr).

    Args:
        cmd: Command and arguments as a list
        cwd: Working directory (None = current dir)
        check: Raise exception on non-zero exit code
        capture: Capture output (if False, output goes to console)
        env: Additional environment variables (merged with os.environ)

    Returns:
        Tuple of (returncode, stdout, stderr)
    """
    # Prepare environment
    command_env = os.environ.copy()
    if env:
        command_env.update(env)

    try:
        if capture:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                check=check,
                capture_output=True,
                text=True,
                env=command_env
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        else:
            result = subprocess.run(cmd, cwd=cwd, check=check, env=command_env)
            return result.returncode, '', ''
    except subprocess.CalledProcessError as e:
        if capture:
            return e.returncode, e.stdout.strip() if e.stdout else '', e.stderr.strip() if e.stderr else ''
        else:
            return e.returncode, '', ''


def print_error(msg: str):
    """Print error message in red."""
    print(f"{Colors.RED}Error: {msg}{Colors.NC}", file=sys.stderr)


def print_success(msg: str):
    """Print success message in green."""
    print(f"{Colors.GREEN}{msg}{Colors.NC}")


def print_warning(msg: str):
    """Print warning message in yellow."""
    print(f"{Colors.YELLOW}{msg}{Colors.NC}")


def print_info(msg: str):
    """Print info message in blue."""
    print(f"{Colors.BLUE}{msg}{Colors.NC}")


def check_git_available() -> bool:
    """Check if git is available in PATH."""
    returncode, _, _ = run_command(['git', '--version'], check=False)
    return returncode == 0


def get_project_root() -> Path:
    """Get the project root directory (parent of scripts/)."""
    script_path = Path(__file__).resolve()
    # scripts/upgrade/checkout_upstream.py -> go up 2 levels
    return script_path.parent.parent.parent


def check_uncommitted_changes(repo_path: Path) -> bool:
    """Check if there are uncommitted changes in the repository."""
    # Check diff-index (staged and unstaged changes)
    returncode, _, _ = run_command(
        ['git', 'diff-index', '--quiet', 'HEAD', '--'],
        cwd=str(repo_path),
        check=False
    )
    return returncode != 0


def check_untracked_files(repo_path: Path) -> list:
    """Get list of untracked files."""
    returncode, stdout, _ = run_command(
        ['git', 'ls-files', '--others', '--exclude-standard'],
        cwd=str(repo_path),
        check=False
    )
    if returncode == 0 and stdout:
        return stdout.split('\n')
    return []


def get_current_commit(repo_path: Path) -> Tuple[str, str]:
    """Get current commit SHA and short SHA."""
    returncode, full_sha, _ = run_command(
        ['git', 'rev-parse', 'HEAD'],
        cwd=str(repo_path)
    )
    if returncode != 0:
        return '', ''

    returncode, short_sha, _ = run_command(
        ['git', 'rev-parse', '--short', 'HEAD'],
        cwd=str(repo_path)
    )

    return full_sha, short_sha


def verify_ref_exists(repo_path: Path, ref: str) -> Tuple[bool, str]:
    """
    Verify if a reference exists.

    Returns:
        Tuple of (exists, resolved_ref)
        resolved_ref might be 'origin/{ref}' if local ref doesn't exist
    """
    # Try the ref as-is
    returncode, _, _ = run_command(
        ['git', 'rev-parse', '--verify', f'{ref}^{{commit}}'],
        cwd=str(repo_path),
        check=False
    )

    if returncode == 0:
        return True, ref

    # Try with origin/ prefix
    returncode, _, _ = run_command(
        ['git', 'rev-parse', '--verify', f'origin/{ref}^{{commit}}'],
        cwd=str(repo_path),
        check=False
    )

    if returncode == 0:
        return True, f'origin/{ref}'

    return False, ref


def get_commit_info(repo_path: Path, commit: str = 'HEAD') -> dict:
    """Get commit information."""
    returncode, subject, _ = run_command(
        ['git', 'log', '-1', '--pretty=format:%s', commit],
        cwd=str(repo_path)
    )

    returncode2, date, _ = run_command(
        ['git', 'log', '-1', '--pretty=format:%ci', commit],
        cwd=str(repo_path)
    )

    return {
        'subject': subject if returncode == 0 else '',
        'date': date if returncode2 == 0 else ''
    }


def is_detached_head(repo_path: Path) -> bool:
    """Check if repository is in detached HEAD state."""
    returncode, _, _ = run_command(
        ['git', 'symbolic-ref', '-q', 'HEAD'],
        cwd=str(repo_path),
        check=False
    )
    return returncode != 0


def main():
    """Main entry point."""
    # Check if colors should be disabled (for Windows compatibility)
    if sys.platform == 'win32' and not os.environ.get('ANSICON'):
        # Windows without ANSI support
        Colors.disable()

    # Parse arguments
    force = False
    target_ref = None

    for arg in sys.argv[1:]:
        if arg == '--force' or arg == '-f':
            force = True
        elif not target_ref:
            target_ref = arg

    if not target_ref:
        print_error("No commit/branch specified")
        print()
        print("Usage: python checkout_upstream.py [--force] <commit-sha|branch-name|tag>")
        print()
        print("Options:")
        print("  --force, -f    Force checkout (discard uncommitted changes)")
        print()
        print("Examples:")
        print("  python checkout_upstream.py main")
        print("  python checkout_upstream.py blender-v5.0-release")
        print("  python checkout_upstream.py --force blender-v5.0-release")
        print("  python checkout_upstream.py e295cdea577771083794e0962a6aba18da229569")
        print("  python checkout_upstream.py v4.2.0")
        return 1

    # Check if git is available
    if not check_git_available():
        print_error("git is not available in PATH")
        return 1

    # Get project root
    root_dir = get_project_root()
    upstream_dir = root_dir / 'upstream'

    print_info("=== Updating Upstream Submodule ===")
    print(f"Target: {Colors.GREEN}{target_ref}{Colors.NC}")
    print()

    # Check if upstream directory exists
    if not upstream_dir.exists():
        print_error("upstream/ directory not found")
        print("Run ./scripts/unix/init.sh first to initialize the submodule")
        return 1

    # Check if upstream is a git repository
    if not (upstream_dir / '.git').exists():
        print_error("upstream/ is not a git repository")
        print("Run ./scripts/unix/init.sh first to initialize the submodule")
        return 1

    # Check for uncommitted changes
    if check_uncommitted_changes(upstream_dir):
        if force:
            print_warning("Warning: Discarding uncommitted changes (--force mode)")
            returncode, _, _ = run_command(
                ['git', 'reset', '--hard'],
                cwd=str(upstream_dir),
                check=False
            )
            if returncode != 0:
                print_error("Failed to reset uncommitted changes")
                return 1
            print("Reset complete.")
            print()
        else:
            print_error("You have uncommitted changes in upstream/")
            print()
            print("Please commit or stash your changes first:")
            print("  cd upstream")
            print("  git status")
            print("  git stash  # or git commit")
            print()
            print("Or, use --force to discard changes and checkout:")
            script_name = 'checkout_upstream.py'
            print_warning(f"  python scripts/upgrade/{script_name} --force {target_ref}")
            return 1

    # Check for untracked files
    untracked = check_untracked_files(upstream_dir)
    if untracked:
        if force:
            print_warning("Warning: Cleaning untracked files (--force mode)")
            returncode, _, _ = run_command(
                ['git', 'clean', '-fd'],
                cwd=str(upstream_dir),
                check=False
            )
            if returncode != 0:
                print_error("Failed to clean untracked files")
                return 1
            print("Clean complete.")
            print()
        else:
            print_warning("Warning: You have untracked files in upstream/")
            print("These will be left as-is. To clean them:")
            print("  cd upstream && git clean -fd")
            print()

    # Clean up lib submodules if in force mode (will be pulled later via init.sh)
    if force:
        lib_dir = upstream_dir / 'lib'
        if lib_dir.exists():
            print_warning("Deinitializing upstream/lib submodules (will be reinitialized by init.sh)")
            # Deinitialize lib submodules
            returncode, _, _ = run_command(
                ['git', 'submodule', 'deinit', '-f', 'lib'],
                cwd=str(upstream_dir),
                check=False
            )
            if returncode != 0:
                print_warning("Failed to deinit lib submodules, trying to remove directory...")
                try:
                    shutil.rmtree(lib_dir)
                    print("Removed upstream/lib directory")
                except Exception as e:
                    print_error(f"Failed to remove upstream/lib: {e}")
                    return 1
            else:
                print("Deinitialized lib submodules")
            print()

    # Get current commit
    current_commit, current_short = get_current_commit(upstream_dir)
    print(f"Current commit: {current_short}")
    print()

    # Fetch latest changes
    print_info("Fetching latest changes from remote...")
    returncode, _, stderr = run_command(
        ['git', 'fetch', 'origin', '--quiet'],
        cwd=str(upstream_dir),
        check=False
    )

    if returncode != 0:
        print_warning("Warning: Failed to fetch from origin")
        print("Continuing with local refs...")

    # Verify reference exists
    exists, resolved_ref = verify_ref_exists(upstream_dir, target_ref)
    if not exists:
        print_error(f"Reference '{target_ref}' not found")
        print()
        print("Available branches:")
        returncode, branches, _ = run_command(
            ['git', 'branch', '-a'],
            cwd=str(upstream_dir),
            check=False
        )
        if returncode == 0:
            for line in branches.split('\n'):
                if 'main' in line or 'blender-v' in line:
                    print(f"  {line.strip()}")
        print()
        print("To see all branches: cd upstream && git branch -a")
        return 1

    if resolved_ref != target_ref:
        print(f"Using remote branch: {resolved_ref}")

    # Checkout the target reference (skip LFS download to avoid errors)
    print_info(f"Checking out {resolved_ref}...")
    print_info("(Skipping LFS file download - run init.sh later to download assets)")
    returncode, _, stderr = run_command(
        ['git', 'checkout', resolved_ref, '--quiet'],
        cwd=str(upstream_dir),
        check=False,
        env={'GIT_LFS_SKIP_SMUDGE': '1'}
    )

    if returncode != 0:
        print_error(f"Failed to checkout {resolved_ref}")
        if stderr:
            print(stderr)
        return 1

    # Get new commit info
    new_commit, new_short = get_current_commit(upstream_dir)
    commit_info = get_commit_info(upstream_dir)

    print_success("Successfully checked out:")
    print(f"  Commit: {new_short}")
    print(f"  Subject: {commit_info['subject']}")
    print(f"  Date: {commit_info['date']}")
    print()

    # Check if detached HEAD
    if is_detached_head(upstream_dir):
        print_warning("Note: In detached HEAD state (this is expected for submodules)")
    else:
        returncode, branch, _ = run_command(
            ['git', 'branch', '--show-current'],
            cwd=str(upstream_dir)
        )
        if returncode == 0:
            print_warning(f"Note: On branch {branch}")
    print()

    # Check if anything changed
    if current_commit == new_commit:
        print_warning(f"No change: Already at commit {new_short}")
        print("Submodule not updated.")
        return 0

    # Stage the submodule change in parent repo
    print_info("Staging submodule change in parent repo...")
    returncode, _, _ = run_command(
        ['git', 'add', 'upstream'],
        cwd=str(root_dir)
    )

    if returncode != 0:
        print_error("Failed to stage submodule change")
        return 1

    print_success("Submodule updated successfully!")
    print()

    # Summary
    print("=== Summary ===")
    print(f"  Old commit: {current_short}")
    print(f"  New commit: {new_short}")
    print()

    # Show staged changes
    print("=== Staged Changes ===")
    returncode, output, _ = run_command(
        ['git', 'diff', '--cached', '--submodule', 'upstream'],
        cwd=str(root_dir),
        check=False
    )
    if returncode == 0 and output:
        print(output)
    print()

    # Show submodule status
    print("=== Submodule Status ===")
    returncode, output, _ = run_command(
        ['git', 'submodule', 'status', 'upstream'],
        cwd=str(root_dir),
        check=False
    )
    if returncode == 0 and output:
        print(output)
    print()

    # Next steps
    print_success("=== Next Steps ===")
    print("1. Review the change above")
    print("2. Commit the submodule update:")
    print(f"   {Colors.BLUE}git commit -m \"Update upstream to {target_ref} ({new_short})\"{Colors.NC}")
    print()
    print("3. Push to remote:")
    print(f"   {Colors.BLUE}git push{Colors.NC}")
    print()
    print("4. Other developers can get this exact commit by running:")
    print(f"   {Colors.BLUE}./scripts/unix/init.sh{Colors.NC}")
    print()
    print_warning("Note: You may want to run ./scripts/unix/init.sh to download LFS files")
    print_warning("and update dependencies for the new Blender version.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
