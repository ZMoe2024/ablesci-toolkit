"""AbleSci HTTP check-in. No browser, Codex, or cloud service is used at runtime."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta, timezone
import getpass
import json
import os
from pathlib import Path
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'AbleSciCheckin'
SECRET = DATA / 'session.dpapi'
BASE = 'https://www.ablesci.com'
TZ = timezone(timedelta(hours=8))
COOKIE_NAMES = {'_identity-frontend', 'ablesci-serial', 'advanced-frontend', '_csrf', 'security_session_verify'}


class CheckinError(Exception):
    pass


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def dpapi(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != 'nt':
        raise CheckinError('本版本使用 Windows DPAPI 保存登录态，请在当前 Windows 账号下运行。')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    func.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise CheckinError('登录态加解密失败，请使用最初导入登录态的 Windows 账号。')
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)


def save_secret(value: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    temp = SECRET.with_suffix('.tmp')
    temp.write_bytes(dpapi(json.dumps(value, ensure_ascii=False).encode('utf-8')))
    temp.replace(SECRET)


def load_secret() -> dict:
    if not SECRET.exists():
        raise CheckinError('尚未配置登录态。请运行 import-session.cmd。')
    return json.loads(dpapi(SECRET.read_bytes(), decrypt=True))


def import_cookie(raw: str, account: str) -> None:
    raw = raw.strip()
    if raw.lower().startswith('cookie:'):
        raw = raw.split(':', 1)[1].strip()
    if '\r' in raw or '\n' in raw:
        raise CheckinError('Cookie 必须为一行文本。')
    cookies = []
    for item in raw.split(';'):
        name, sep, value = item.strip().partition('=')
        if sep and name in COOKIE_NAMES:
            cookies.append({'name': name, 'value': value, 'domain': 'www.ablesci.com', 'path': '/'})
    if not any(c['name'] in {'advanced-frontend', '_identity-frontend'} for c in cookies):
        raise CheckinError('没有找到科研通登录 Cookie。')
    save_secret({'account': account, 'cookies': cookies})


def parse_profile(html: str, expected: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    name = soup.select_one('.able-head-user-vip-username')
    if not name:
        raise CheckinError('登录已失效或页面结构发生变化，请重新登录并更新登录态。')
    username = name.get_text(strip=True)
    if username != expected:
        raise CheckinError('登录账号与配置不符，已停止。')
    points = soup.select_one('#user-point-now')
    days = soup.select_one('#sign-count')
    return {'account': username,
            'points': int(points.get_text(strip=True)) if points else None,
            'consecutive_days': int(days.get_text(strip=True)) if days else None}


def find_record(html: str, day: str) -> dict | None:
    soup = BeautifulSoup(html, 'html.parser')
    for row in soup.select('tr'):
        cells = [c.get_text(' ', strip=True) for c in row.select('td')]
        if len(cells) >= 3 and re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', cells[0]):
            if cells[0].startswith(day + ' ') and cells[2] == '签到':
                return {'time': cells[0], 'reward': cells[1]}
    return None


class Client:
    def __init__(self, secret: dict):
        self.secret = secret
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36',
                                     'Referer': BASE + '/', 'Accept-Language': 'zh-CN,zh;q=0.9'})
        for item in secret['cookies']:
            domain = item.get('domain', 'www.ablesci.com')
            if domain not in {'www.ablesci.com', '.ablesci.com', 'ablesci.com'}:
                continue
            self.session.cookies.set(item['name'], item['value'], domain=domain,
                                     path=item.get('path', '/'), secure=True)

    def request(self, path: str, method: str = 'GET', **kwargs) -> requests.Response:
        if not path.startswith('/') or path.startswith('//'):
            raise CheckinError('无效的网站路径。')
        try:
            res = self.session.request(method, BASE + path, timeout=(10, 25),
                                       allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise CheckinError('网络请求失败；请检查网络后重试。') from None
        if 300 <= res.status_code < 400:
            raise CheckinError('网站要求跳转，可能登录已失效；请重新登录后更新登录态。')
        if res.status_code in {401, 403}:
            raise CheckinError('网站拒绝请求或需要验证，请到网站手动处理。')
        if res.status_code >= 400:
            raise CheckinError(f'网站返回 HTTP {res.status_code}，未确认签到成功。')
        res.encoding = 'utf-8'
        return res

    def profile(self) -> tuple[dict, str]:
        html = self.request('/').text
        return parse_profile(html, self.secret['account']), html

    def record(self, day: str) -> dict | None:
        # The account name is checked on the private ledger as well.
        html = self.request('/my/point').text
        parse_profile(html, self.secret['account'])
        return find_record(html, day)

    def persist(self) -> None:
        self.secret['cookies'] = [
            {'name': c.name, 'value': c.value, 'domain': c.domain, 'path': c.path}
            for c in self.session.cookies if c.name in COOKIE_NAMES
        ]
        save_secret(self.secret)

    def sign(self, html: str) -> dict:
        soup = BeautifulSoup(html, 'html.parser')
        token = soup.select_one('meta[name="csrf-token"]')
        headers = {'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest'}
        if token:
            headers['X-CSRF-Token'] = token.get('content', '')
        # The site's sign endpoint is verified separately with an already-signed account.
        response = self.request('/user/sign', headers=headers)
        try:
            result = response.json()
        except ValueError:
            raise CheckinError('签到接口没有返回 JSON，可能需要登录或验证。') from None
        if not isinstance(result, dict):
            raise CheckinError('签到接口返回格式异常。')
        return result


def run(client: Client, check_only: bool = False) -> dict:
    day = datetime.now(TZ).date().isoformat()
    profile, html = client.profile()
    before = client.record(day)
    if before:
        client.persist()
        return {'status': 'already_signed', 'date': day, **profile, **before}
    if check_only:
        client.persist()
        return {'status': 'not_signed', 'date': day, **profile}
    response = client.sign(html)
    # A timeout or success-looking response is never treated as a verified success.
    after = None
    for attempt in range(3):
        current_day = datetime.now(TZ).date().isoformat()
        after = client.record(current_day)
        if after:
            day = current_day
            break
        if attempt < 2:
            time.sleep(2)
    client.persist()
    if not after:
        # Keep raw server text out of logs: it may contain identifiers or tokens.
        code = response.get('code')
        safe_code = code if isinstance(code, (int, float)) else 'unknown'
        raise CheckinError(f'没有查到今日签到入账记录（接口代码 {safe_code}），不能确认成功。')
    profile, _ = client.profile()
    client.persist()
    return {'status': 'signed', 'date': day, **profile, **after}


def emit(result: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    result['checked_at'] = datetime.now(TZ).isoformat(timespec='seconds')
    text = json.dumps(result, ensure_ascii=False)
    (DATA / 'last-result.json').write_text(text + '\n', encoding='utf-8')
    with (DATA / 'checkin.jsonl').open('a', encoding='utf-8') as log:
        log.write(text + '\n')
    print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description='科研通独立 HTTP 签到脚本')
    parser.add_argument('--check-only', action='store_true', help='只读取今日签到记录，不调用签到接口')
    parser.add_argument('--import-session', action='store_true', help='安全输入并加密保存 Cookie')
    parser.add_argument('--import-stdin', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--account', help='导入时填写科研通昵称，用于校验登录账号')
    args = parser.parse_args()
    try:
        if args.import_session or args.import_stdin:
            account = (args.account or '').strip()
            if not account and args.import_session:
                account = input('科研通账号昵称：').strip()
            if not account:
                raise CheckinError('导入时必须指定账号昵称；非交互导入请提供 --account。')
            raw = sys.stdin.read() if args.import_stdin else getpass.getpass('粘贴科研通 Cookie（不回显），然后回车：')
            import_cookie(raw, account)
            print('登录态已在当前 Windows 用户下加密保存。')
            return 0
        client = Client(load_secret())
        try:
            result = run(client, args.check_only)
        finally:
            client.session.close()
        emit(result)
        return 0
    except CheckinError as exc:
        emit({'status': 'error', 'message': str(exc)})
        return 2
    except Exception as exc:
        # Avoid tracebacks including server payloads, request headers or cookies.
        emit({'status': 'error', 'message': '脚本异常：' + type(exc).__name__})
        return 3


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
