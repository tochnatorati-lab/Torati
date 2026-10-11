# -*- coding: utf-8 -*-
# שרת מקומי של תּוֹרָתִי - מגיש את קבצי התוכנה מהתיקייה הזו (כמו python -m http.server),
# ובנוסף יודע לעדכן את התוכנה לגרסה חדשה בלחיצה אחת מתוך התוכנה עצמה.
# החידושים השמורים נמצאים בדפדפן (localStorage) ולא בקבצים האלה, ולכן העדכון לא נוגע בהם.
# לפני כל עדכון נשמר עותק של הקבצים הישנים בתיקייה "גיבוי_גרסאות".

import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import sys
import time
import urllib.request

PORT = 8951
# כתובת קובץ הגרסה. התוכנה עצמה שולחת כתובת (UPDATE_URL שלה); זו ברירת המחדל אם לא נשלחה.
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/tochnatorati-lab/torati/main/version.json'

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(APP_DIR, 'גיבוי_גרסאות')
ALLOWED_EXT = {'.html', '.js', '.json', '.png', '.ico', '.txt', '.md', '.py', '.bat', '.docx'}
SAFE_NAME = re.compile(r'^[\w֐-׿][\w֐-׿ .\-]*$')
MAX_FILE = 30 * 1024 * 1024


def fetch(url, timeout=60):
    sep = '&' if '?' in url else '?'
    req = urllib.request.Request(url + sep + 't=' + str(int(time.time())),
                                 headers={'User-Agent': 'Torati-Updater', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise ValueError('קובץ גדול מדי')
    return data


def safe_name(name):
    if not isinstance(name, str) or '/' in name or '\\' in name or '..' in name:
        return False
    if not SAFE_NAME.match(name):
        return False
    return os.path.splitext(name)[1].lower() in ALLOWED_EXT


def current_version():
    try:
        with open(os.path.join(APP_DIR, 'torah_app.html'), encoding='utf-8') as f:
            m = re.search(r"APP_VERSION\s*=\s*'([^']+)'", f.read())
            return m.group(1) if m else '0'
    except OSError:
        return '0'


def do_update(update_url):
    info = json.loads(fetch(update_url).decode('utf-8'))
    version = str(info['version'])
    base = info.get('base_url') or update_url.rsplit('/', 1)[0] + '/'
    if not base.endswith('/'):
        base += '/'
    files = info.get('files') or ['torah_app.html']

    # שלב 1: מורידים הכל לזיכרון ובודקים, ורק אם הכל תקין כותבים לדיסק - כך שעדכון שנקטע לא משאיר תוכנה שבורה
    downloaded = {}
    for entry in files:
        name = entry if isinstance(entry, str) else entry.get('name')
        sha = None if isinstance(entry, str) else entry.get('sha256')
        if not safe_name(name):
            raise ValueError('שם קובץ לא חוקי: %r' % name)
        data = fetch(base + urllib.request.quote(name))
        if sha and hashlib.sha256(data).hexdigest().lower() != sha.lower():
            raise ValueError('הקובץ %s הגיע פגום (בדיקת תקינות נכשלה)' % name)
        downloaded[name] = data
    html = downloaded.get('torah_app.html')
    if html is not None and ("APP_VERSION = '%s'" % version) not in html.decode('utf-8', 'replace'):
        raise ValueError('הקובץ שהורד לא תואם לגרסה %s' % version)

    # שלב 2: גיבוי הקבצים הנוכחיים
    old = current_version()
    dest = os.path.join(BACKUP_DIR, '%s_%s' % (old, time.strftime('%Y-%m-%d_%H-%M')))
    os.makedirs(dest, exist_ok=True)
    for name in downloaded:
        p = os.path.join(APP_DIR, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, name))

    # שלב 3: כתיבה - קודם לקובץ זמני ואז החלפה, כדי שלא יישאר קובץ חצי-כתוב
    for name, data in downloaded.items():
        p = os.path.join(APP_DIR, name)
        tmp = p + '.new'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
    return {'ok': True, 'version': version, 'old_version': old, 'files': list(downloaded)}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=APP_DIR, **kw)

    def _local_only(self):
        host = self.client_address[0]
        if host in ('127.0.0.1', '::1', '::ffff:127.0.0.1'):
            return True
        self.send_error(403)
        return False

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # תמיד לבדוק מול הקובץ בדיסק, כדי שאחרי עדכון הדפדפן לא יציג גרסה ישנה
        if not self.path.startswith('/__'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def do_GET(self):
        if not self._local_only():
            return
        if self.path.startswith('/__torati/ping'):
            return self._json(200, {'ok': True, 'updater': 1, 'version': current_version()})
        return super().do_GET()

    def do_HEAD(self):
        if self._local_only():
            super().do_HEAD()

    def do_POST(self):
        if not self._local_only():
            return
        if not self.path.startswith('/__torati/update'):
            return self.send_error(404)
        # הכותרת המיוחדת מונעת מאתרים אחרים בדפדפן להפעיל עדכון בלי ידיעת המשתמש
        if self.headers.get('X-Torati') != '1':
            return self.send_error(403)
        try:
            length = int(self.headers.get('Content-Length') or 0)
            req = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
            url = req.get('url') or DEFAULT_UPDATE_URL
            if not url.startswith('https://'):
                raise ValueError('כתובת עדכון לא חוקית')
            result = do_update(url)
            print('Updated to version', result['version'])
            self._json(200, result)
        except Exception as e:
            print('Update failed:', repr(e))
            self._json(500, {'ok': False, 'error': str(e)})

    def log_message(self, fmt, *args):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server():
    # מאזינים גם ל-IPv6 וגם ל-IPv4 (כמו python -m http.server), כדי ש-localhost יעבוד בכל מחשב.
    # בקשות שלא מהמחשב עצמו נחסמות ב-_local_only.
    try:
        class Server6(Server):
            address_family = socket.AF_INET6

            def server_bind(self):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                super().server_bind()
        return Server6(('::', PORT), Handler)
    except (OSError, AttributeError, ValueError):
        return Server(('127.0.0.1', PORT), Handler)


if __name__ == '__main__':
    try:
        httpd = make_server()
    except OSError:
        print('Torati is already running (port %d is busy). You can close this window.' % PORT)
        sys.exit(0)
    print('Torati is running on http://localhost:%d/torah_app.html' % PORT)
    print('Do not close this window while using the app.')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
