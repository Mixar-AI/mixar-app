# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
# Only the Mixar-owned Python package is pruned; Blender's overlay is additive.
$ErrorActionPreference = 'Stop'
$cadRepository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$cadSource = [IO.Path]::GetFullPath((Join-Path $cadRepository 'src/scripts/mixar'))
$cadOverlay = [IO.Path]::GetFullPath((Join-Path $cadRepository 'source/scripts/mixar'))
if (-not $cadOverlay.StartsWith($cadRepository + '\', [StringComparison]::OrdinalIgnoreCase) -or
    -not (Test-Path -LiteralPath (Join-Path $cadSource '__init__.py'))) {
    throw 'Invalid Mixar overlay roots.'
}
if (-not (Test-Path -LiteralPath $cadOverlay)) { exit 0 }
# Refuse links before enumerating or removing anything in the build tree.
foreach ($cadRoot in @($cadSource, $cadOverlay)) {
    $cadAncestor = Get-Item -LiteralPath $cadRoot
    while ($cadAncestor) {
        if ($cadAncestor.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked overlay roots are unsupported.' }
        $cadAncestor = $cadAncestor.Parent
    }
}
$cadItems = @(Get-ChildItem -LiteralPath $cadOverlay -Recurse -Force)
if ($cadItems | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) {
    throw 'Linked overlay entries are unsupported.'
}
foreach ($cadFile in $cadItems | Where-Object { -not $_.PSIsContainer }) {
    $cadTarget = [IO.Path]::GetFullPath($cadFile.FullName)
    if (-not $cadTarget.StartsWith($cadOverlay + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Overlay target escaped its root.' }
    $cadRelative = $cadTarget.Substring($cadOverlay.Length + 1)
    if (-not (Test-Path -LiteralPath (Join-Path $cadSource $cadRelative))) {
        Remove-Item -LiteralPath $cadTarget -Force
    }
}
