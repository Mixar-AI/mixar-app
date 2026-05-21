#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Master script to migrate Mixar customizations to a new upstream Blender version.

This orchestrates the complete migration workflow:
1. Generate diff from current src/
2. Checkout new upstream version
3. Apply diff to new upstream
4. Resolve conflicts interactively
5. Report success

Usage:
    python migrate_upstream.py <branch-or-commit> [options]

Examples:
    # Interactive migration (recommended)
    python migrate_upstream.py blender-v5.0-release

    # Automatic mode (stops only on conflicts)
    python migrate_upstream.py blender-v5.0-release --auto

    # Force checkout and custom fuzzy matching
    python migrate_upstream.py main --force --fuzzy 3
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple


# ANSI color codes
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    BOLD = '\033[1m'
    NC = '\033[0m'

    @classmethod
    def disable(cls):
        """Disable colors for Windows compatibility."""
        for attr in ['RED', 'GREEN', 'YELLOW', 'BLUE', 'CYAN', 'MAGENTA', 'BOLD', 'NC']:
            setattr(cls, attr, '')


class MigrationOrchestrator:
    """Orchestrates the complete upstream migration workflow."""

    def __init__(self, target_ref: str, project_root: Path, auto_mode: bool = False,
                 force: bool = False, fuzzy: int = 2, keep_patch: bool = False):
        self.target_ref = target_ref
        self.project_root = project_root
        self.auto_mode = auto_mode
        self.force = force
        self.fuzzy = fuzzy
        self.keep_patch = keep_patch

        # Paths
        self.scripts_dir = project_root / 'scripts' / 'upgrade'
        self.patches_dir = self.scripts_dir / 'patches'
        self.src_dir = project_root / 'src'
        self.upstream_dir = project_root / 'upstream'

        # State
        self.patch_file: Optional[Path] = None
        self.custom_files_json: Optional[Path] = None
        self.backup_dir: Optional[Path] = None
        self.current_step = 0
        self.total_steps = 5

    def print_header(self):
        """Print the script header."""
        print()
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print(f"{Colors.CYAN}║{Colors.BOLD}{'Mixar Upstream Migration Tool'.center(68)}{Colors.NC}{Colors.CYAN}║{Colors.NC}")
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print()
        print(f"{Colors.BOLD}Target:{Colors.NC} {self.target_ref}")
        print()

    def print_step(self, step_num: int, title: str):
        """Print a step header."""
        self.current_step = step_num
        print()
        print(f"{Colors.BLUE}[Step {step_num}/{self.total_steps}] {title}...{Colors.NC}")

    def print_success(self, msg: str):
        """Print success message."""
        print(f"{Colors.GREEN}✓ {msg}{Colors.NC}")

    def print_error(self, msg: str):
        """Print error message."""
        print(f"{Colors.RED}✗ {msg}{Colors.NC}")

    def print_warning(self, msg: str):
        """Print warning message."""
        print(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")

    def print_info(self, msg: str):
        """Print info message."""
        print(f"  {msg}")

    def run_command(self, cmd: list, description: str, check: bool = True) -> Tuple[int, str, str]:
        """
        Run a command and return result.

        Returns:
            Tuple of (returncode, stdout, stderr)
        """
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                check=check,
                capture_output=True,
                text=True
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.CalledProcessError as e:
            return e.returncode, e.stdout or '', e.stderr or ''

    def wait_for_user(self, prompt: str = "Press Enter to continue..."):
        """Wait for user input in interactive mode."""
        if not self.auto_mode:
            try:
                input(f"\n{Colors.YELLOW}{prompt}{Colors.NC}")
            except KeyboardInterrupt:
                print()
                raise

    def validate_environment(self) -> bool:
        """Validate that the environment is ready for migration."""
        self.print_step(0, "Validating environment")

        # Check directories exist
        if not self.src_dir.exists():
            self.print_warning("src/ directory doesn't exist (will be created)")

        if not self.upstream_dir.exists():
            self.print_error("upstream/ directory doesn't exist")
            self.print_info("Run ./scripts/unix/init.sh first to initialize upstream")
            return False

        if not (self.scripts_dir / 'generate_diff.py').exists():
            self.print_error("generate_diff.py not found")
            return False

        if not (self.scripts_dir / 'checkout_upstream.py').exists():
            self.print_error("checkout_upstream.py not found")
            return False

        if not (self.scripts_dir / 'apply_patch.py').exists():
            self.print_error("apply_patch.py not found")
            return False

        # Check for uncommitted changes in upstream
        returncode, _, _ = self.run_command(
            ['git', '-C', 'upstream', 'diff-index', '--quiet', 'HEAD', '--'],
            "Check upstream status",
            check=False
        )

        if returncode != 0 and not self.force:
            self.print_warning("Uncommitted changes detected in upstream/")
            self.print_info("Use --force to discard changes automatically")
            if not self.auto_mode:
                response = input(f"{Colors.YELLOW}Continue anyway? (y/N): {Colors.NC}").strip().lower()
                if response != 'y':
                    return False

        self.print_success("Environment validated")
        return True

    def step1_generate_diff(self) -> bool:
        """Step 1: Generate diff from current modifications."""
        self.print_step(1, "Generating diff from current modifications")

        # Create patches directory if it doesn't exist
        self.patches_dir.mkdir(parents=True, exist_ok=True)

        # Generate filenames
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.patch_file = self.patches_dir / f'mixar_modifications_{timestamp}.patch'
        self.custom_files_json = self.patches_dir / f'custom_files_{timestamp}.json'

        # Run generate_diff.py
        cmd = [
            sys.executable,
            str(self.scripts_dir / 'generate_diff.py'),
            '--output', str(self.patch_file),
            '--custom-files-output', str(self.custom_files_json)
        ]

        returncode, stdout, stderr = self.run_command(cmd, "Generate diff", check=False)

        if returncode != 0:
            self.print_error("Failed to generate diff")
            if stderr:
                print(stderr)
            return False

        # Check which files were created
        patch_exists = self.patch_file.exists()
        custom_files_exist = self.custom_files_json.exists()

        if patch_exists:
            self.print_success(f"Modifications patch: {self.patch_file.name}")
        else:
            self.print_info("No upstream modifications found")

        if custom_files_exist:
            self.print_success(f"Custom files list: {self.custom_files_json.name}")
        else:
            self.print_info("No custom files found")

        if not patch_exists and not custom_files_exist:
            self.print_error("No differences found")
            return False

        # Show summary from stdout
        for line in stdout.split('\n'):
            if 'upstream-modified' in line.lower() or 'custom' in line.lower() or 'summary' in line.lower():
                self.print_info(line.strip())

        return True

    def step2_checkout_upstream(self) -> bool:
        """Step 2: Checkout new upstream version."""
        self.print_step(2, f"Checking out new upstream version: {self.target_ref}")

        cmd = [
            sys.executable,
            str(self.scripts_dir / 'checkout_upstream.py'),
            self.target_ref
        ]

        if self.force:
            cmd.append('--force')

        returncode, stdout, stderr = self.run_command(cmd, "Checkout upstream", check=False)

        if returncode != 0:
            self.print_error("Failed to checkout upstream")
            if stderr:
                print(stderr)
            self.print_info("\nTroubleshooting:")
            self.print_info("  - Check if the branch/commit exists")
            self.print_info("  - Use --force to discard uncommitted changes")
            self.print_info("  - Manually resolve issues in upstream/")
            return False

        # Extract commit info from stdout
        for line in stdout.split('\n'):
            if 'checked out' in line.lower() or 'commit:' in line.lower():
                self.print_success(line.strip())

        return True

    def step3_apply_patch(self) -> Tuple[bool, bool]:
        """
        Step 3: Apply patch to new upstream.

        Returns:
            Tuple of (success, has_conflicts)
        """
        self.print_step(3, "Applying modifications to new upstream (3-way merge)")

        # Check if we have at least a patch file or custom files
        if not self.patch_file or not self.patch_file.exists():
            self.print_warning("No modifications patch found")
            # If we only have custom files, that's OK - they'll be preserved
            if not self.custom_files_json or not self.custom_files_json.exists():
                self.print_error("No patch or custom files found")
                return False, False
            else:
                self.print_info("Only custom files to preserve, no patching needed")
                return True, False

        cmd = [
            sys.executable,
            str(self.scripts_dir / 'apply_patch.py'),
            str(self.patch_file),
            '--report', str(self.project_root / 'conflicts_report.json')
        ]

        # Add custom files JSON if it exists
        if self.custom_files_json and self.custom_files_json.exists():
            cmd.extend(['--custom-files', str(self.custom_files_json)])

        returncode, stdout, stderr = self.run_command(cmd, "Apply patch", check=False)

        # Check if returncode indicates failure
        if returncode != 0:
            # Show full output from apply_patch.py (includes detailed error info)
            print(stdout)
            if stderr:
                print(stderr)

        # Parse output for statistics
        has_conflicts = False
        for line in stdout.split('\n'):
            if 'conflicts:' in line.lower():
                # Extract conflict count
                try:
                    count = int(line.split(':')[-1].strip())
                    if count > 0:
                        has_conflicts = True
                except ValueError:
                    pass

        # Check backup directory
        backups = list(self.project_root.glob('src_backup_*'))
        if backups:
            self.backup_dir = max(backups, key=lambda p: p.name)
            self.print_info(f"Backup saved: {self.backup_dir.name}/")

        if returncode == 0:
            self.print_success("Patch applied successfully")
            return True, has_conflicts
        elif has_conflicts:
            self.print_warning("Patch applied with conflicts")
            return True, has_conflicts
        else:
            self.print_error("Failed to apply patch")
            return False, False

    def step4_resolve_conflicts(self) -> bool:
        """Step 4: Interactively resolve conflicts."""
        self.print_step(4, "Resolving conflicts")

        # Check for conflict markers (git merge-file uses standard git format)
        returncode, stdout, _ = self.run_command(
            ['grep', '-r', '--include=*.py', '--include=*.c', '--include=*.cc',
             '--include=*.cpp', '--include=*.h', '--include=*.hpp',
             '<<<<<<< ', 'src/'],
            "Search for conflicts",
            check=False
        )

        conflict_files = []
        if returncode == 0 and stdout:
            # Parse grep output
            for line in stdout.split('\n'):
                if line.strip():
                    file_path = line.split(':')[0]
                    if file_path not in conflict_files:
                        conflict_files.append(file_path)

        if not conflict_files:
            self.print_success("No conflicts detected")
            return True

        # Show conflicts
        print()
        print(f"{Colors.YELLOW}Conflicts detected in {len(conflict_files)} file(s):{Colors.NC}")
        for i, file_path in enumerate(conflict_files[:10], 1):
            print(f"  {i}. {file_path}")
        if len(conflict_files) > 10:
            print(f"  ... and {len(conflict_files) - 10} more")

        print()
        print(f"{Colors.CYAN}Resolution commands:{Colors.NC}")
        print(f"  Search for conflicts:  {Colors.BOLD}grep -r '<<<<<<< ' src/{Colors.NC}")
        print(f"  View backup:           {Colors.BOLD}ls {self.backup_dir}/{Colors.NC}" if self.backup_dir else "")
        print(f"  Edit file:             {Colors.BOLD}vim/nano src/path/to/file{Colors.NC}")

        # Load conflict report if available
        report_file = self.project_root / 'conflicts_report.json'
        if report_file.exists():
            print(f"  Detailed report:       {Colors.BOLD}cat conflicts_report.json{Colors.NC}")

        print()
        print(f"{Colors.YELLOW}Conflict markers format (standard git 3-way merge):{Colors.NC}")
        print(f"  {Colors.CYAN}<<<<<<< [new upstream file]{Colors.NC}")
        print(f"  {Colors.BOLD}code from new upstream{Colors.NC}")
        print(f"  {Colors.CYAN}||||||| [old upstream ancestor]{Colors.NC}")
        print(f"  {Colors.BOLD}code from old upstream (common ancestor){Colors.NC}")
        print(f"  {Colors.CYAN}======={Colors.NC}")
        print(f"  {Colors.BOLD}your custom modifications{Colors.NC}")
        print(f"  {Colors.CYAN}>>>>>>> [your modified file]{Colors.NC}")

        # Wait for user to resolve
        self.wait_for_user("\nResolve conflicts and press Enter to continue...")

        # Verify conflicts are resolved
        returncode, stdout, _ = self.run_command(
            ['grep', '-r', '--include=*.py', '--include=*.c', '--include=*.cc',
             '--include=*.cpp', '--include=*.h', '--include=*.hpp',
             '<<<<<<< ', 'src/'],
            "Check remaining conflicts",
            check=False
        )

        if returncode == 0 and stdout.strip():
            self.print_error("Conflicts still remain!")
            remaining = len([l for l in stdout.split('\n') if l.strip()])
            self.print_info(f"Found {remaining} conflict marker(s)")

            if not self.auto_mode:
                response = input(f"{Colors.YELLOW}Continue anyway? (y/N): {Colors.NC}").strip().lower()
                if response != 'y':
                    return False

        self.print_success("All conflicts resolved")
        return True

    def step5_report_success(self):
        """Step 5: Report successful migration."""
        self.print_step(5, "Migration complete")

        print()
        print(f"{Colors.GREEN}{'═' * 70}{Colors.NC}")
        print(f"{Colors.GREEN}║{Colors.BOLD}{'Migration Successful!'.center(68)}{Colors.NC}{Colors.GREEN}║{Colors.NC}")
        print(f"{Colors.GREEN}{'═' * 70}{Colors.NC}")
        print()

        print(f"{Colors.CYAN}{Colors.BOLD}Next steps:{Colors.NC}")
        print(f"  1. Test build:    {Colors.BOLD}./scripts/unix/build.sh{Colors.NC}")
        print(f"  2. Review changes:{Colors.BOLD} git diff src/{Colors.NC}")
        print(f"  3. Commit:        {Colors.BOLD}git add src/ upstream/ .gitmodules{Colors.NC}")
        print(f"                    {Colors.BOLD}git commit -m 'Migrate to {self.target_ref}'{Colors.NC}")

        if self.backup_dir:
            print()
            print(f"{Colors.CYAN}Backup location:{Colors.NC} {self.backup_dir}/")

        if self.patch_file and self.keep_patch:
            print(f"{Colors.CYAN}Patch file:{Colors.NC} {self.patch_file}")
        elif self.patch_file and not self.keep_patch:
            print()
            print(f"{Colors.YELLOW}Note:{Colors.NC} Patch file can be deleted: {self.patch_file}")

        print()

    def run(self) -> int:
        """Run the complete migration workflow."""
        try:
            self.print_header()

            # Step 0: Validate environment
            if not self.validate_environment():
                return 1

            if not self.auto_mode:
                self.wait_for_user("Ready to start migration? Press Enter to continue...")

            # Step 1: Generate diff
            if not self.step1_generate_diff():
                self.print_error("Migration failed at step 1")
                return 1

            # Step 2: Checkout upstream
            if not self.step2_checkout_upstream():
                self.print_error("Migration failed at step 2")
                return 1

            # Step 3: Apply patch
            success, has_conflicts = self.step3_apply_patch()
            if not success:
                self.print_error("Migration failed at step 3")
                return 1

            # Step 4: Resolve conflicts (if any)
            if has_conflicts:
                if not self.step4_resolve_conflicts():
                    self.print_error("Migration failed at step 4")
                    self.print_info("You can manually resolve conflicts and re-run later")
                    return 1
            else:
                self.print_step(4, "No conflicts to resolve")
                self.print_success("Skipping conflict resolution")

            # Step 5: Report success
            self.step5_report_success()

            return 0

        except KeyboardInterrupt:
            print()
            self.print_warning("\nMigration interrupted by user")
            self.print_info(f"Progress saved - you can resume manually")
            if self.patch_file:
                self.print_info(f"Patch file: {self.patch_file}")
            return 130

        except Exception as e:
            print()
            self.print_error(f"Migration failed: {e}")
            return 1


def main():
    """Main entry point."""
    # Check if colors should be disabled
    if sys.platform == 'win32' and not os.environ.get('ANSICON'):
        Colors.disable()

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        'target_ref',
        help='Target branch or commit to migrate to (e.g., blender-v5.0-release, main)'
    )
    parser.add_argument(
        '--auto',
        action='store_true',
        help='Automatic mode (only stop on conflicts)'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Force checkout (discard uncommitted changes in upstream/)'
    )
    parser.add_argument(
        '--fuzzy',
        type=int,
        default=2,
        help='Fuzzy matching tolerance for patch application (default: 2)'
    )
    parser.add_argument(
        '--keep-patch',
        action='store_true',
        help='Keep the generated patch file after migration'
    )

    args = parser.parse_args()

    # Get project root
    script_dir = Path(__file__).parent.parent.parent
    project_root = script_dir.resolve()

    # Create orchestrator
    orchestrator = MigrationOrchestrator(
        target_ref=args.target_ref,
        project_root=project_root,
        auto_mode=args.auto,
        force=args.force,
        fuzzy=args.fuzzy,
        keep_patch=args.keep_patch
    )

    return orchestrator.run()


if __name__ == '__main__':
    sys.exit(main())
