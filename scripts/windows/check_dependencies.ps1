# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
<#
Read-only build preflight. Source archives have no commit pins to compare, so
they receive payload validation only. Never initialize, checkout, or fetch here.
#>
param(
    [Parameter(Mandatory = $true)][string]$RootDir,
    [Parameter(Mandatory = $true)][string]$UpstreamDir,
    [Parameter(Mandatory = $true)][string]$PythonVersion
)

$ErrorActionPreference = 'Stop'

function Read-Git([string]$Directory, [string[]]$GitArgs) {
    try {
        $value = & git -C $Directory @GitArgs 2>$null
        if ($LASTEXITCODE -eq 0) { return ($value -join "`n").Trim() }
    } catch { }
    return $null
}

function Is-GitRoot([string]$Directory) {
    $top = Read-Git $Directory @('rev-parse', '--show-toplevel')
    if (-not $top) { return $false }
    return [string]::Equals(
        [IO.Path]::GetFullPath($top).TrimEnd('\', '/'),
        [IO.Path]::GetFullPath($Directory).TrimEnd('\', '/'),
        [StringComparison]::OrdinalIgnoreCase)
}

function Read-Prefix([string]$Path, [int]$Count) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Missing dependency: $Path`n$script:PayloadHelp"
    }
    $stream = [IO.File]::OpenRead($Path)
    try {
        $bytes = New-Object byte[] $Count
        $read = $stream.Read($bytes, 0, $Count)
        if ($read -eq 0) { throw "Empty dependency: $Path`n$script:PayloadHelp" }
        $prefix = [Text.Encoding]::ASCII.GetString($bytes, 0, $read)
        if ($prefix.StartsWith('version https://git-lfs.github.com/spec/')) {
            throw "Git LFS pointer instead of dependency: $Path`n$script:PayloadHelp"
        }
        return ,$bytes[0..($read - 1)]
    } finally { $stream.Dispose() }
}

try {
    if ($PythonVersion -notmatch '^3\.[0-9]+$') {
        throw "Invalid Python version '$PythonVersion'; expected major.minor, for example 3.13."
    }
    $RootDir = [IO.Path]::GetFullPath($RootDir)
    $UpstreamDir = [IO.Path]::GetFullPath($UpstreamDir)
    $lib = Join-Path $UpstreamDir 'lib/windows_x64'
    $rootHasGit = Test-Path -LiteralPath (Join-Path $RootDir '.git')
    if ($rootHasGit -and -not (Is-GitRoot $RootDir)) {
        throw "Cannot inspect Git metadata at $RootDir. Install Git and verify this checkout."
    }
    if (Is-GitRoot $RootDir) {
        $expected = Read-Git $RootDir @('rev-parse', '--verify', 'HEAD:upstream')
        if (-not $expected) { throw 'The project HEAD does not contain an upstream pin.' }
        if (-not (Is-GitRoot $UpstreamDir)) {
            throw "Upstream is not initialized at $UpstreamDir.`nRun: git -C `"$RootDir`" submodule update --init --checkout upstream`nThen select that initialized upstream directory."
        }
        $actual = Read-Git $UpstreamDir @('rev-parse', '--verify', 'HEAD')
        if ($actual -ne $expected) {
            throw "Upstream revision mismatch: expected $expected, found $actual.`nAfter preserving local changes, run: git -C `"$UpstreamDir`" checkout --detach $expected"
        }
        $expectedLib = Read-Git $UpstreamDir @('rev-parse', '--verify', 'HEAD:lib/windows_x64')
        if (-not $expectedLib) { throw 'The upstream HEAD has no Windows x64 library pin.' }
        if (-not (Is-GitRoot $lib)) {
            throw "Windows libraries are not initialized at $lib.`nRun: git -C `"$UpstreamDir`" submodule update --init --checkout lib/windows_x64"
        }
        $actualLib = Read-Git $lib @('rev-parse', '--verify', 'HEAD')
        if ($actualLib -ne $expectedLib) {
            throw "Windows library revision mismatch: expected $expectedLib, found $actualLib.`nAfter preserving local changes, run: git -C `"$lib`" checkout --detach $expectedLib"
        }
        Write-Host 'Upstream and Windows library revisions match the project pins.'
    } else {
        Write-Warning 'Source archive: Git pins cannot be verified; validating bundled Python files only.'
    }
    $script:PayloadHelp = "Restore the Windows dependency payloads: git -C `"$lib`" lfs pull`nFor source archives, obtain the complete Windows libraries for this Blender revision."
    $digits = $PythonVersion.Replace('.', '')
    $python = Join-Path $lib "python/$digits"
    $exe = Join-Path $python 'bin/python.exe'
    $header = Read-Prefix $exe 128
    if ($header.Length -lt 64 -or $header[0] -ne 0x4d -or $header[1] -ne 0x5a) {
        throw "Invalid Windows Python executable: $exe`n$script:PayloadHelp"
    }
    $stream = [IO.File]::OpenRead($exe)
    try {
        $offset = [BitConverter]::ToUInt32([byte[]]$header, 60)
        if ($offset -lt 64 -or $offset -gt $stream.Length - 6) {
            throw "Invalid PE header in $exe`n$script:PayloadHelp"
        }
        $null = $stream.Seek($offset, [IO.SeekOrigin]::Begin)
        $pe = New-Object byte[] 6
        $null = $stream.Read($pe, 0, 6)
        if ([BitConverter]::ToUInt32($pe, 0) -ne 0x4550 -or
            [BitConverter]::ToUInt16($pe, 4) -ne 0x8664) {
            throw "Python must be a Windows x64 PE executable: $exe`n$script:PayloadHelp"
        }
    } finally { $stream.Dispose() }
    $null = Read-Prefix (Join-Path $python 'include/Python.h') 128
    $archivePath = Join-Path $python "libs/python$digits.lib"
    $archive = Read-Prefix $archivePath 128
    if ($archive.Length -lt 8 -or [Text.Encoding]::ASCII.GetString([byte[]]$archive, 0, 8) -ne "!<arch>`n") {
        throw "Invalid Python import library: $archivePath`n$script:PayloadHelp"
    }
    Write-Host "Windows dependencies ready: Python $PythonVersion ($python)."
    exit 0
} catch {
    [Console]::Error.WriteLine("Build dependency check failed: $($_.Exception.Message)")
    exit 1
}
