"""Download files from the current user's AbleSci requests using ordinary HTTP."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from pypdf import PdfReader
import requests

from checkin import BASE, Client, CheckinError, load_secret, parse_profile

ROOT = Path(__file__).resolve().parent


def inspect_detail(html: str, account: str) -> dict:
    parse_profile(html, account)
    soup = BeautifulSoup(html, 'html.parser')
    rows = {}
    for row in soup.select('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) == 2:
            rows[cells[0].get_text(strip=True)] = cells[1]
    owner = rows.get('求助人')
    owner_link = owner.select_one('a[data-id]') if owner else None
    scope = re.search(r'window\.AbleActivity\.start\(\{\s*scope:\s*["\']([^"\']+)', html)
    if not owner_link or not scope or owner_link.get('data-id') != scope.group(1):
        raise CheckinError('该求助不属于当前登录账号，停止下载。')
    if owner_link.get_text(strip=True) != account:
        raise CheckinError('求助人身份不符。')
    title = rows.get('标题')
    doi_cell = rows.get('DOI')
    doi_match = re.search(r'10\.\d{4,9}/[^\s]+', doi_cell.get_text(' ', strip=True)) if doi_cell else None
    page_title = soup.title.get_text() if soup.title else ''
    status_match = re.match(r'【([^】]+)】', page_title)
    files = []
    seen = set()
    for link in soup.select('a[href]'):
        url = urlsplit(urljoin(BASE, link['href']))
        if url.netloc != 'www.ablesci.com' or url.path != '/assist/download':
            continue
        file_id = parse_qs(url.query).get('id', [''])[0]
        item = link.find_parent('li')
        badge = item.select_one('.assistfile-badge') if item else None
        badge_text = badge.get_text(strip=True) if badge else ''
        if any(word in badge_text for word in ['驳回', '撤回', '删除']):
            continue
        if not re.fullmatch(r'[A-Za-z0-9]+', file_id) or file_id in seen:
            continue
        seen.add(file_id)
        files.append({'file_id': file_id, 'name': link.get_text(strip=True), 'state': badge_text})
    expired = '文件已从服务器自动删除' in soup.get_text()
    return {'status': status_match.group(1) if status_match else 'unknown',
            'title': title.get_text(' ', strip=True) if title else '',
            'doi': doi_match.group(0) if doi_match else '', 'expired': expired, 'files': files}


def safe_filename(name: str) -> str:
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name).strip(' .')
    name = name[:180].rstrip(' .') or 'document.pdf'
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        name = '_' + name
    return name


def token_url(data: dict, allowed: list[str]) -> str:
    if data.get('channel') != 'normal' or data.get('transport') != 'normal':
        raise CheckinError('下载通道不是免费普通线路，已停止。')
    target = urlsplit(data.get('host', ''))
    if (target.scheme != 'https' or target.username or target.password
            or target.port not in (None, 443) or target.hostname not in allowed
            or not re.fullmatch(r'filehub\d+\.ablesci\.com', target.hostname or '')):
        raise CheckinError('下载节点未通过校验。')
    if not data.get('token') or not data.get('output_filename'):
        raise CheckinError('下载令牌响应字段不完整。')
    params = parse_qs(target.query)
    params['token'] = [data['token']]
    return urlunsplit((target.scheme, target.netloc, target.path, urlencode(params, doseq=True), ''))


def check_pdf(path: Path, expected_doi: str, expected_title: str) -> dict:
    with path.open('rb') as f:
        if f.read(5) != b'%PDF-':
            raise CheckinError('下载结果不是 PDF，不能标记为文献已获取。')
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise CheckinError('PDF 有密码保护，需要人工核验。')
        pages = len(reader.pages)
        if pages < 1:
            raise CheckinError('PDF 没有可读页面。')
        text = '\n'.join(page.extract_text() or '' for page in reader.pages[:3])
        # Parse the last page as a basic check for a truncated page tree as well.
        _ = reader.pages[-1].mediabox
    except CheckinError:
        raise
    except Exception:
        raise CheckinError('PDF 解析失败，需要重新下载或人工检查。') from None
    normalized = re.sub(r'\s+', '', text).lower()
    title_normalized = re.sub(r'[^a-z0-9]', '', expected_title.lower())
    title_text = re.sub(r'[^a-z0-9]', '', text.lower())
    return {'pages': pages, 'doi_match': bool(expected_doi and expected_doi.lower() in normalized),
            'title_match': bool(title_normalized and title_normalized in title_text)}


def download_file(client: Client, file_id: str, out: Path, detail: dict, preferred_server: str | None = None) -> dict:
    page_path = '/assist/download?' + urlencode({'id': file_id})
    html = client.request(page_path).text
    parse_profile(html, client.secret['account'])
    soup = BeautifulSoup(html, 'html.parser')
    config_match = re.search(r'const config\s*=\s*(\{[^\n]+\});', html)
    if not config_match:
        raise CheckinError('下载页结构改变或文件过期，未找到下载配置。')
    config = json.loads(config_match.group(1))
    if config.get('hashid') != file_id or config.get('tokenUrl') != '/file/request-download-token':
        raise CheckinError('下载页标识与文件不一致。')
    csrf = soup.select_one('meta[name="csrf-token"]')
    if not csrf:
        raise CheckinError('下载页缺少 CSRF 校验。')
    normal = [str(item['id']) for item in config['normalServers']]
    server = preferred_server or str(config['defaultServerId'])
    if preferred_server and preferred_server not in normal:
        raise CheckinError('所选服务器不在普通线路列表中。')
    if server not in normal:
        server = normal[0]
    headers = {'X-CSRF-Token': csrf['content'], 'X-Requested-With': 'XMLHttpRequest',
               'Referer': BASE + page_path, 'Accept': 'application/json'}
    reply = client.request('/file/request-download-token', method='POST', headers=headers, data={
        'type': 'assistFile', 'id': file_id, 'channel': 'normal', 'highspeed': '0',
        'fallback': '0', 'file_server': server, 'remove_sensitive': '1'}).json()
    if reply.get('code') != 0 or not isinstance(reply.get('data'), dict):
        raise CheckinError('获取下载令牌失败；请检查该文件状态。')
    data = reply['data']
    url = token_url(data, config['allowedNodeHosts'])
    out.mkdir(parents=True, exist_ok=True)
    filename = file_id + '-' + safe_filename(str(data['output_filename']))
    destination = out / filename
    partial = out / (filename + '.part')
    expected_size = int(data.get('expected_size') or config.get('expectedSize') or 0)
    if destination.exists():
        size = destination.stat().st_size
        validation = check_pdf(destination, detail['doi'], detail['title'])
        if (expected_size and size != expected_size) or not all(
                validation[key] for key in ('doi_match', 'title_match')):
            raise CheckinError('已有文件未通过大小/文献核验，请人工检查或选择其他目录。')
        with destination.open('rb') as saved:
            digest = hashlib.file_digest(saved, 'sha256').hexdigest()
        return {'file_id': file_id, 'path': str(destination), 'bytes': size,
                'sha256': digest, 'channel': 'normal', 'server_id': server,
                'verification': validation, 'accepted': False, 'reused': True}
    digest = hashlib.sha256()
    size = 0
    began = time.monotonic()
    last_report = began
    print(f'普通线路 server_id={server}，预期 {expected_size} 字节', file=sys.stderr, flush=True)
    # Match the official page's withCredentials=false. Never send account cookies to file nodes.
    try:
        with requests.get(url, stream=True, allow_redirects=False, timeout=(15, 120),
                          headers={'Referer': BASE + '/', 'Accept-Encoding': 'identity',
                                   'User-Agent': client.session.headers['User-Agent']}) as response:
            if response.status_code != 200:
                raise CheckinError(f'文件节点返回 HTTP {response.status_code}，未保存为成功结果。')
            if 'text/html' in response.headers.get('Content-Type', '').lower():
                raise CheckinError('文件节点返回网页而不是文件。')
            with partial.open('wb') as output:
                for chunk in response.iter_content(16384):
                    if time.monotonic() - began > 600:
                        raise CheckinError('下载超过 10 分钟，保留 .part 文件供检查。')
                    if chunk:
                        output.write(chunk); digest.update(chunk); size += len(chunk)
                    if time.monotonic() - last_report >= 30:
                        print(f'已接收 {size}/{expected_size} 字节', file=sys.stderr, flush=True)
                        last_report = time.monotonic()
                    if size > 100 * 1024 * 1024:
                        raise CheckinError('文件超过本脚本 100 MB 上限。')
    except requests.RequestException:
        raise CheckinError('普通线路下载失败，未自动切换收费线路。') from None
    if not size or (expected_size and size != expected_size):
        raise CheckinError(f'文件大小不匹配：收到 {size}，预期 {expected_size} 字节。')
    validation = check_pdf(partial, detail['doi'], detail['title'])
    partial.rename(destination)
    return {'file_id': file_id, 'path': str(destination), 'bytes': size,
            'sha256': digest.hexdigest(), 'channel': 'normal', 'server_id': server,
            'verification': validation, 'accepted': False}


def main() -> int:
    p = argparse.ArgumentParser(description='等待本人科研通求助的应助文件，并用普通线路下载 PDF')
    p.add_argument('--assist-id', required=True)
    p.add_argument('--output-dir', type=Path, default=ROOT / 'downloads')
    p.add_argument('--wait-seconds', type=int, default=0)
    p.add_argument('--poll-seconds', type=int, default=120)
    p.add_argument('--status-only', action='store_true')
    p.add_argument('--server', help='普通线路服务器 ID，当前为 2、3、4；不启用高速线路')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9]+', args.assist_id):
        p.error('invalid assist id')
    if args.wait_seconds < 0 or args.poll_seconds < 15:
        p.error('wait must be nonnegative; polling interval must be at least 15 seconds')
    client = Client(load_secret())
    deadline = time.monotonic() + args.wait_seconds
    try:
        while True:
            html = client.request('/assist/detail?' + urlencode({'id': args.assist_id})).text
            detail = inspect_detail(html, client.secret['account'])
            if args.status_only:
                print(json.dumps(detail, ensure_ascii=False)); return 0
            if detail['expired']:
                raise CheckinError('求助文件已经过期删除。')
            if detail['files']:
                results = [download_file(client, f['file_id'], args.output_dir, detail, args.server)
                           for f in detail['files']]
                verified = all(item['verification']['doi_match'] and item['verification']['title_match']
                               for item in results)
                result = {'status': 'downloaded' if verified else 'needs_review',
                          'assist_id': args.assist_id, 'paper': detail, 'files': results}
                (args.output_dir / (args.assist_id + '-result.json')).write_text(
                    json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(result, ensure_ascii=False)); return 0
            if detail['status'] in {'已关闭', '已完结'}:
                raise CheckinError('求助已结束但没有可下载文件。')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(json.dumps({'status': 'waiting', 'assist_id': args.assist_id}, ensure_ascii=False)); return 4
            time.sleep(min(args.poll_seconds, remaining))
    finally:
        client.persist(); client.session.close()


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    try:
        raise SystemExit(main())
    except CheckinError as error:
        print(json.dumps({'status': 'error', 'message': str(error)}, ensure_ascii=False)); raise SystemExit(2)
    except Exception as error:
        print(json.dumps({'status': 'error', 'message': type(error).__name__}, ensure_ascii=False)); raise SystemExit(3)
