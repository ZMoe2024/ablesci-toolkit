"""Read route load and optionally sample a small ordinary download on each route."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import requests

from checkin import BASE, Client, CheckinError, load_secret, parse_profile
from assist_download import token_url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file-id', required=True, help='本人有下载权限的应助文件ID')
    parser.add_argument('--probe', action='store_true', help='Sample at most 64 KiB on each free route')
    parser.add_argument('--server', help='Sample only this ordinary server ID')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--reference', type=Path, help='Compare downloaded range with this local PDF')
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('route-diagnostics.json'))
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9]+', args.file_id) or args.offset < 0:
        parser.error('invalid file ID')
    c = Client(load_secret())
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'probes': []}
    try:
        started = time.monotonic()
        load = c.request('/file/progress-download-server-load').json()
        report['load_api_seconds'] = round(time.monotonic() - started, 3)
        report['load'] = load
        if args.probe:
            page_path = '/assist/download?id=' + args.file_id
            html = c.request(page_path).text
            parse_profile(html, c.secret['account'])
            config = json.loads(re.search(r'const config\s*=\s*(\{[^\n]+\});', html).group(1))
            csrf = BeautifulSoup(html, 'html.parser').select_one('meta[name="csrf-token"]')['content']
            for node in config['normalServers']:
                if args.server and str(node['id']) != args.server:
                    continue
                sample = {'server_id': str(node['id']), 'name': node['name']}
                report['probes'].append(sample)
                started = time.monotonic()
                reply = c.request('/file/request-download-token', method='POST', headers={
                    'X-CSRF-Token': csrf, 'X-Requested-With': 'XMLHttpRequest',
                    'Referer': BASE + page_path}, data={
                    'type': 'assistFile', 'id': args.file_id, 'channel': 'normal',
                    'highspeed': '0', 'fallback': '0', 'file_server': node['id'],
                    'remove_sensitive': '1'}).json()
                sample['token_seconds'] = round(time.monotonic() - started, 3)
                if reply.get('code') != 0:
                    sample['error'] = 'token_rejected'
                    continue
                target = token_url(reply['data'], config['allowedNodeHosts'])
                sample['host'] = urlsplit(target).hostname
                sample['received_bytes'] = 0
                sample['requested_range'] = f'bytes={args.offset}-{args.offset + 65535}'
                body = bytearray()
                started = time.monotonic()
                try:
                    # Range is only a support check, never a speed-limit bypass.
                    with requests.get(target, stream=True, allow_redirects=False, timeout=(10, 20), headers={
                        'Range': sample['requested_range'], 'Accept-Encoding': 'identity',
                        'Referer': BASE + '/', 'User-Agent': c.session.headers['User-Agent']}) as r:
                        sample['headers_seconds'] = round(time.monotonic() - started, 3)
                        sample['http_status'] = r.status_code
                        sample['headers'] = {key: r.headers[key] for key in (
                            'Server', 'Content-Type', 'Content-Length', 'Content-Range',
                            'Accept-Ranges', 'X-Cache', 'Via') if key in r.headers}
                        if r.status_code in (200, 206):
                            for chunk in r.iter_content(4096):
                                if chunk:
                                    sample.setdefault('first_chunk_seconds', round(time.monotonic() - started, 3))
                                    sample['received_bytes'] += len(chunk)
                                    body.extend(chunk)
                                if sample['received_bytes'] >= 65536 or time.monotonic() - started > 25:
                                    break
                        sample['sample_seconds'] = round(time.monotonic() - started, 3)
                        sample['range_honored'] = r.status_code == 206 and 'Content-Range' in r.headers
                        if args.reference and sample['range_honored'] and len(body) == 65536:
                            with args.reference.open('rb') as reference:
                                reference.seek(args.offset)
                                sample['matches_local_range'] = reference.read(len(body)) == body
                            sample['sample_sha256'] = hashlib.sha256(body).hexdigest()
                except requests.RequestException as e:
                    # requests error strings may contain the secret token URL.
                    sample['error_type'] = type(e).__name__
                    sample['sample_seconds'] = round(time.monotonic() - started, 3)
                print(json.dumps(sample, ensure_ascii=False), flush=True)
        report['final_load'] = c.request('/file/progress-download-server-load').json()
        path = args.output
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        c.persist()
        c.session.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except Exception as e:
        print(json.dumps({'error_type': type(e).__name__}))
        raise SystemExit(2)
