"""Dispatch the local native harness through Fusion's enabled MCP endpoint."""
import argparse
import http.client
import json
from pathlib import Path


def execute(script, port=27182):
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json'}
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1200)

    def rpc(method, params=None, request_id=None):
        payload = {'jsonrpc': '2.0', 'method': method}
        if params is not None: payload['params'] = params
        if request_id is not None: payload['id'] = request_id
        connection.request('POST', '/mcp', json.dumps(payload), headers)
        response = connection.getresponse()
        raw = response.read()
        session = response.getheader('MCP-Session-Id')
        if session: headers['MCP-Session-Id'] = session
        if request_id is None:
            if response.status not in (200, 202): raise RuntimeError('MCP notification HTTP ' + str(response.status))
            return None
        if response.status != 200: raise RuntimeError('MCP HTTP ' + str(response.status))
        data = json.loads(raw)
        if data.get('id') != request_id or 'result' not in data: raise RuntimeError('MCP invalid result: ' + str(data))
        result = data['result']
        if result.get('isError'): raise RuntimeError(json.dumps(result))
        for block in result.get('content', []):
            if block.get('type') == 'text':
                try: value = json.loads(block['text'])
                except json.JSONDecodeError: continue
                if value.get('success') is False: raise RuntimeError(json.dumps(value))
        return result

    try:
        rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                          'clientInfo': {'name': 'scad2fusion verification', 'version': '0.1.0'}}, 1)
        rpc('notifications/initialized')
        return rpc('tools/call', {'name': 'fusion_mcp_execute', 'arguments': {
            'featureType': 'script', 'object': {'script': script, 'readOnly': False}}}, 2)
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, help='JSON: evidence path and cases/variants')
    parser.add_argument('--port', type=int, default=27182)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    config['evidence'] = str(Path(config['evidence']).resolve())
    for case in config['cases']:
        case['script'] = str(Path(case['script']).resolve())
    # Fusion's local script dispatcher can misdecode literal non-ASCII source.
    # Python escapes preserve Unicode paths without changing their runtime value.
    script = 'CONFIG = ' + ascii(config) + '\n' + Path(__file__).with_name('fusion_validate.py').read_text(encoding='utf-8')
    result = execute(script, args.port)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
