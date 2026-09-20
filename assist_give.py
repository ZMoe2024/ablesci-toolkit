"""Prepare or submit one verified PDF to an AbleSci request."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
import requests

from assist_download import check_pdf
from checkin import BASE, Client, CheckinError, load_secret, parse_profile

ROOT = Path(__file__).resolve().parent


def read_target(client, assist_id):
    html = client.request('/assist/detail?id=' + assist_id).text
    parse_profile(html, client.secret['account'])
    soup = BeautifulSoup(html, 'html.parser')
    rows = {}
    for row in soup.select('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) == 2:
            rows[cells[0].get_text(strip=True)] = cells[1].get_text(' ', strip=True)
    identifier = soup.select_one('.uploading-assist-id-val')
    csrf = soup.select_one('meta[name="csrf-token"]')
    scope = re.search(r'window\.AbleActivity\.start\(\{\s*scope:\s*["\']([^"\']+)', html)
    if not identifier or identifier.get('value') != assist_id or not csrf or not scope:
        raise CheckinError('求助页面身份/安全字段缺失。')
    doi = re.search(r'10\.\d{4,9}/[^\s]+', rows.get('DOI', ''))
    target = {'assist_id': assist_id, 'title': rows.get('标题', ''),
              'doi': doi.group(0) if doi else '', 'note': rows.get('备注', ''),
              'page_title': soup.title.get_text() if soup.title else '',
              'can_upload': bool(soup.select_one('#browse-btn'))}
    return target, soup, csrf['content'], scope.group(1)


def own_files(soup, scope):
    files = []
    for item in soup.select('li.layui-timeline-item'):
        user = item.select_one('.timeline-user a.user-name[data-id]')
        field = item.select_one('.assist-file-id')
        if user and user.get('data-id') == scope and field:
            badge = item.select_one('.assistfile-badge')
            name = item.select_one('.file-info a.name')
            files.append({'file_id': field.get('value'),
                          'name': name.get_text(strip=True) if name else '',
                          'status': badge.get_text(strip=True) if badge else ''})
    return files


def save(path, result):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description='核验并向单条科研通求助提交PDF；默认只准备')
    parser.add_argument('--assist-id', required=True)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--submit', action='store_true', help='实际应助，MD5命中也会直接提交')
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9]+', args.assist_id):
        parser.error('invalid assist ID')
    path = args.file.resolve(strict=True)
    if path.suffix.lower() != '.pdf' or not 0 < path.stat().st_size <= 50 * 1024 * 1024:
        raise CheckinError('当前入口仅支持不超过50 MiB的PDF正文。')
    with path.open('rb') as f:
        md5 = hashlib.file_digest(f, 'md5').hexdigest()
    with path.open('rb') as f:
        sha256 = hashlib.file_digest(f, 'sha256').hexdigest()
    receipt = ROOT / ('give-' + args.assist_id + '.json')
    if receipt.exists():
        old = json.loads(receipt.read_text(encoding='utf-8'))
        if old.get('status') != 'prepared' or old.get('sha256') != sha256:
            raise CheckinError('已有提交记录或待核查尝试；请先核对站内状态，禁止盲目重发。')
    client = Client(load_secret())
    try:
        target, soup, csrf, scope = read_target(client, args.assist_id)
        if not target['page_title'].startswith('【求助中】') or not target['can_upload']:
            raise CheckinError('该求助目前不可应助，未调用上传请求。')
        if '补充材料' in target['page_title'] or '补充材料' in target['title']:
            raise CheckinError('此入口仅用于正文，补充材料需单独核验。')
        if own_files(soup, scope):
            raise CheckinError('该求助已有本人上传记录，先人工核对，未重复提交。')
        validation = check_pdf(path, target['doi'], target['title'])
        if not validation['doi_match'] or not validation['title_match']:
            raise CheckinError('PDF题名或DOI未匹配，未调用上传请求。')
        result = {'status': 'prepared', 'target': target, 'file': str(path),
                  'bytes': path.stat().st_size, 'md5': md5, 'sha256': sha256,
                  'verification': validation, 'created_at': datetime.now(timezone.utc).isoformat()}
        save(receipt, result)
        if not args.submit:
            print(json.dumps(result, ensure_ascii=False)); return 0
        # Persist the uncertain state BEFORE the first mutating request.
        result['status'] = 'submission_pending_verification'
        save(receipt, result)
        headers = {'X-CSRF-Token': csrf, 'X-Requested-With': 'XMLHttpRequest',
                   'Referer': BASE + '/assist/detail?id=' + args.assist_id}
        reply = client.request('/assist/upload-request?t=' + str(int(time.time() * 1000)),
            method='POST', headers=headers, data={'assist_id': args.assist_id,
                'filename': path.name, 'file_md5': md5, 'filesize': str(path.stat().st_size)}).json()
        code = reply.get('code')
        result['upload_request_code'] = code
        if code == 0:
            data = reply.get('data', {})
            host = urlsplit(data.get('host', ''))
            name = host.hostname or ''
            if (host.scheme != 'https' or host.username or host.password or host.port not in (None, 443)
                    or not (name.endswith('.aliyuncs.com') or name.endswith('.ablesci.com'))):
                save(receipt, result)
                raise CheckinError('上传目的地尚未验证，保留记录供检查。')
            fields = {'assist_id': args.assist_id, 'key': data['dir'] + data['randFilename'],
                      'policy': data['policy'], 'OSSAccessKeyId': data['accessid'],
                      'success_action_status': '200', 'callback': data['callback'],
                      'signature': data['signature'], 'x:filename': data['filename'],
                      'x:assist_id': data['assist_id'], 'x:user_id': data['user_id']}
            if str(data['assist_id']) != args.assist_id:
                raise CheckinError('上传签名对应的求助ID不符。')
            result['mode'] = 'oss_upload'
            result['upload_host'] = name
            save(receipt, result)
            print('已取得上传签名，正在传输PDF。', file=sys.stderr, flush=True)
            # Separate request: never forward the account cookies to object storage.
            with path.open('rb') as source:
                response = requests.post(data['host'], data=fields,
                    files={'file': (path.name, source, 'application/pdf')},
                    timeout=(15, 120), allow_redirects=False)
            result['upload_http_status'] = response.status_code
            try:
                outcome = response.json()
                result['upload_callback_code'] = outcome.get('code')
            except ValueError:
                result['upload_callback_code'] = 'non_json'
        elif code == 10:
            result['mode'] = 'md5_reuse'
        else:
            result['status'] = 'needs_captcha' if code == 2 else 'request_rejected'
            result['message'] = BeautifulSoup(str(reply.get('msg', '')), 'html.parser').get_text(' ', strip=True)[:500]
            save(receipt, result)
            print(json.dumps(result, ensure_ascii=False)); return 2
        save(receipt, result)
        for delay in (0, 2, 4):
            if delay:
                time.sleep(delay)
            latest, updated, _, identity = read_target(client, args.assist_id)
            files = own_files(updated, identity)
            if files:
                result['status'] = 'submitted'
                result['files'] = files
                result['page_title_after'] = latest['page_title']
                result['verified_at'] = datetime.now(timezone.utc).isoformat()
                save(receipt, result)
                print(json.dumps(result, ensure_ascii=False)); return 0
        save(receipt, result)
        print(json.dumps(result, ensure_ascii=False)); return 3
    finally:
        client.persist(); client.session.close()


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except CheckinError as error:
        print(json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=False)); raise SystemExit(2)
    except Exception as error:
        print(json.dumps({'status': 'error', 'error_type': type(error).__name__})); raise SystemExit(3)
