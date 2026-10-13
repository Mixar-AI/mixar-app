# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
from types import SimpleNamespace

from mixar.modules.common.utils.process_identity import instance_id


def test_loading_a_document_cannot_replace_process_identity():
    original = SimpleNamespace(mixie_instance_id="")
    identity = instance_id(original)
    loaded = SimpleNamespace(mixie_instance_id="saved-in-another-process")
    assert identity and instance_id(loaded) == identity
    assert loaded.mixie_instance_id == original.mixie_instance_id


def test_unregistered_window_manager_does_not_mint_an_rna_property():
    pending = SimpleNamespace()
    assert instance_id(None) == instance_id(pending) == ""
    assert not hasattr(pending, "mixie_instance_id")
