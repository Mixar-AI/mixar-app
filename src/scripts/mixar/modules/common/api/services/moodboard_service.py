# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Moodboard publication uses the shared authenticated request queue."""
from ..constants import APIModule
from .base_service import BaseService


class MoodboardService(BaseService):
    @property
    def module(self):
        return APIModule.MOODBOARDS


_service = None


def get_moodboard_service():
    global _service
    if _service is None:
        _service = MoodboardService()
    return _service
