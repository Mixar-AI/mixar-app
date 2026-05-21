#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Apply custom Mixar modifications to new upstream Blender version using 3-way merge.

This script uses git merge-file for proper 3-way merging with conflict markers.
It handles upstream-modified files separately from custom Mixar files.

Workflow:
1. Backup src/ to src_backup_TIMESTAMP/
2. For each upstream-modified file:
   a. Get OLD upstream version (before migration)
   b. Get NEW upstream version (after migration)
   c. Get MODIFIED version (from src backup)
   d. Perform 3-way merge: merge NEW with MODIFIED using OLD as ancestor
   e. Write result with conflict markers to src/
3. Preserve all custom files (don't delete or modify them)
4. Generate conflict report for manual resolution

Usage:
    python apply_patch.py patches/mixar_modifications_TIMESTAMP.patch [options]

Options:
    --custom-files FILE    JSON file listing custom files to preserve
    --dry-run              Check without applying
    --report FILE          Output JSON conflict report

Examples:
    # Basic usage
    python apply_patch.py patches/mixar_modifications_2025-11-18.patch

    # With custom files list
    python apply_patch.py patches/mixar_modifications_2025-11-18.patch \\
        --custom-files patches/custom_files_2025-11-18.json

    # Dry run
    python apply_patch.py patches/mixar_modifications_2025-11-18.patch --dry-run
"""

import os
import sys
import json
import shutil
import subprocess
import argparse
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict


# ANSI color codes
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'

    @classmethod
    def disable(cls):
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = cls.CYAN = cls.BOLD = cls.NC = ''


@dataclass
class ConflictInfo:
    """Information about a patch conflict."""
    file_path: str
    reason: str
    hunk_details: str
    backup_file: Optional[str] = None
    upstream_file: Optional[str] = None
    patch_content: Optional[str] = None


@dataclass
class MigrationStats:
    """Statistics about the migration process."""
    total_files: int = 0
    successful: int = 0
    failed: int = 0
    conflicts: int = 0


class PatchApplier:
    """Main class for applying patches using git 3-way merge."""

    def __init__(self, patch_file: Path, project_root: Path, custom_files_json: Optional[Path] = None, dry_run: bool = False):
        # Convert patch_file to absolute path
        self.patch_file = patch_file.resolve()
        self.project_root = project_root
        self.custom_files_json = custom_files_json.resolve() if custom_files_json else None
        self.dry_run = dry_run

        # Directories
        self.src_dir = project_root / 'src'
        self.upstream_dir = project_root / 'upstream'
        self.backup_dir = None

        # State
        self.conflicts: List[ConflictInfo] = []
        self.stats = MigrationStats()
        self.failed_files: List[str] = []
        self.custom_files: List[str] = []
        self.old_upstream_commit: Optional[str] = None

        # Setup logging
        self.setup_logging()

    def setup_logging(self):
        """Setup logging."""
        log_file = self.project_root / f'patch_apply_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'

        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def print_info(self, msg: str):
        print(f"{Colors.BLUE}{msg}{Colors.NC}")

    def print_success(self, msg: str):
        print(f"{Colors.GREEN}✓ {msg}{Colors.NC}")

    def print_warning(self, msg: str):
        print(f"{Colors.YELLOW}⚠ {msg}{Colors.NC}")

    def print_error(self, msg: str):
        print(f"{Colors.RED}✗ {msg}{Colors.NC}")

    def backup_src(self) -> Path:
        """Backup src/ directory."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.backup_dir = self.project_root / f'src_backup_{timestamp}'

        self.print_info(f"Backing up src/ to {self.backup_dir.name}/...")

        if self.dry_run:
            self.print_warning("[DRY RUN] Would backup src/")
            return self.backup_dir

        if self.src_dir.exists():
            shutil.copytree(self.src_dir, self.backup_dir, symlinks=True)
            self.print_success(f"Backup created: {self.backup_dir}")
        else:
            self.print_warning("src/ doesn't exist, nothing to backup")

        return self.backup_dir

    def load_custom_files(self):
        """Load list of custom files from JSON."""
        if not self.custom_files_json or not self.custom_files_json.exists():
            self.print_warning("No custom files list provided")
            return

        try:
            with open(self.custom_files_json, 'r') as f:
                data = json.load(f)
                self.custom_files = data.get('custom_files', [])
                self.print_info(f"Loaded {len(self.custom_files)} custom files to preserve")
        except Exception as e:
            self.logger.error(f"Failed to load custom files JSON: {e}")
            self.print_error(f"Failed to load custom files: {e}")

    def get_old_upstream_commit(self):
        """Get the OLD upstream commit from patch header."""
        self.print_info("Detecting old upstream commit...")

        # Parse patch header for commit info
        try:
            with open(self.patch_file, 'r') as f:
                for line in f:
                    if line.startswith("# Old upstream commit:"):
                        self.old_upstream_commit = line.split(":")[-1].strip()
                        break
        except Exception as e:
            self.logger.error(f"Failed to parse patch header: {e}")

        if self.old_upstream_commit:
            self.print_success(f"Found old upstream commit: {self.old_upstream_commit[:12]}")
            self.logger.info(f"Using commit {self.old_upstream_commit} as 3-way merge ancestor")
        else:
            self.print_warning("Could not determine old upstream commit from patch header")
            self.print_warning("Will fall back to 2-way merge (copy from backup)")
            self.logger.warning("3-way merge not available - patch file missing commit info")

    def parse_patch_files(self) -> List[str]:
        """Parse patch to extract list of modified files."""
        self.print_info("Parsing patch file...")

        try:
            with open(self.patch_file, 'r') as f:
                content = f.read()

            # Extract file paths from diff headers (unified diff format)
            # Look for lines like: +++ b/path/to/file.cc
            file_pattern = re.compile(r'^[\+]{3} b/(.+)$', re.MULTILINE)
            files = file_pattern.findall(content)

            self.stats.total_files = len(files)
            self.print_success(f"Found {len(files)} files to patch")

            return files

        except Exception as e:
            self.logger.error(f"Failed to parse patch: {e}")
            self.print_error(f"Failed to parse patch: {e}")
            return []

    def get_file_from_commit(self, file_path: str, commit: str) -> Optional[bytes]:
        """Get file content from a specific upstream commit."""
        try:
            result = subprocess.run(
                ['git', 'show', f'{commit}:{file_path}'],
                cwd=str(self.upstream_dir),
                capture_output=True,
                check=False
            )

            if result.returncode == 0:
                return result.stdout
            else:
                self.logger.warning(f"File {file_path} not found in commit {commit}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to get file from commit: {e}")
            return None

    def apply_3way_merge(self, file_path: str) -> bool:
        """Apply 3-way merge for a single file.

        Returns:
            True if successful (even with conflicts), False on error
        """
        self.print_info(f"Merging: {file_path}")

        # Paths
        src_file = self.src_dir / file_path
        upstream_file = self.upstream_dir / file_path
        backup_file = self.backup_dir / file_path if self.backup_dir else None

        if self.dry_run:
            self.logger.info(f"[DRY RUN] Would merge {file_path}")
            return True

        # Get the three versions
        # OLD: from old upstream commit (ancestor)
        # NEW: from new upstream (current upstream/)
        # MODIFIED: from backup (our changes)

        try:
            # NEW version (from current upstream)
            if not upstream_file.exists():
                self.logger.error(f"File not found in new upstream: {file_path}")
                self.print_error(f"File not found in new upstream: {file_path}")
                self.failed_files.append(file_path)
                return False

            new_content = upstream_file.read_bytes()

            # MODIFIED version (from backup)
            if not backup_file or not backup_file.exists():
                self.logger.warning(f"No backup found for {file_path}, using current src/")
                if src_file.exists():
                    modified_content = src_file.read_bytes()
                else:
                    # File doesn't exist in src - just copy from upstream
                    src_file.parent.mkdir(parents=True, exist_ok=True)
                    src_file.write_bytes(new_content)
                    self.logger.info(f"Copied new file from upstream: {file_path}")
                    return True
            else:
                modified_content = backup_file.read_bytes()

            # OLD version (from old upstream commit)
            old_content = None
            if self.old_upstream_commit:
                old_content = self.get_file_from_commit(file_path, self.old_upstream_commit)

            # If we don't have old version, fall back to 2-way merge
            if old_content is None:
                self.logger.warning(f"No old version available for {file_path}, using 2-way merge")
                self.print_warning(f"  ⚠ 2-way merge (no ancestor): {file_path}")
                # Just use the modified version
                src_file.parent.mkdir(parents=True, exist_ok=True)
                src_file.write_bytes(modified_content)
                self.stats.successful += 1
                return True

            # Write temporary files for merge
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                old_file = tmp_path / 'old'
                new_file = tmp_path / 'new'
                modified_file = tmp_path / 'modified'
                output_file = tmp_path / 'output'

                old_file.write_bytes(old_content)
                new_file.write_bytes(new_content)
                modified_file.write_bytes(modified_content)

                # Run git merge-file with diff3 style markers
                # git merge-file [options] <current-file> <base-file> <other-file>
                # Format: <current> <base> <other>
                # where current is what we're updating, base is ancestor, other is the other version
                #
                # We want: <new> <old> <modified>
                # This merges modified into new, using old as ancestor
                #
                # --diff3: Show ||||||| markers with ancestor content (helps understand conflicts)
                # -p: Write to stdout instead of modifying files

                result = subprocess.run(
                    ['git', 'merge-file', '-p', '--diff3', str(new_file), str(old_file), str(modified_file)],
                    capture_output=True,
                    check=False
                )

                # git merge-file returns:
                # 0: clean merge
                # 1: conflicts
                # >1: error (but may still produce valid output with conflict markers)

                # Log stderr if present for diagnostics
                if result.stderr:
                    stderr_text = result.stderr.decode('utf-8', errors='replace')
                    self.logger.warning(f"git merge-file stderr for {file_path}: {stderr_text}")

                # Check if we got valid output, even with returncode > 1
                # Git merge-file sometimes returns exit code 2 for severe conflicts
                # but still produces valid merge output with conflict markers
                if result.returncode > 1:
                    if not result.stdout or len(result.stdout) == 0:
                        # True error - no output produced
                        error_msg = result.stderr.decode('utf-8', errors='replace') if result.stderr else "No output produced"
                        self.logger.error(f"Merge failed for {file_path}: returncode={result.returncode}, error={error_msg}")
                        self.print_error(f"Merge failed for {file_path}: {error_msg}")

                        # Add detailed error to conflicts report
                        conflict = ConflictInfo(
                            file_path=file_path,
                            reason=f"git merge-file error (exit code {result.returncode})",
                            hunk_details=error_msg,
                            backup_file=str(backup_file) if backup_file else None,
                            upstream_file=str(upstream_file),
                            patch_content=f"Return code: {result.returncode}\nStderr: {error_msg}"
                        )
                        self.conflicts.append(conflict)
                        self.failed_files.append(file_path)
                        return False
                    else:
                        # Git returned error code but produced output - treat as severe conflict
                        self.logger.warning(f"git merge-file returned code {result.returncode} for {file_path}, but produced {len(result.stdout)} bytes of output - treating as severe conflict")
                        self.print_warning(f"  ⚠ SEVERE CONFLICT (exit {result.returncode}): {file_path}")

                # Write output (even for severe conflicts with exit code > 1)
                src_file.parent.mkdir(parents=True, exist_ok=True)
                src_file.write_bytes(result.stdout)

                # Check for conflicts (exit code 1 or higher)
                if result.returncode >= 1:
                    self.logger.warning(f"Conflicts in {file_path} (exit code: {result.returncode})")
                    self.stats.conflicts += 1

                    # Determine severity and message
                    if result.returncode == 1:
                        reason = "3-way merge conflict"
                        severity_note = ""
                    else:
                        reason = f"Severe 3-way merge conflict (exit code {result.returncode})"
                        severity_note = f"\nNote: git merge-file returned exit code {result.returncode}, indicating severe conflicts"

                    conflict = ConflictInfo(
                        file_path=file_path,
                        reason=reason,
                        hunk_details=f"File contains conflict markers: <<<<<<< ||||||| ======= >>>>>>>{severity_note}",
                        backup_file=str(backup_file) if backup_file else None,
                        upstream_file=str(upstream_file),
                        patch_content=None
                    )
                    self.conflicts.append(conflict)

                    # Only print warning for normal conflicts (exit 1)
                    # Severe conflicts (exit 2+) already printed above
                    if result.returncode == 1:
                        self.print_warning(f"  ⚠ CONFLICT: {file_path}")
                else:
                    self.logger.info(f"Clean 3-way merge: {file_path}")
                    self.print_success(f"  ✓ 3-way merge: {file_path}")

            return True

        except Exception as e:
            self.logger.exception(f"Exception during merge of {file_path}")
            self.print_error(f"Error merging {file_path}: {e}")
            self.failed_files.append(file_path)
            return False

    def preserve_custom_files(self):
        """Ensure custom files are preserved (not deleted)."""
        if not self.custom_files:
            self.print_info("No custom files to preserve")
            return

        self.print_info(f"Verifying {len(self.custom_files)} custom files...")

        missing_custom_files = []
        for file_path in self.custom_files:
            src_file = self.src_dir / file_path
            backup_file = self.backup_dir / file_path if self.backup_dir else None

            # Check if file exists in src
            if not src_file.exists():
                # If it doesn't exist, try to restore from backup
                if backup_file and backup_file.exists():
                    src_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, src_file)
                    self.logger.info(f"Restored custom file from backup: {file_path}")
                else:
                    missing_custom_files.append(file_path)
                    self.logger.warning(f"Custom file missing and no backup: {file_path}")

        if missing_custom_files:
            self.print_warning(f"{len(missing_custom_files)} custom files are missing")
        else:
            self.print_success("All custom files preserved")

    def generate_resolution_guide(self):
        """Generate detailed manual resolution guide."""
        print()
        print(f"{Colors.RED}{'═' * 70}{Colors.NC}")
        print(f"{Colors.RED}{Colors.BOLD}PATCH APPLICATION FAILED{Colors.NC}")
        print(f"{Colors.RED}{'═' * 70}{Colors.NC}")
        print()

        print(f"{Colors.YELLOW}{len(self.failed_files)} file(s) require manual resolution:{Colors.NC}")
        print()

        for i, conflict in enumerate(self.conflicts, 1):
            print(f"{Colors.CYAN}{'─' * 70}{Colors.NC}")
            print(f"{Colors.BOLD}[{i}/{len(self.conflicts)}] {conflict.file_path}{Colors.NC}")
            print(f"{Colors.CYAN}{'─' * 70}{Colors.NC}")
            print()

            print(f"{Colors.YELLOW}Reason:{Colors.NC} {conflict.reason}")
            print()

            print(f"{Colors.CYAN}Files to compare:{Colors.NC}")
            if conflict.backup_file:
                print(f"  {Colors.GREEN}Original (your old version):{Colors.NC}")
                print(f"    {conflict.backup_file}")
            if conflict.upstream_file:
                print(f"  {Colors.BLUE}Upstream (new version):{Colors.NC}")
                print(f"    {conflict.upstream_file}")
            print()

            if conflict.patch_content:
                print(f"{Colors.YELLOW}Patch content (what needs to be applied):{Colors.NC}")
                print("  " + "\n  ".join(conflict.patch_content.split('\n')[:30]))
                if len(conflict.patch_content.split('\n')) > 30:
                    print("  ... (truncated)")
            print()

            print(f"{Colors.CYAN}Manual resolution steps:{Colors.NC}")
            print(f"  1. Compare files:")
            if conflict.backup_file and conflict.upstream_file:
                print(f"     {Colors.BOLD}diff {conflict.backup_file} {conflict.upstream_file}{Colors.NC}")
            print(f"  2. Edit the upstream file with your changes:")
            print(f"     {Colors.BOLD}vim {conflict.upstream_file}{Colors.NC}")
            print(f"  3. Copy your customizations from backup:")
            if conflict.backup_file:
                print(f"     {Colors.BOLD}cat {conflict.backup_file}{Colors.NC}")
            print(f"  4. Apply changes manually to:")
            print(f"     {Colors.BOLD}{conflict.upstream_file}{Colors.NC}")
            print(f"  5. Copy to src/:")
            print(f"     {Colors.BOLD}cp {conflict.upstream_file} src/{conflict.file_path}{Colors.NC}")
            print()

        # Summary commands
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print(f"{Colors.BOLD}QUICK REFERENCE:{Colors.NC}")
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print()
        print(f"{Colors.YELLOW}View all differences:{Colors.NC}")
        for conflict in self.conflicts:
            if conflict.backup_file and conflict.upstream_file:
                print(f"  diff {conflict.backup_file} {conflict.upstream_file}")
        print()

        print(f"{Colors.YELLOW}Merge tool (recommended):{Colors.NC}")
        for conflict in self.conflicts:
            if conflict.backup_file and conflict.upstream_file:
                print(f"  vimdiff {conflict.backup_file} {conflict.upstream_file}")
        print()

        print(f"{Colors.YELLOW}After manual resolution:{Colors.NC}")
        print(f"  1. Copy resolved files to src/:")
        print(f"     {Colors.BOLD}cp upstream/path/to/file.cc src/path/to/file.cc{Colors.NC}")
        print(f"  2. Re-run migration or continue with build")
        print()

    def generate_report(self, report_file: Optional[Path] = None):
        """Generate JSON report."""
        if self.failed_files:
            self.stats.failed = len(self.failed_files)
        else:
            self.stats.successful = self.stats.total_files

        report = {
            "summary": asdict(self.stats),
            "conflicts": [asdict(c) for c in self.conflicts],
            "failed_files": self.failed_files,
            "metadata": {
                "patch_file": str(self.patch_file),
                "backup_dir": str(self.backup_dir) if self.backup_dir else None,
                "timestamp": datetime.now().isoformat(),
                "dry_run": self.dry_run
            }
        }

        if report_file:
            with open(report_file, 'w') as f:
                json.dump(report, f, indent=2)
            self.print_success(f"Report saved: {report_file}")

        # Print summary
        print()
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print(f"{Colors.CYAN}Summary:{Colors.NC}")
        print(f"{Colors.CYAN}{'═' * 70}{Colors.NC}")
        print(f"Total files:    {self.stats.total_files}")
        if self.stats.successful > 0:
            print(f"{Colors.GREEN}Successful:     {self.stats.successful}{Colors.NC}")
        if self.stats.failed > 0:
            print(f"{Colors.RED}Failed:         {self.stats.failed}{Colors.NC}")
        if self.stats.conflicts > 0:
            print(f"{Colors.YELLOW}Conflicts:      {self.stats.conflicts}{Colors.NC}")
        print()

    def run(self, report_file: Optional[Path] = None) -> int:
        """Main entry point for new 3-way merge workflow."""
        try:
            print()
            print(f"{Colors.CYAN}{'='*70}{Colors.NC}")
            print(f"{Colors.CYAN}{Colors.BOLD}{'Mixar Patch Applicator (3-way merge)'.center(70)}{Colors.NC}")
            print(f"{Colors.CYAN}{'='*70}{Colors.NC}")
            print()

            # Step 1: Backup src/
            self.backup_src()

            # Step 2: Load custom files list
            self.load_custom_files()

            # Step 3: Get old upstream commit for 3-way merge
            self.get_old_upstream_commit()

            # Step 4: Parse patch to find files to merge
            files_to_patch = self.parse_patch_files()

            if not files_to_patch:
                self.print_error("No files found in patch")
                return 1

            # Step 5: Apply 3-way merge for each file
            self.print_info(f"Applying 3-way merge to {len(files_to_patch)} files...")
            print()

            successful_merges = 0
            for file_path in files_to_patch:
                if self.apply_3way_merge(file_path):
                    successful_merges += 1

            # Step 6: Preserve custom files
            self.preserve_custom_files()

            # Calculate stats
            self.stats.successful = successful_merges - self.stats.conflicts
            self.stats.failed = len(self.failed_files)

            # Generate report
            self.generate_report(report_file)

            # Determine exit code
            if self.failed_files:
                self.print_error(f"\nPatch application failed for {len(self.failed_files)} files")
                self.generate_resolution_guide()
                return 1
            elif self.conflicts:
                self.print_warning(f"\nPatch applied with {len(self.conflicts)} conflicts")
                self.print_info("Review files with conflict markers and resolve manually")
                self.generate_resolution_guide()
                return 0  # Not a failure - conflicts are expected and can be resolved
            else:
                self.print_success("\nPatch applied successfully!")
                return 0

        except Exception as e:
            self.print_error(f"Fatal error: {e}")
            self.logger.exception("Full traceback:")
            return 1


def main():
    if sys.platform == 'win32' and not os.environ.get('ANSICON'):
        Colors.disable()

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('patch_file', type=Path, help='Patch file to apply')
    parser.add_argument('--custom-files', type=Path, help='JSON file with custom files list')
    parser.add_argument('--dry-run', action='store_true', help='Check without applying')
    parser.add_argument('--report', type=Path, help='Output JSON report file')

    args = parser.parse_args()

    if not args.patch_file.exists():
        print(f"{Colors.RED}Error: Patch file not found: {args.patch_file}{Colors.NC}")
        return 1

    if args.custom_files and not args.custom_files.exists():
        print(f"{Colors.RED}Error: Custom files JSON not found: {args.custom_files}{Colors.NC}")
        return 1

    script_dir = Path(__file__).parent.parent.parent
    applier = PatchApplier(args.patch_file, script_dir, args.custom_files, args.dry_run)

    return applier.run(args.report)


if __name__ == '__main__':
    sys.exit(main())
