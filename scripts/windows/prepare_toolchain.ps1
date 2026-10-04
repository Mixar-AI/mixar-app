# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
<# Back up stale CMake configuration after an MSVC compiler path changes. #>
param(
    [Parameter(Mandatory = $true)][string]$RootDir,
    [Parameter(Mandatory = $true)][string]$BuildDir,
    [Parameter(Mandatory = $true)][string]$Compiler
)

$ErrorActionPreference = 'Stop'

function Full-Path([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Require-Child([string]$Path, [string]$Parent) {
    $full = Full-Path $Path
    $prefix = (Full-Path $Parent) + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside $Parent : $full"
    }
    return $full
}

function Require-NoReparse([string]$Path) {
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing junction or symbolic link in build path: $current"
            }
        }
        if ([string]::Equals($current, $script:RootDir, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
    throw "Build path does not resolve within project root: $Path"
}

function Compiler-Matches([string]$Recorded) {
    if (-not [IO.Path]::IsPathRooted($Recorded)) { return $false }
    return [string]::Equals((Full-Path $Recorded), $script:Compiler,
        [StringComparison]::OrdinalIgnoreCase)
}

try {
    $RootDir = Full-Path $RootDir
    if (-not (Test-Path -LiteralPath $RootDir -PathType Container)) {
        throw "Project root does not exist: $RootDir"
    }
    $BuildDir = Require-Child $BuildDir (Join-Path $RootDir 'build')
    Require-NoReparse $BuildDir
    $Compiler = Full-Path $Compiler
    if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
        throw "Selected compiler does not exist: $Compiler"
    }
    if (-not (Test-Path -LiteralPath $BuildDir -PathType Container)) { exit 0 }

    $cache = Join-Path $BuildDir 'CMakeCache.txt'
    $cmakeFiles = Join-Path $BuildDir 'CMakeFiles'
    Require-NoReparse $cache
    Require-NoReparse $cmakeFiles
    $versions = @()
    if (Test-Path -LiteralPath $cmakeFiles -PathType Container) {
        $versions = @(Get-ChildItem -LiteralPath $cmakeFiles -Directory | Where-Object {
            $_.Name -match '^\d+\.\d+(?:\.\d+)?(?:[-.][A-Za-z0-9]+)*$'
        })
    }
    $changed = $false
    if (Test-Path -LiteralPath $cache -PathType Leaf) {
        foreach ($line in Get-Content -LiteralPath $cache) {
            if ($line -match '^CMAKE_(?:C|CXX)_COMPILER:[A-Z]+=(.+)$') {
                if (-not (Compiler-Matches $Matches[1])) { $changed = $true }
            }
        }
    }
    foreach ($version in $versions) {
        Require-NoReparse $version.FullName
        foreach ($language in @('C', 'CXX')) {
            $info = Join-Path $version.FullName "CMake${language}Compiler.cmake"
            Require-NoReparse $info
            if (Test-Path -LiteralPath $info -PathType Leaf) {
                foreach ($line in Get-Content -LiteralPath $info) {
                    if ($line -match '^\s*set\(CMAKE_(?:C|CXX)_COMPILER\s+"([^"]+)"\s*\)') {
                        if (-not (Compiler-Matches $Matches[1])) { $changed = $true }
                    }
                }
            }
        }
    }
    if (-not $changed) { exit 0 }

    $backupRoot = Require-Child (Join-Path $BuildDir '.mixar-toolchain-backups') $BuildDir
    Require-NoReparse $backupRoot
    $null = [IO.Directory]::CreateDirectory($backupRoot)
    $backup = $null
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $id = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N')
        $candidate = Require-Child (Join-Path $backupRoot $id) $backupRoot
        if (Test-Path -LiteralPath $candidate) { continue }
        try {
            $null = New-Item -ItemType Directory -Path $candidate -ErrorAction Stop
            $backup = $candidate
            break
        } catch {
            if (-not (Test-Path -LiteralPath $candidate)) { throw }
        }
    }
    if (-not $backup) { throw 'Could not reserve a unique toolchain backup directory.' }
    if (Test-Path -LiteralPath $cache -PathType Leaf) {
        Move-Item -LiteralPath $cache -Destination (Join-Path $backup 'CMakeCache.txt')
    }
    if ($versions.Count -gt 0) {
        $savedVersions = Join-Path $backup 'CMakeFiles'
        $null = [IO.Directory]::CreateDirectory($savedVersions)
        foreach ($version in $versions) {
            Move-Item -LiteralPath $version.FullName -Destination $savedVersions
        }
    }
    Write-Host "Compiler changed; CMake configuration backed up to $backup"
    Write-Host 'Manual CMake-only options will reset; the build reapplies its -C/-D settings.'
    Write-Host 'Target object directories were preserved; changed compiler commands will rebuild as needed.'
    exit 0
} catch {
    [Console]::Error.WriteLine("Toolchain preparation failed: $($_.Exception.Message)")
    exit 1
}
