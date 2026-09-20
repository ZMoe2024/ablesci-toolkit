"""Bounded experiment: retrieve 192 KiB in three parts, verify against a known PDF.

This is a protocol/throughput experiment, not the full production downloader.
Each normal node gets at most one simultaneous request. No paid channel is used.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import sys
import time

from bs4 import BeautifulSoup
import requests

from checkin import BASE, Client, load_secret, parse_profile
from assist_download import inspect_detail, token_url

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['parallel', 'serial'], default='parallel')
    parser.add_argument('--server', choices=['2', '3', '4'], default='4')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--assist-id', required=True)
    parser.add_argument('--file-id', required=True)
    parser.add_argument('--reference', required=True, type=Path, help='已完整下载且核验过的同一PDF')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'downloads')
    args = parser.parse_args()
    if not all(re.fullmatch('[A-Za-z0-9]+', value) for value in (args.assist_id, args.file_id)):
        parser.error('invalid request/file ID')
    reference = args.reference.read_bytes()
    if not reference.startswith(b'%PDF-') or len(reference) < 3 * 65536:
        parser.error('reference must be a PDF of at least 192 KiB')
    total = len(reference)
    chunk_size = 64 * 1024
    folder = args.output_dir / args.file_id / ('probe-' + args.mode)
    folder.mkdir(parents=True, exist_ok=True)
    routes = ['2', '3', '4'] if args.mode == 'parallel' and not args.resume else [args.server] * 3
    jobs, reused = [], []
    for index, server in enumerate(routes):
        start = index * chunk_size
        path = folder / f'{index:03d}.chunk'
        if path.exists():
            if path.read_bytes() == reference[start:start + chunk_size]:
                reused.append(index)
                continue
            raise ValueError('existing chunk mismatch')
        jobs.append((index, server, start, path))
    c = Client(load_secret())
    urls = {}
    try:
        detail = inspect_detail(c.request('/assist/detail?id=' + args.assist_id).text, c.secret['account'])
        if args.file_id not in {f['file_id'] for f in detail['files']}:
            raise ValueError('file is not available in this own request')
        page = '/assist/download?id=' + args.file_id
        html = c.request(page).text
        parse_profile(html, c.secret['account'])
        config = json.loads(re.search(r'const config\s*=\s*(\{[^\n]+\});', html).group(1))
        csrf = BeautifulSoup(html, 'html.parser').select_one('meta[name="csrf-token"]')['content']
        for server in sorted({job[1] for job in jobs}):
            reply = c.request('/file/request-download-token', method='POST', headers={
                'X-CSRF-Token': csrf, 'X-Requested-With': 'XMLHttpRequest', 'Referer': BASE + page}, data={
                'type': 'assistFile', 'id': args.file_id, 'channel': 'normal', 'highspeed': '0',
                'fallback': '0', 'file_server': server, 'remove_sensitive': '1'}).json()
            if reply.get('code') != 0:
                raise ValueError('token request rejected')
            urls[server] = token_url(reply['data'], config['allowedNodeHosts'])
    finally:
        c.persist()
        c.session.close()

    def fetch(job):
        index, server, start, path = job
        end = start + chunk_size - 1
        began = time.monotonic()
        result = {'index': index, 'server_id': server, 'start': start, 'end': end, 'status': 'failed'}
        try:
            with requests.get(urls[server], stream=True, allow_redirects=False, timeout=(10, 25), headers={
                'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity',
                'Referer': BASE + '/'}) as response:
                result['header_seconds'] = round(time.monotonic() - began, 3)
                result['http_status'] = response.status_code
                if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{total}':
                    raise ValueError('range response mismatch')
                body = bytearray()
                for part in response.iter_content(4096):
                    body.extend(part)
                    if len(body) > chunk_size or time.monotonic() - began > 45:
                        raise ValueError('sample size or duration exceeded')
                if bytes(body) != reference[start:end + 1]:
                    raise ValueError('sample bytes differ from reference')
                temporary = path.with_suffix('.tmp')
                temporary.write_bytes(body)
                temporary.replace(path)
                result.update(status='complete', bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        except Exception as error:
            # Never expose request URLs or tokens via exception messages.
            result['error_type'] = type(error).__name__
        result['seconds'] = round(time.monotonic() - began, 3)
        return result

    started = time.monotonic()
    results = []
    concurrency = 3 if args.mode == 'parallel' and not args.resume else 1
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        for future in as_completed([executor.submit(fetch, job) for job in jobs]):
            result = future.result()
            results.append(result)
            print(json.dumps(result), flush=True)
    seconds = time.monotonic() - started
    report = {'mode': args.mode, 'resumed': args.resume, 'concurrency': concurrency,
              'transfer_seconds': round(seconds, 3), 'reused_chunks': reused,
              'results': sorted(results, key=lambda r: r['index'])}
    report['new_bytes'] = sum(r.get('bytes', 0) for r in results)
    report['useful_kib_per_second'] = round(report['new_bytes'] / 1024 / max(seconds, .001), 2)
    paths = [folder / f'{index:03d}.chunk' for index in range(3)]
    if all(path.exists() for path in paths):
        assembled = b''.join(path.read_bytes() for path in paths)
        report['merged_matches_reference'] = assembled == reference[:3 * chunk_size]
        if not report['merged_matches_reference']:
            raise ValueError('assembled data mismatch')
        (folder / 'assembled-192KiB.bin').write_bytes(assembled)
        report['assembled_bytes'] = len(assembled)
    filename = 'resume-result.json' if args.resume else 'result.json'
    (folder / filename).write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except Exception as error:
        print(json.dumps({'error_type': type(error).__name__}))
        raise SystemExit(2)
