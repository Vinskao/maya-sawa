from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from maya_sawa.api.mcp_core import McpServer, Tool


class Echo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str


def echo(arguments: Echo):
    return {'echo': arguments.text}


def broken(arguments: Echo):
    raise RuntimeError('secret internal detail')


def build(max_body=200):
    server = McpServer('Test server', '9.9.9', [
        Tool('echo', 'Echo text back.', Echo, echo, usage='Send text.', unavailable='Echo is down.'),
        Tool('broken', 'Always fails.', Echo, broken, usage='Send text.', unavailable='Broken is down.'),
    ], max_body=max_body)
    router = APIRouter()

    @router.post('/mcp')
    async def mcp(request: Request):
        return await server.handle(request)

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def rpc(client, method, params=None, **extra):
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}, **extra})


def call(client, name, arguments):
    return rpc(client, 'tools/call', {'name': name, 'arguments': arguments}).json()['result']


def test_initialize_negotiates_a_supported_protocol_and_names_the_server():
    client = build()
    result = rpc(client, 'initialize', {'protocolVersion': '2025-06-18'}).json()['result']
    assert result['protocolVersion'] == '2025-06-18'
    assert result['serverInfo'] == {'name': 'Test server', 'version': '9.9.9'}
    assert result['capabilities'] == {'tools': {}}
    fallback = rpc(client, 'initialize', {'protocolVersion': '1999-01-01'}).json()['result']
    assert fallback['protocolVersion'] == '2025-11-25'


def test_ping_and_unknown_method():
    client = build()
    assert rpc(client, 'ping').json()['result'] == {}
    assert rpc(client, 'resources/list').json()['error']['code'] == -32601


def test_tools_list_describes_each_registered_tool_as_read_only():
    tools = rpc(build(), 'tools/list').json()['result']['tools']
    assert [tool['name'] for tool in tools] == ['echo', 'broken']
    assert tools[0]['inputSchema'] == Echo.model_json_schema()
    assert tools[0]['annotations'] == {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False}


def test_tool_call_returns_text_and_structured_content():
    result = call(build(), 'echo', {'text': 'hi'})
    assert result['structuredContent'] == {'echo': 'hi'}
    assert result['content'] == [{'type': 'text', 'text': '{"echo": "hi"}'}]


def test_bad_arguments_and_unknown_tools_are_tool_errors_not_http_errors():
    client = build()
    bad = call(client, 'echo', {'text': 'hi', 'extra': 1})
    assert bad == {'isError': True, 'content': [{'type': 'text', 'text': 'Send text.'}]}
    assert call(client, 'echo', {})['isError']
    assert call(client, 'nope', {})['content'][0]['text'] == 'Unknown tool'


def test_handler_exceptions_do_not_leak_internal_detail():
    result = call(build(), 'broken', {'text': 'x'})
    assert result == {'isError': True, 'content': [{'type': 'text', 'text': 'Broken is down.'}]}


def test_transport_rules():
    client = build()
    assert client.post('/mcp', content=b'x' * 201).status_code == 413
    assert client.post('/mcp', content=b'not json').status_code == 400
    assert client.post('/mcp', json=[1]).status_code == 400
    assert client.post('/mcp', json={'jsonrpc': '1.0', 'id': 1, 'method': 'ping'}).status_code == 400
    assert client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 5}).status_code == 400
    assert client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'ping', 'params': 3}).status_code == 400
    assert client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202
    assert client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'ping'}).status_code == 400
