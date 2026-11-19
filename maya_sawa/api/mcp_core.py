"""Shared stateless Streamable-HTTP MCP transport: JSON-RPC parsing and a read-only tool registry.

Auth stays with each router (a FastAPI dependency); this module only speaks the protocol.
To add a tool, build a `Tool` and pass it to `McpServer`.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

PROTOCOLS = {'2025-03-26', '2025-06-18', '2025-11-25'}
DEFAULT_PROTOCOL = '2025-11-25'
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    model: type[BaseModel]
    handler: Callable[[Any], dict]  # sync; run in a thread so database reads do not block the loop
    usage: str  # shown when the arguments are invalid
    unavailable: str  # shown when the handler raises; never expose the exception itself


def _error(text: str) -> dict:
    return {'isError': True, 'content': [{'type': 'text', 'text': text}]}


class McpServer:
    def __init__(self, name: str, version: str, tools: list[Tool], max_body: int = 24000):
        self.name = name
        self.version = version
        self.tools = {tool.name: tool for tool in tools}
        self.max_body = max_body

    async def call_tool(self, params: dict) -> dict:
        tool = self.tools.get(params.get('name'))
        if tool is None:
            return _error('Unknown tool')
        try:
            arguments = tool.model.model_validate(params.get('arguments', {}))
        except ValidationError:
            return _error(tool.usage)
        try:
            output = await asyncio.to_thread(tool.handler, arguments)
        except Exception:
            logger.exception('MCP tool %s failed', tool.name)
            return _error(tool.unavailable)
        return {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}], 'structuredContent': output}

    def list_tools(self) -> list[dict]:
        return [{
            'name': tool.name, 'description': tool.description,
            'inputSchema': tool.model.model_json_schema(),
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False},
        } for tool in self.tools.values()]

    async def handle(self, request: Request) -> Response:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > self.max_body:
                raise HTTPException(413, 'Request too large')
            body.extend(chunk)
        try:
            message = json.loads(body)
        except ValueError as exc:
            raise HTTPException(400, 'Invalid JSON-RPC request') from exc
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
            raise HTTPException(400, 'Invalid JSON-RPC request')
        method, params = message.get('method'), message.get('params', {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise HTTPException(400, 'Invalid JSON-RPC method or parameters')
        if 'id' not in message:
            if method.startswith('notifications/'):
                return Response(status_code=202)
            raise HTTPException(400, 'Invalid notification')

        envelope = {'jsonrpc': '2.0', 'id': message['id']}
        if method == 'initialize':
            version = params.get('protocolVersion')
            result = {
                'protocolVersion': version if isinstance(version, str) and version in PROTOCOLS else DEFAULT_PROTOCOL,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': self.name, 'version': self.version},
            }
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': self.list_tools()}
        elif method == 'tools/call':
            result = await self.call_tool(params)
        else:
            return JSONResponse({**envelope, 'error': {'code': -32601, 'message': 'Method not found'}})
        return JSONResponse({**envelope, 'result': result})
