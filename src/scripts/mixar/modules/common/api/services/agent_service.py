# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Agent settings facade over WebSocket, preserving the UI response envelope."""

from ...agent_rpc.client import request, AgentRPCError
from ..response import APIResponse


class AgentService:
    @staticmethod
    def _request(method, payload=None, mutation=False):
        try:
            result = request(method, payload, mutation=mutation)
            return APIResponse.from_success(200, data=result)
        except AgentRPCError as exc:
            return APIResponse.from_error(exc.status_code, exc.message,
                                          data={'message': exc.message, 'data': exc.data})

    def list_models(self):
        return self._request('models.list')

    def get_credentials(self):
        return self._request('credentials.list')

    def save_credentials_all(self, provider, model, api_key, base_url=None, supports_vision=None):
        payload = {'provider': provider, 'model': model}
        if api_key is not None:
            payload['api_key'] = api_key
        if base_url is not None:
            payload['base_url'] = base_url
        if supports_vision is not None:
            payload['supports_vision'] = bool(supports_vision)
        return self._request('byok.set', payload, mutation=True)

    def delete_credentials_all(self):
        return self._request('credentials.clear', mutation=True)


_agent_service = None


def get_agent_service():
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
