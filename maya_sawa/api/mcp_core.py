"""Shared stateless Streamable-HTTP MCP transport: JSON-RPC parsing and a read-only tool registry.

Auth stays with each router (a FastAPI dependency); this module only speaks the protocol.
To add a tool, build a `Tool` and pass it to `McpServer`.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from inspect import iscoroutinefunction
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
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
    handler: Callable[[Any], dict | Awaitable[dict]]
    usage: str  # shown when the arguments are invalid
    unavailable: str  # shown when the handler raises; never expose the exception itself
    narrow: str = 'Use the public API for the complete result.'
    max_output_bytes: int = 24000


def _error(text: str) -> dict:
    return {'isError': True, 'content': [{'type': 'text', 'text': text}]}


def _output(tool: Tool, data: dict) -> dict:
    data = jsonable_encoder(data)
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False)
    result = {'content': [{'type': 'text', 'text': serialized}], 'structuredContent': data}
    # Count both copies, including the JSON escaping on the text copy.
    if len(JSONResponse(result).body) <= tool.max_output_bytes:
        return result
    summary = {'status': data.get('status', 'found'), 'truncated': True, 'message': tool.narrow}
    for preview_length in (1500, 0):
        if preview_length:
            summary['preview'] = serialized[:preview_length]
        else:
            summary.pop('preview', None)
        result = {
            'content': [{'type': 'text', 'text': json.dumps(summary, ensure_ascii=False)}],
            'structuredContent': summary,
        }
        if len(JSONResponse(result).body) <= tool.max_output_bytes:
            return result
    raise ValueError('MCP output limit too small for truncation notice')


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
            if iscoroutinefunction(tool.handler):
                output = await tool.handler(arguments)
            else:
                output = await asyncio.to_thread(tool.handler, arguments)
            return _output(tool, output)
        except Exception:
            logger.exception('MCP tool %s failed', tool.name)
            return _error(tool.unavailable)

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
