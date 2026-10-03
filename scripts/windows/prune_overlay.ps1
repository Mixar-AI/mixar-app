# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
<# Preserve the union of both overlay inputs; archive obsolete generated files. #>
param(
    [Parameter(Mandatory = $true)][string]$RootDir,
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [Parameter(Mandatory = $true)][string]$UpstreamDir,
    [Parameter(Mandatory = $true)][string]$SrcDir
)

$ErrorActionPreference = 'Stop'

function Full-Path([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Same-Path([string]$Left, [string]$Right) {
    return [string]::Equals($Left, $Right, [StringComparison]::OrdinalIgnoreCase)
}

function Under-Path([string]$Path, [string]$Parent) {
    return $Path.StartsWith($Parent + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)
}

function Require-NoReparse([string]$Path) {
    while ($Path) {
        if ([IO.Directory]::Exists($Path) -or [IO.File]::Exists($Path)) {
            if ([IO.File]::GetAttributes($Path) -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing junction or symbolic link: $Path"
            }
        }
        $Path = [IO.Path]::GetDirectoryName($Path)
    }
}

function Scan-Tree([string]$Directory, [bool]$Destination, [bool]$Overlay = $false) {
    $prefixLength = $Directory.Length + 1
    $ignoredDirectories = $script:upstreamIgnoredDirs
    $ignoredFiles = $script:upstreamIgnoredFiles
    if ($Overlay) {
        $ignoredDirectories = $script:overlayIgnoredDirs
        $ignoredFiles = $script:overlayIgnoredFiles
    }
    $pending = New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push($Directory)
    while ($pending.Count -gt 0) {
        foreach ($entry in [IO.Directory]::EnumerateFileSystemEntries($pending.Pop())) {
            $name = [IO.Path]::GetFileName($entry)
            $attributes = [IO.File]::GetAttributes($entry)
            $isDirectory = $attributes -band [IO.FileAttributes]::Directory
            # Never traverse Git internals. Actual .git files remain part of the
            # union: bundled libraries use them for CMake's Git metadata lookup.
            if ($isDirectory -and $name -eq '.git') { continue }
            if (-not $Destination) {
                if ($isDirectory -and $ignoredDirectories.Contains($name)) { continue }
                if (-not $isDirectory -and $ignoredFiles.Contains($name)) { continue }
            }
            if ($attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing junction or symbolic link in overlay tree: $entry"
            }
            if ($isDirectory) {
                $pending.Push($entry)
                continue
            }
            $relative = $entry.Substring($prefixLength).Replace('\', '/')
            if (-not $Destination) {
                $null = $script:retained.Add($relative)
            } elseif (-not $script:retained.Contains($relative)) {
                $script:orphans.Add([pscustomobject]@{ Path = $entry; Relative = $relative })
            }
        }
    }
}

try {
    $RootDir = Full-Path $RootDir
    $SourceDir = Full-Path $SourceDir
    $UpstreamDir = Full-Path $UpstreamDir
    $SrcDir = Full-Path $SrcDir
    if (-not (Same-Path $SourceDir (Join-Path $RootDir 'source'))) {
        throw "Generated source must be exactly $RootDir\source; refusing $SourceDir"
    }
    $roots = @($SourceDir, $UpstreamDir, $SrcDir)
    foreach ($directory in @($RootDir) + $roots) {
        if (-not [IO.Directory]::Exists($directory)) {
            throw "Overlay directory does not exist: $directory"
        }
        Require-NoReparse $directory
    }
    for ($left = 0; $left -lt $roots.Count; $left++) {
        for ($right = $left + 1; $right -lt $roots.Count; $right++) {
            if ((Same-Path $roots[$left] $roots[$right]) -or
                (Under-Path $roots[$left] $roots[$right]) -or
                (Under-Path $roots[$right] $roots[$left])) {
                throw 'Overlay input and generated trees must be distinct and must not overlap.'
            }
        }
    }
    if (-not [IO.File]::Exists((Join-Path $UpstreamDir 'CMakeLists.txt'))) {
        throw "Upstream CMakeLists.txt is missing: $UpstreamDir"
    }
    $backupRoot = Full-Path (Join-Path $RootDir 'build/.mixar-overlay-backups')
    Require-NoReparse $backupRoot
    # Match each robocopy pass. Upstream's Python stdlib can legitimately have
    # a venv directory; only the Mixar overlay excludes development venvs.
    foreach ($setName in @('upstreamIgnoredDirs', 'upstreamIgnoredFiles', 'overlayIgnoredDirs', 'overlayIgnoredFiles')) {
        Set-Variable -Scope Script -Name $setName -Value (
            New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase))
    }
    foreach ($name in @('.github', '.vscode', '.idea', '.gitea')) { $null = $upstreamIgnoredDirs.Add($name) }
    foreach ($name in @('.gitignore', '.gitmodules', '.gitattributes', '.gitkeep')) { $null = $upstreamIgnoredFiles.Add($name) }
    foreach ($name in @('.venv', 'venv', '__pycache__', '.pytest_cache')) { $null = $overlayIgnoredDirs.Add($name) }
    $null = $overlayIgnoredFiles.Add('.DS_Store')
    $script:retained = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($generated in @('source/creator/mixar_env_config.h', 'scripts/mixar/config/_build_env.py')) {
        $null = $script:retained.Add($generated)
    }
    $script:orphans = New-Object 'System.Collections.Generic.List[object]'
    Scan-Tree $UpstreamDir $false
    Scan-Tree $SrcDir $false $true
    Scan-Tree $SourceDir $true
    if ($orphans.Count -eq 0) {
        Write-Host 'Overlay contains no obsolete source files.'
        exit 0
    }

    # No writes occur until every input, destination and candidate has been checked.
    $null = [IO.Directory]::CreateDirectory($backupRoot)
    $backup = $null
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $id = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
        $candidate = Full-Path (Join-Path $backupRoot $id)
        if (Test-Path -LiteralPath $candidate) { continue }
        try {
            $null = New-Item -ItemType Directory -Path $candidate -ErrorAction Stop
            $backup = $candidate
            break
        } catch {
            if (-not (Test-Path -LiteralPath $candidate)) { throw }
        }
    }
    if (-not $backup) { throw 'Could not reserve a unique overlay backup directory.' }
    foreach ($orphan in $orphans) {
        $target = Full-Path (Join-Path $backup $orphan.Relative)
        if (-not (Under-Path $orphan.Path $SourceDir) -or -not (Under-Path $target $backup)) {
            throw "Refusing an overlay move outside its checked trees: $($orphan.Path)"
        }
        $orphan | Add-Member -NotePropertyName Target -NotePropertyValue $target
    }
    foreach ($orphan in $orphans) {
        $target = $orphan.Target
        $null = [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        Move-Item -LiteralPath $orphan.Path -Destination $target
    }
    Write-Host "Archived $($orphans.Count) obsolete overlay files to $backup"
    exit 0
} catch {
    [Console]::Error.WriteLine("Overlay pruning failed: $($_.Exception.Message)")
    exit 1
}
