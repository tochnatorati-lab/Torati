# -*- coding: utf-8 -*-
# שרת מקומי של תּוֹרָתִי - מגיש את קבצי התוכנה מהתיקייה הזו (כמו python -m http.server),
# ובנוסף יודע להוריד גרסה חדשה מתוך התוכנה עצמה ולהחיל אותה בהפעלה הבאה.
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
import base64
import sys
import time
import urllib.request

PORT = 8951
# כתובת קובץ הגרסה. התוכנה עצמה שולחת כתובת (UPDATE_URL שלה); זו ברירת המחדל אם לא נשלחה.
DEFAULT_UPDATE_URL = 'https://raw.githubusercontent.com/tochnatorati-lab/torati/main/version.json'

APP_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(APP_DIR, 'גיבוי_גרסאות')
PENDING_DIR = os.path.join(APP_DIR, 'עדכון_ממתין')
PENDING_INFO = os.path.join(PENDING_DIR, 'pending.json')
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


def download_update(update_url):
    """מוריד את הגרסה החדשה לתיקיית המתנה. הקבצים של התוכנה עצמה לא משתנים עד ההפעלה הבאה."""
    info = json.loads(fetch(update_url).decode('utf-8'))
    version = str(info['version'])
    base = info.get('base_url') or update_url.rsplit('/', 1)[0] + '/'
    if not base.endswith('/'):
        base += '/'
    files = info.get('files') or ['torah_app.html']

    # מורידים הכל לזיכרון ובודקים, ורק אם הכל תקין שומרים - כך שהורדה שנקטעה לא משאירה עדכון שבור
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
    return stage_update(version, downloaded)


def stage_update(version, downloaded):
    """בודק ושומר את קבצי הגרסה החדשה בתיקיית ההמתנה (גם כשהדפדפן הוריד אותם בעצמו)."""
    for name in downloaded:
        if not safe_name(name):
            raise ValueError('שם קובץ לא חוקי: %r' % name)
        if len(downloaded[name]) > MAX_FILE:
            raise ValueError('קובץ גדול מדי')
    html = downloaded.get('torah_app.html')
    if html is not None and ("APP_VERSION = '%s'" % version) not in html.decode('utf-8', 'replace'):
        raise ValueError('הקובץ שהורד לא תואם לגרסה %s' % version)

    if os.path.isdir(PENDING_DIR):
        shutil.rmtree(PENDING_DIR, ignore_errors=True)
    os.makedirs(PENDING_DIR, exist_ok=True)
    for name, data in downloaded.items():
        with open(os.path.join(PENDING_DIR, name), 'wb') as f:
            f.write(data)
    # pending.json נכתב אחרון: כל עוד הוא לא קיים, ההורדה לא נחשבת גמורה
    with open(PENDING_INFO, 'w', encoding='utf-8') as f:
        json.dump({'version': version, 'files': list(downloaded)}, f, ensure_ascii=False)
    return {'ok': True, 'version': version}


def pending_version():
    try:
        with open(PENDING_INFO, encoding='utf-8') as f:
            return str(json.load(f)['version'])
    except (OSError, ValueError, KeyError):
        return None


def apply_pending():
    """מחיל עדכון שהורד (אם יש): גיבוי הקבצים הנוכחיים ל"גיבוי_גרסאות" ואז החלפה."""
    try:
        with open(PENDING_INFO, encoding='utf-8') as f:
            info = json.load(f)
    except (OSError, ValueError):
        return None
    version, names = str(info['version']), info['files']
    old = current_version()
    dest = os.path.join(BACKUP_DIR, '%s_%s' % (old, time.strftime('%Y-%m-%d_%H-%M')))
    os.makedirs(dest, exist_ok=True)
    for name in names:
        if not safe_name(name):
            continue
        p = os.path.join(APP_DIR, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(dest, name))
    for name in names:
        if not safe_name(name):
            continue
        p = os.path.join(APP_DIR, name)
        tmp = p + '.new'
        shutil.copyfile(os.path.join(PENDING_DIR, name), tmp)
        os.replace(tmp, p)
    shutil.rmtree(PENDING_DIR, ignore_errors=True)
    return {'ok': True, 'version': version, 'old_version': old}



# =====================================================================================
# ספריית אוצריא המקומית - בדיקת מקורות בלי אינטרנט ובלי ספריא
# =====================================================================================
# אוצריא שומרת את כל הספרים במחשב, בקובץ אחד בשם seforim.db (בגרסאות ישנות: תיקיית קבצי txt).
# השרת קורא משם (קריאה בלבד, בלי לשנות כלום) ומחזיר לתוכנה את הטקסט של מקום מבוקש,
# כולל פירוש של מפרש מסוים על המקום. כך הבדיקה עובדת גם אצל מי שספריא חסומה אצלו (נטפרי וכו').

import ctypes
import ctypes.util
import html as _html
import sqlite3
import threading
import urllib.parse

SETTINGS_FILE = os.path.join(APP_DIR, 'torati_settings.json')
OTZ_HEADING_RE = re.compile(r'^\s*<h([1-6])[^>]*>(.*?)</h\1>', re.I | re.S)
OTZ_TAG_RE = re.compile(r'<[^>]+>')
OTZ_NIKUD_RE = re.compile('[\u0591-\u05C7]')
HEB_VALUES = {'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9, 'י': 10,
              'כ': 20, 'ך': 20, 'ל': 30, 'מ': 40, 'ם': 40, 'נ': 50, 'ן': 50, 'ס': 60, 'ע': 70,
              'פ': 80, 'ף': 80, 'צ': 90, 'ץ': 90, 'ק': 100, 'ר': 200, 'ש': 300, 'ת': 400}
QUOTES = '"\'״׳“”‘’`'
# מילים שמסמנות מספור (דף/פרק/סימן...) בכותרות ובמראי מקום
LOC_KEYWORDS = {'דף', 'פרק', 'סימן', 'סעיף', 'הלכה', 'משנה', 'פסוק', 'פרשה', 'אות', 'עמוד', 'שורה',
                'סק', 'מאמר', 'שורש', 'מצוה', 'תשובה', 'פיסקא', 'מזמור', 'שער', 'כלל', 'חלק'}
CHALAKIM = ['אורח חיים', 'יורה דעה', 'אבן העזר', 'חושן משפט']
# ראשי תיבות נפוצים בשמות ספרים -> השם כפי שהוא בכותרות אוצריא
BOOK_ACRONYMS = {'שוע': 'שולחן ערוך', 'שלחן': 'שולחן', 'רמבם': 'משנה תורה', 'מב': 'משנה ברורה',
                 'אוח': 'אורח חיים', 'יוד': 'יורה דעה', 'אהע': 'אבן העזר', 'חומ': 'חושן משפט',
                 'ביהל': 'ביאור הלכה', 'שעהצ': 'שער הציון', 'מגא': 'מגן אברהם', 'טז': 'טורי זהב',
                 'שך': 'שפתי כהן', 'קצוהח': 'קצות החושן', 'נתיבומ': 'נתיבות המשפט', 'ערוהש': 'ערוך השולחן',
                 'ירושלמי': 'תלמוד ירושלמי', 'תוספתא': 'תוספתא'}


def heb_num(token):
    """גימטריה של מספר עברי (ט"ו, קכ"ג, רסב). מחזיר None אם זה לא נראה כמו מספר."""
    t = ''.join(ch for ch in (token or '') if ch not in QUOTES)
    if not t or len(t) > 5 or any(ch not in HEB_VALUES for ch in t):
        return None
    return sum(HEB_VALUES[ch] for ch in t)


def clean_html(s):
    s = OTZ_TAG_RE.sub(' ', s or '')
    s = _html.unescape(s).replace('\u00a0', ' ').replace('\u2009', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def norm_name(s):
    """מאחד כתיב לצורך השוואת שמות: בלי ניקוד, גרשיים, פיסוק וה"א הידיעה בראשי תיבות."""
    s = OTZ_NIKUD_RE.sub('', clean_html(s))
    words = []
    for w in re.split(r'[\s,\-–—_()\[\]:;.]+', s):
        if not w:
            continue
        had_quote = any(q in w for q in QUOTES)
        w2 = ''.join(ch for ch in w if ch not in QUOTES)
        if had_quote and w2.startswith('ה') and len(w2) > 3:
            w2 = w2[1:]
        if w2:
            words.append(BOOK_ACRONYMS.get(w2, w2) if had_quote or w2 in ('שלחן', 'ירושלמי') else w2)
    words = ' '.join(words).split()
    # ה"א הידיעה בתחילת מילה (הגרא/גר"א, החושן/חושן) - מורידים בשני הצדדים של ההשוואה
    return ' '.join(w[1:] if w.startswith('ה') and len(w) > 3 else w for w in words)


def parse_heading(text):
    """'דף ב.' -> ('דף', 2, 'א');  'פרק יב' -> ('פרק', 12, None);  'סימן רסב' -> ('סימן', 262, None)"""
    t = OTZ_NIKUD_RE.sub('', clean_html(text))
    amud = None
    if re.search(r'ע["״]?א\b|עמוד א\b', t):
        amud = 'א'
    elif re.search(r'ע["״]?ב\b|עמוד ב\b', t):
        amud = 'ב'
    elif t.endswith('.'):
        amud = 'א'
    elif t.endswith(':'):
        amud = 'ב'
    words = [w for w in re.split(r'[\s,.:;()\[\]]+', t) if w]
    if not words:
        return None, None, amud
    kw = None
    first = ''.join(ch for ch in words[0] if ch not in QUOTES)
    if first in LOC_KEYWORDS or first in ('סעיף', 'ס'):
        kw = first
        rest = words[1:]
        if rest and rest[0] == 'קטן':
            kw, rest = 'סק', rest[1:]
        n = heb_num(rest[0]) if rest else None
        return kw, n, amud
    if len(words) <= 2:
        return None, heb_num(words[0]), amud
    return None, None, amud


LINE_NUM_RE = re.compile(r'^\s*[\(\[]\s*([א-ת"\'״׳]{1,5})\s*[\)\]]')


def line_number(content):
    """מספר בתחילת שורה: '(ג) וכו'' -> 3"""
    m = LINE_NUM_RE.match(clean_html(content))
    return heb_num(m.group(1)) if m else None


LOC_ABBREVIATIONS = {"סי'": 'סימן', "סימ'": 'סימן', "סע'": 'סעיף', "סעי'": 'סעיף', 'ס"ק': 'סעיף קטן', 'סק"': 'סעיף קטן',
                     "הל'": 'הלכה', "הלכ'": 'הלכה', "פ'": 'פרק', "פר'": 'פרק', "פס'": 'פסוק', "מש'": 'משנה',
                     'או"ח': 'אורח חיים', 'יו"ד': 'יורה דעה', 'אה"ע': 'אבן העזר', 'אבה"ע': 'אבן העזר', 'חו"מ': 'חושן משפט',
                     'ע"א': 'עמוד א', 'ע"ב': 'עמוד ב'}


def expand_abbreviations(text, location=True):
    t = OTZ_NIKUD_RE.sub('', text or '')
    t = t.replace('״', '"').replace('׳', "'").replace('”', '"').replace('“', '"').replace("''", '"')
    t = re.sub(r'([,.:;()])', r' \1 ', t)
    words, out = t.split(), []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ''
        m = re.match(r'^([פהמ])"([א-ת]{1,3})$', w) if location else None
        if w in ("הל'", "הלכ'"):
            num_like = heb_num(nxt) is not None and (any(q in nxt for q in QUOTES) or len(nxt) <= 2)
            out.append('הלכה' if num_like else 'הלכות')
        elif m:   # פ"ב = פרק ב, ה"ג = הלכה ג, מ"א = משנה א
            out.append({'פ': 'פרק', 'ה': 'הלכה', 'מ': 'משנה'}[m.group(1)] + ' ' + m.group(2))
        else:
            out.append(LOC_ABBREVIATIONS.get(w, w))
    return ' '.join(out)


def parse_location(loc):
    """'סימן רסב סעיף קטן ב' -> ([('סימן',262),('סק',2)], 'טקסט שלפני המספרים')"""
    t = expand_abbreviations(loc).replace(' .', '.').replace(' :', ':')
    tokens = [w for w in re.split(r'\s+', t) if w]
    pairs, title_words, i, started = [], [], 0, False
    while i < len(tokens):
        w = tokens[i]
        bare = ''.join(ch for ch in w if ch not in QUOTES).strip('.:')
        if bare in LOC_KEYWORDS or bare in ('ס',):
            kw = bare
            j = i + 1
            if j < len(tokens) and tokens[j] == 'קטן':
                kw, j = 'סק', j + 1
            if j < len(tokens) and heb_num(tokens[j].strip('.:')) is not None:
                amud = 'א' if tokens[j].endswith('.') else ('ב' if tokens[j].endswith(':') else None)
                pairs.append((kw, heb_num(tokens[j].strip('.:')), amud))
                started = True
                i = j + 1
                continue
        if w == ',':
            i += 1
            continue
        n = heb_num(w.strip('.:'))
        if n is not None and (started or any(q in w for q in QUOTES) or len(bare) <= 2):
            amud = 'א' if w.endswith('.') else ('ב' if w.endswith(':') else None)
            pairs.append((None, n, amud))
            started = True
        elif not started:
            title_words.append(w)
        i += 1
    return pairs, ' '.join(title_words)


# ---------- פענוח שורות דחוסות (zstd) - בגרסאות חדשות של אוצריא ----------

class ZstdDecoder:
    """מפענח מסגרות zstd עם המילונים שבמסד. מנסה כמה דרכים, לפי מה שקיים במחשב."""

    def __init__(self, dicts, lib_dirs):
        self.dicts = dicts
        self.impl = None
        self.error = None
        self._lock = threading.Lock()
        for make in (self._py314, self._zstandard, lambda: self._ctypes(lib_dirs)):
            try:
                self.impl = make()
                if self.impl:
                    break
            except Exception as e:  # ממשיכים לדרך הבאה
                self.error = repr(e)

    def _py314(self):
        from compression import zstd  # Python 3.14 ומעלה
        ds = [zstd.ZstdDict(d) for d in self.dicts]

        def dec(frame):
            last = None
            for d in ds:
                try:
                    return zstd.decompress(frame, zstd_dict=d)
                except Exception as e:
                    last = e
            raise last or ValueError('no dict')
        return dec

    def _zstandard(self):
        import zstandard  # אם הותקן (pip install zstandard)
        ds = [zstandard.ZstdDecompressor(dict_data=zstandard.ZstdCompressionDict(d)) for d in self.dicts]

        def dec(frame):
            last = None
            for d in ds:
                try:
                    return d.decompress(frame, max_output_size=16 * 1024 * 1024)
                except Exception as e:
                    last = e
            raise last or ValueError('no dict')
        return dec

    def _ctypes(self, lib_dirs):
        names = ['zstandard_windows.dll', 'libzstd.dll', 'zstd.dll', 'libzstd.so.1', 'libzstd.so',
                 'libzstandard_linux_plugin.so', 'libzstd.dylib', 'libzstd.1.dylib']
        lib = None
        for d in lib_dirs:
            for n in names:
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    try:
                        if hasattr(os, 'add_dll_directory'):
                            try:
                                os.add_dll_directory(d)
                            except OSError:
                                pass
                        lib = ctypes.CDLL(p)
                        break
                    except OSError:
                        continue
            if lib:
                break
        if lib is None:
            found = ctypes.util.find_library('zstd') or ctypes.util.find_library('libzstd')
            if found:
                lib = ctypes.CDLL(found)
        if lib is None:
            return None
        lib.ZSTD_createDCtx.restype = ctypes.c_void_p
        lib.ZSTD_createDDict.restype = ctypes.c_void_p
        lib.ZSTD_createDDict.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.ZSTD_getDictID_fromDDict.restype = ctypes.c_uint
        lib.ZSTD_getDictID_fromDDict.argtypes = [ctypes.c_void_p]
        lib.ZSTD_getDictID_fromFrame.restype = ctypes.c_uint
        lib.ZSTD_getDictID_fromFrame.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
        lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.ZSTD_decompress_usingDDict.restype = ctypes.c_size_t
        lib.ZSTD_decompress_usingDDict.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                                   ctypes.c_char_p, ctypes.c_size_t, ctypes.c_void_p]
        lib.ZSTD_isError.restype = ctypes.c_uint
        lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
        dctx = lib.ZSTD_createDCtx()
        ddicts = {}
        keep = []
        for d in self.dicts:
            keep.append(d)
            dd = lib.ZSTD_createDDict(d, len(d))
            if dd:
                ddicts[lib.ZSTD_getDictID_fromDDict(dd)] = dd
        self._keep = keep

        def dec(frame):
            frame = bytes(frame)
            size = lib.ZSTD_getFrameContentSize(frame, len(frame))
            if size >= 0xFFFFFFFFFFFFFFFE or size > 16 * 1024 * 1024:
                raise ValueError('bad frame')
            did = lib.ZSTD_getDictID_fromFrame(frame, len(frame))
            dd = ddicts.get(did) or (next(iter(ddicts.values())) if len(ddicts) == 1 else None)
            if not dd:
                raise ValueError('missing dict %s' % did)
            out = ctypes.create_string_buffer(max(int(size), 1))
            n = lib.ZSTD_decompress_usingDDict(dctx, out, int(size), frame, len(frame), dd)
            if lib.ZSTD_isError(n):
                raise ValueError('zstd error')
            return out.raw[:n]
        return dec

    def text(self, value):
        if value is None:
            return ''
        if isinstance(value, str):
            return value
        b = bytes(value)
        if b[:4] != b'\x28\xb5\x2f\xfd':
            return b.decode('utf-8', 'replace')
        if not self.impl:
            raise RuntimeError('zstd')
        with self._lock:
            return self.impl(b).decode('utf-8', 'replace')


# ---------- איתור הספרייה במחשב ----------

def load_settings():
    try:
        with open(SETTINGS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data):
    tmp = SETTINGS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SETTINGS_FILE)


def _read_text_file(p):
    try:
        with open(p, encoding='utf-8-sig') as f:
            return f.read().strip()
    except OSError:
        return ''


def _otzaria_exe_dirs():
    """תיקיות שבהן כנראה מותקנת תוכנת אוצריא עצמה (שם יש גם את רכיב הפענוח של zstd)."""
    dirs = []
    if sys.platform.startswith('win'):
        try:
            import winreg
            for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
                try:
                    with winreg.OpenKey(root, r'Software\Classes\otzaria\shell\open\command' if root == winreg.HKEY_CURRENT_USER else r'otzaria\shell\open\command') as k:
                        cmd = winreg.QueryValue(k, None) or ''
                        m = re.match(r'\s*"([^"]+)"|\s*(\S+)', cmd)
                        exe = m and (m.group(1) or m.group(2))
                        if exe:
                            dirs.append(os.path.dirname(exe))
                except OSError:
                    pass
        except ImportError:
            pass
        env = os.environ
        for base in (env.get('LOCALAPPDATA', '') + r'\Programs', env.get('ProgramFiles', ''),
                     env.get('ProgramFiles(x86)', ''), env.get('ProgramW6432', '')):
            if base:
                for name in ('otzaria', 'Otzaria', 'אוצריא'):
                    dirs.append(os.path.join(base, name))
    else:
        dirs += ['/opt/otzaria', '/usr/lib/otzaria', os.path.expanduser('~/otzaria')]
    return [d for d in dirs if d and os.path.isdir(d)]


def _candidate_library_dirs():
    env = os.environ
    cands = []
    s = load_settings().get('otzaria_path')
    if s:
        cands.append(s)
    roots = []
    if sys.platform.startswith('win'):
        appdata = env.get('APPDATA', '')
        roots.append(os.path.join(appdata, 'otzaria'))
        roots.append(os.path.join(env.get('ProgramData', r'C:\ProgramData'), 'otzaria'))
    elif sys.platform == 'darwin':
        roots.append(os.path.expanduser('~/Library/Application Support/otzaria'))
        roots.append('/Library/Application Support/otzaria')
    else:
        roots.append(os.path.expanduser('~/.local/share/otzaria'))
        roots.append('/var/lib/otzaria')
    for r in roots:
        for rec in ('library_database_path.txt', 'library_path.txt'):
            p = _read_text_file(os.path.join(r, rec))
            if p:
                cands.append(p)
        cands.append(os.path.join(r, 'books'))
    # הגדרות שמורות של אוצריא (shared_preferences.json) - שם רשום הנתיב שהמשתמש בחר
    if sys.platform.startswith('win') and env.get('APPDATA'):
        for sub in ('com.example', 'sivan22', 'otzaria', 'com.otzaria', 'Otzaria'):
            base = os.path.join(env['APPDATA'], sub)
            if not os.path.isdir(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                if dirpath.count(os.sep) - base.count(os.sep) > 2:
                    dirnames[:] = []
                    continue
                if 'shared_preferences.json' in filenames:
                    try:
                        with open(os.path.join(dirpath, 'shared_preferences.json'), encoding='utf-8') as f:
                            prefs = json.load(f)
                        for k, v in prefs.items():
                            if isinstance(v, str) and 'library' in k.lower() and 'path' in k.lower():
                                cands.append(v)
                    except (OSError, ValueError):
                        pass
    if sys.platform.startswith('win'):
        for drive in 'CDEFGHIJ':
            for name in ('אוצריא', 'otzaria', 'Otzaria', 'אוצריא\\books', 'otzaria\\books'):
                cands.append('%s:\\%s' % (drive, name))
    home = os.path.expanduser('~')
    for name in ('אוצריא', 'otzaria', 'Otzaria'):
        cands += [os.path.join(home, name), os.path.join(home, 'Documents', name), os.path.join(home, 'Desktop', name)]
    for d in _otzaria_exe_dirs():
        cands += [os.path.join(d, 'אוצריא'), os.path.join(d, 'books'), d]
    seen, out = set(), []
    for c in cands:
        c = (c or '').strip().strip('"')
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def find_library(path=None):
    """מחזיר ('db', נתיב_לקובץ) או ('txt', תיקיית_אוצריא) או (None, None)."""
    for c in ([path] if path else _candidate_library_dirs()):
        if not c:
            continue
        if os.path.isfile(c) and c.lower().endswith('.db'):
            return 'db', c
        if not os.path.isdir(c):
            continue
        for sub in ('', 'אוצריא', 'books', 'Otzaria', 'otzaria', 'ספרייה'):
            d = os.path.join(c, sub) if sub else c
            p = os.path.join(d, 'seforim.db')
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return 'db', p
        for sub in ('אוצריא', ''):
            d = os.path.join(c, sub) if sub else c
            if os.path.isdir(d) and any(os.path.isdir(os.path.join(d, x)) for x in ('תלמוד בבלי', 'תנך', 'תלמוד', 'הלכה')):
                return 'txt', d
    return None, None


# ---------- הספרייה עצמה ----------

class OtzariaLibrary:
    def __init__(self, kind, path):
        self.kind, self.path = kind, path
        self.books = []          # [{id, title, norm, cats(str), lines?, file?}]
        self.cache = {}          # bookKey -> (lines, headings)
        self.cache_order = []
        self.lock = threading.Lock()
        self.decoder = None
        self.split = False
        self.compressed = False
        self.db = None
        if kind == 'db':
            self._open_db()
        else:
            self._scan_txt()
        by_title = {}
        for b in self.books:
            b['norm'] = norm_name(b['title'])
            b['words'] = set(b['norm'].split())
            by_title.setdefault(b['norm'], []).append(b)
        self.by_title = by_title

    # --- מסד הנתונים ---
    def _connect(self):
        uri_path = urllib.parse.quote(os.path.abspath(self.path).replace('\\', '/'))
        if not uri_path.startswith('/'):
            uri_path = '/' + uri_path
        last = None
        for mode in ('ro', 'ro&immutable=1'):
            try:
                db = sqlite3.connect('file:%s?mode=%s' % (uri_path, mode), uri=True, check_same_thread=False, timeout=10)
                db.execute('SELECT 1 FROM book LIMIT 1').fetchall()
                return db
            except sqlite3.Error as e:
                last = e
        raise last

    def _open_db(self):
        self.db = self._connect()
        tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.tables = tables
        self.split = 'line_content' in tables
        if 'zstd_dict' in tables:
            dicts = [bytes(r[0]) for r in self.db.execute('SELECT dict FROM zstd_dict ORDER BY id')]
            self.compressed = bool(dicts)
            lib_dirs = _otzaria_exe_dirs() + [os.path.dirname(self.path), os.path.dirname(os.path.dirname(self.path)), APP_DIR]
            self.decoder = ZstdDecoder(dicts, lib_dirs)
        else:
            self.decoder = ZstdDecoder([], [])
        cats = {}
        if 'category' in tables:
            for cid, parent, title in self.db.execute('SELECT id, parentId, title FROM category'):
                cats[cid] = (parent, title)

        def cat_path(cid):
            out, guard = [], 0
            while cid in cats and guard < 30:
                parent, title = cats[cid]
                out.append(title or '')
                cid, guard = parent, guard + 1
            return '/'.join(reversed(out))
        cols = {r[1] for r in self.db.execute('PRAGMA table_info(book)')}
        sel = 'id, title, categoryId' + (', filePath' if 'filePath' in cols else ', NULL') + (', totalLines' if 'totalLines' in cols else ', 1')
        cat_cache = {}
        for bid, title, cid, fpath, total in self.db.execute('SELECT %s FROM book' % sel):
            if cid not in cat_cache:
                cat_cache[cid] = cat_path(cid)
            if fpath and not str(fpath).lower().endswith('.txt') and not total:
                continue  # PDF/Word וכו' - אין טקסט לבדוק
            self.books.append({'id': bid, 'title': title or '', 'cats': cat_cache[cid], 'file': fpath})

    def _db_lines(self, book):
        if self.split:
            q = ('SELECT l.lineIndex, lc.content FROM line l LEFT JOIN line_content lc ON lc.id = l.id '
                 'WHERE l.bookId = ? ORDER BY l.lineIndex')
        else:
            q = 'SELECT lineIndex, content FROM line WHERE bookId = ? ORDER BY lineIndex'
        with self.lock:
            rows = self.db.execute(q, (book['id'],)).fetchall()
        lines = [self.decoder.text(c) for _, c in rows]
        if not lines and book.get('file') and os.path.isfile(book['file']):
            with open(book['file'], encoding='utf-8-sig', errors='replace') as f:
                lines = f.read().split('\n')
        return lines, [i for i, _ in rows] if rows else list(range(len(lines)))

    def _db_toc(self, book):
        if 'tocEntry' not in self.tables or 'tocText' not in self.tables:
            return []
        with self.lock:
            rows = self.db.execute('SELECT e.level, t.text, e.lineIndex FROM tocEntry e JOIN tocText t ON t.id = e.textId '
                                   'WHERE e.bookId = ? AND e.lineIndex IS NOT NULL ORDER BY e.lineIndex', (book['id'],)).fetchall()
        return rows

    def line_ids(self, book, start, end):
        with self.lock:
            return [r[0] for r in self.db.execute('SELECT id FROM line WHERE bookId = ? AND lineIndex >= ? AND lineIndex < ?',
                                                  (book['id'], start, end))]

    # --- ספרייה ישנה של קבצי טקסט ---
    def _scan_txt(self):
        for dirpath, dirnames, filenames in os.walk(self.path):
            rel = os.path.relpath(dirpath, self.path)
            for fn in filenames:
                if fn.lower().endswith('.txt'):
                    self.books.append({'id': None, 'title': fn[:-4], 'cats': rel.replace('\\', '/'),
                                       'file': os.path.join(dirpath, fn)})

    # --- טעינת ספר: שורות + כותרות ---
    def load(self, book):
        key = book['id'] if book['id'] is not None else book['file']
        if key in self.cache:
            return self.cache[key]
        if self.kind == 'db':
            lines, idx = self._db_lines(book)
        else:
            with open(book['file'], encoding='utf-8-sig', errors='replace') as f:
                lines = f.read().split('\n')
            idx = list(range(len(lines)))
        heads = []
        for pos, content in enumerate(lines):
            m = OTZ_HEADING_RE.match(content or '')
            if m:
                txt = clean_html(m.group(2))
                if txt:
                    heads.append({'level': int(m.group(1)), 'text': txt, 'pos': pos})
        if not heads and self.kind == 'db':
            # כותרות לא נשמרו כשורות - לוקחים מתוכן העניינים של המסד
            where = {li: p for p, li in enumerate(idx)}
            for level, text, li in self._db_toc(book):
                if li in where:
                    heads.append({'level': int(level), 'text': clean_html(text), 'pos': where[li]})
        for h in heads:
            h['kw'], h['num'], h['amud'] = parse_heading(h['text'])
        data = {'lines': lines, 'idx': idx, 'heads': heads}
        self.cache[key] = data
        self.cache_order.append(key)
        if len(self.cache_order) > 12:
            self.cache.pop(self.cache_order.pop(0), None)
        return data

    # --- חיפוש ספר לפי שם ---
    def find_books(self, name, cats_need=None, cats_avoid=None, allow_commentary=False, limit=8):
        n = norm_name(name)
        if not n:
            return []
        words = n.split()
        out = []
        for b in self.books:
            if cats_need and not any(c in b['cats'] for c in cats_need):
                continue
            if cats_avoid and any(c in b['cats'] for c in cats_avoid):
                continue
            if b['norm'] == n:
                score = 0
            elif all(w in b['words'] for w in words):
                score = 1 + len(b['words']) - len(words)
                if not allow_commentary and ' על ' in ' %s ' % b['norm'] and 'על' not in words:
                    score += 20
            else:
                continue
            out.append((score, len(b['title']), b))
        out.sort(key=lambda x: (x[0], x[1]))
        return [b for _, _, b in out[:limit]]

    # --- מעבר בתוך ספר לפי מספרים (דף/עמוד, פרק/פסוק, סימן/סעיף) ---
    @staticmethod
    def _section_end(data, hi):
        heads = data['heads']
        h = heads[hi]
        for k in range(hi + 1, len(heads)):
            if heads[k]['level'] <= h['level']:
                return heads[k]['pos']
        return len(data['lines'])

    def navigate(self, data, pairs):
        """pairs: [(kw, num, amud)...]. מחזיר (start, end, exact, labels) או None."""
        heads = data['heads']
        start, end, labels = 0, len(data['lines']), []
        lo_level = 0
        exact = True
        for i, (kw, num, amud) in enumerate(pairs):
            if num is None:
                continue
            inside = [k for k, h in enumerate(heads) if start <= h['pos'] < end and h['level'] > lo_level and h['num'] == num]
            if kw:
                same_kw = [k for k in inside if heads[k]['kw'] == kw or (kw == 'סק' and heads[k]['kw'] in ('סעיף', 'סק'))]
                no_kw = [k for k in inside if not heads[k]['kw']]
                # פרשה/פרק, סימן/פרק וכו' - אם אין התאמה מדויקת למילה, מסתפקים במספר עצמו
                inside = same_kw or no_kw or inside
            if amud:
                exact_amud = [k for k in inside if heads[k]['amud'] == amud]
                if exact_amud:
                    inside = exact_amud
                elif inside and all(heads[k]['amud'] for k in inside):
                    inside = []   # יש רק את העמוד השני - המקום לא קיים בצורה הזו
            if inside:
                best = min(inside, key=lambda k: (heads[k]['level'], heads[k]['pos']))
                h = heads[best]
                start, end = h['pos'], self._section_end(data, best)
                lo_level = h['level']
                labels.append(h['text'])
                if amud and not h['amud']:
                    # הדף שלם בכותרת אחת - מחפשים בתוכו כותרת משנה של עמוד
                    sub = [k for k, x in enumerate(heads) if start < x['pos'] < end and x['amud'] == amud]
                    if sub:
                        s = heads[sub[0]]
                        start, end = s['pos'], self._section_end(data, sub[0])
                        lo_level = s['level']
                        labels.append(s['text'])
                continue
            if i == 0:
                return None
            # מספר שאין לו כותרת - מחפשים שורה שמתחילה ב-(ג) וכדומה
            line_hits = [p for p in range(start, end) if line_number(data['lines'][p]) == num]
            if line_hits:
                p0 = line_hits[0]
                p1 = end
                for p in range(p0 + 1, end):
                    if line_number(data['lines'][p]) is not None or OTZ_HEADING_RE.match(data['lines'][p] or ''):
                        p1 = p
                        break
                start, end = p0, p1
                labels.append('(%s)' % num)
                break
            exact = False
            break
        if not labels:
            return None
        return start, end, exact, labels

    @staticmethod
    def segments(data, start, end):
        segs = []
        for p in range(start, end):
            c = data['lines'][p] or ''
            if OTZ_HEADING_RE.match(c):
                continue
            t = clean_html(c)
            if t:
                segs.append(t)
        return segs

    def open_url(self, book, data, start):
        if self.kind != 'db' or book.get('id') is None:
            return ''
        try:
            li = data['idx'][start]
        except (IndexError, KeyError):
            li = start
        return 'otzaria://open/book/%s?index=%s' % (book['id'], li)


# ---------- מראה מקום (כפי שהתוכנה שולחת) -> ספר + מספרים ----------

def ref_to_target(ref):
    """מחזיר (שם_ספר, רשימת_מספרים, קטגוריות_חובה, קטגוריות_להימנע)"""
    cat = ref.get('category')
    book = (ref.get('book') or '').strip()
    if cat == 'shas' and ref.get('daf'):
        amud = ref.get('amud') or None
        return book, [('דף', heb_num(ref.get('daf')), amud if amud in ('א', 'ב') else None)], ['בבלי'], ['ירושלמי']
    if cat == 'chumash' and ref.get('perek'):
        pairs = [('פרק', heb_num(ref.get('perek')), None)]
        if ref.get('pasuk'):
            pairs.append(('פסוק', heb_num(ref.get('pasuk')), None))
        return book, pairs, ['תנ'], None
    loc = expand_abbreviations(ref.get('location') or '')
    book = expand_abbreviations(book, location=False)
    for ch in CHALAKIM:
        if ch in loc and ch not in book:
            book = '%s %s' % (book, ch)
            loc = loc.replace(ch, ' ')
    pairs, title_part = parse_location(loc)
    if title_part:
        book = '%s %s' % (book, title_part)
    return book, pairs, None, None


class OtzariaService:
    def __init__(self):
        self.lib = None
        self.error = None
        self.lock = threading.Lock()

    def get(self, reload=False):
        with self.lock:
            if self.lib is not None and not reload:
                return self.lib
            self.lib, self.error = None, None
            kind, path = find_library()
            if not kind:
                self.error = 'not_found'
                return None
            try:
                self.lib = OtzariaLibrary(kind, path)
            except Exception as e:
                self.error = 'open_failed: %r' % (e,)
                print('Otzaria library open failed:', repr(e))
            return self.lib

    def status(self, reload=False):
        lib = self.get(reload)
        if not lib:
            return {'ok': True, 'available': False, 'error': self.error,
                    'configured': load_settings().get('otzaria_path') or ''}
        st = {'ok': True, 'available': True, 'kind': lib.kind, 'path': lib.path, 'books': len(lib.books),
              'configured': load_settings().get('otzaria_path') or ''}
        if lib.compressed and not lib.decoder.impl:
            st['available'] = False
            st['error'] = 'zstd_missing'
        return st

    def set_path(self, path):
        s = load_settings()
        path = (path or '').strip().strip('"')
        if path:
            kind, found = find_library(path)
            if not kind:
                return {'ok': False, 'error': 'לא נמצאה ספריית אוצריא בתיקייה הזו'}
        s['otzaria_path'] = path
        save_settings(s)
        return self.status(reload=True)

    # --- טקסט של מקום ---
    def _resolve(self, lib, ref):
        name, pairs, need, avoid = ref_to_target(ref)
        if not name or not pairs:
            return None, None, name
        books = lib.find_books(name, need, avoid)
        if not books and need:
            books = lib.find_books(name, None, avoid)
        for b in books[:4]:
            data = lib.load(b)
            nav = lib.navigate(data, pairs)
            if nav:
                return b, (data, nav), name
        return (books[0] if books else None), None, name

    def text(self, ref):
        lib = self.get()
        if not lib:
            return {'ok': False, 'unavailable': True}
        book, hit, name = self._resolve(lib, ref)
        if not book:
            return {'ok': True, 'found': False, 'bookFound': False, 'query': name}
        if not hit:
            return {'ok': True, 'found': False, 'bookFound': True, 'title': book['title']}
        data, (start, end, exact, labels) = hit
        segs = lib.segments(data, start, end)[:400]
        return {'ok': True, 'found': bool(segs), 'exact': exact, 'bookFound': True, 'title': book['title'],
                'label': '%s %s' % (book['title'], ' '.join(labels)), 'segments': segs,
                'url': lib.open_url(book, data, start)}

    # --- פירוש של מפרש על מקום ---
    def commentary(self, ref, names):
        lib = self.get()
        if not lib:
            return {'ok': False, 'unavailable': True}
        base_book, hit, _ = self._resolve(lib, ref)
        if not base_book or not hit:
            return {'ok': True, 'found': False, 'baseFound': bool(hit)}
        name_keys = []
        for n in names or []:
            k = norm_name(n)
            if k and k not in name_keys:
                name_keys.append(k)
            k2 = re.sub(r'^(חידושי|חדושי|פירוש|ביאור|גהות) ', '', k)
            if k2 and k2 not in name_keys:
                name_keys.append(k2)
        base_words = set(base_book['norm'].split())
        name, pairs, _, _ = ref_to_target(ref)

        def title_matches(b):
            t = b['norm']
            for k in name_keys:
                if t == k or t.startswith(k + ' '):
                    return True
            return False

        # 1) ספר המפרש לפי שם ("רש"י על ברכות", "תוספות על ברכות") - ומעבר לאותו מקום בתוכו
        cands = []
        for b in lib.books:
            if b is base_book or not title_matches(b):
                continue
            if base_words <= b['words']:
                cands.append((len(b['words']), b))
        if not cands:
            # מפרש שספרו נקרא רק בשמו ("מגן אברהם") ונמצא באותו מדור כמו הספר (שולחן ערוך/מפרשים)
            base_cat = base_book['cats'].rstrip('/')
            for b in lib.books:
                if b is not base_book and title_matches(b) and base_cat and b['cats'].startswith(base_cat):
                    cands.append((50 + len(b['words']), b))
        cands.sort(key=lambda x: x[0])
        for _, b in cands[:4]:
            data = lib.load(b)
            nav = lib.navigate(data, pairs)
            if nav:
                start, end, exact, labels = nav
                segs = lib.segments(data, start, end)[:400]
                if segs:
                    return {'ok': True, 'found': True, 'title': b['title'], 'segments': segs,
                            'url': lib.open_url(b, data, start), 'exact': exact}
        # 2) לפי הקישורים שבמסד: אילו מפרשים מקושרים לשורות של המקום הזה
        if lib.kind == 'db' and 'link' in lib.tables:
            data, (start, end, exact, labels) = hit
            s_li = data['idx'][start] if start < len(data['idx']) else start
            e_li = data['idx'][end - 1] + 1 if 0 < end <= len(data['idx']) else end
            ids = lib.line_ids(base_book, s_li, e_li)
            if ids:
                found = {}
                with lib.lock:
                    for chunk_start in range(0, len(ids), 400):
                        chunk = ids[chunk_start:chunk_start + 400]
                        ph = ','.join('?' * len(chunk))
                        q = ('SELECT l.targetBookId, l.targetLineId FROM link l WHERE l.sourceLineId IN (%s) '
                             'UNION SELECT l.sourceBookId, l.sourceLineId FROM link l WHERE l.targetLineId IN (%s)') % (ph, ph)
                        for bid, lid in lib.db.execute(q, chunk + chunk):
                            found.setdefault(bid, set()).add(lid)
                by_id = {b['id']: b for b in lib.books}
                groups = [(by_id[bid], lids) for bid, lids in found.items() if bid in by_id and title_matches(by_id[bid])]
                groups.sort(key=lambda g: len(g[0]['title']))
                if groups:
                    b, lids = groups[0]
                    lids = sorted(lids)[:300]
                    ph = ','.join('?' * len(lids))
                    if lib.split:
                        q = ('SELECT l.lineIndex, lc.content FROM line l LEFT JOIN line_content lc ON lc.id = l.id '
                             'WHERE l.id IN (%s) ORDER BY l.lineIndex') % ph
                    else:
                        q = 'SELECT lineIndex, content FROM line WHERE id IN (%s) ORDER BY lineIndex' % ph
                    with lib.lock:
                        rows = lib.db.execute(q, lids).fetchall()
                    segs = [clean_html(lib.decoder.text(c)) for _, c in rows]
                    segs = [s for s in segs if s]
                    if segs:
                        return {'ok': True, 'found': True, 'title': b['title'], 'segments': segs,
                                'url': 'otzaria://open/book/%s?index=%s' % (b['id'], rows[0][0])}
        return {'ok': True, 'found': False, 'baseFound': True}


OTZARIA = OtzariaService()


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
            return self._json(200, {'ok': True, 'updater': 2, 'otzaria': 1, 'version': current_version(), 'pending': pending_version()})
        if self.path.startswith('/__torati/otzaria/status'):
            try:
                return self._json(200, OTZARIA.status(reload='reload=1' in self.path))
            except Exception as e:
                return self._json(200, {'ok': True, 'available': False, 'error': repr(e)})
        return super().do_GET()

    def do_HEAD(self):
        if self._local_only():
            super().do_HEAD()

    def do_POST(self):
        if not self._local_only():
            return
        # הכותרת המיוחדת מונעת מאתרים אחרים בדפדפן להפעיל עדכון בלי ידיעת המשתמש
        if self.headers.get('X-Torati') != '1':
            return self.send_error(403)
        try:
            if self.path.startswith('/__torati/download'):
                length = int(self.headers.get('Content-Length') or 0)
                req = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
                url = req.get('url') or DEFAULT_UPDATE_URL
                if not url.startswith('https://'):
                    raise ValueError('כתובת עדכון לא חוקית')
                result = download_update(url)
                print('Update %s downloaded, will be applied on next start' % result['version'])
            elif self.path.startswith('/__torati/stage'):
                # כשהשרת לא מצליח להוריד בעצמו (למשל תוכנת הגנה שחוסמת את פייתון), הדפדפן מוריד
                # את הקבצים בעצמו ושולח אותם לכאן; הבדיקות והשמירה זהות להורדה רגילה
                length = int(self.headers.get('Content-Length') or 0)
                if length <= 0 or length > 80 * 1024 * 1024:
                    raise ValueError('בקשה לא תקינה')
                req = json.loads(self.rfile.read(length).decode('utf-8'))
                files = {str(k): base64.b64decode(v) for k, v in (req.get('files') or {}).items()}
                if not files:
                    raise ValueError('לא התקבלו קבצים')
                result = stage_update(str(req.get('version') or ''), files)
                print('Update %s received from the app, will be applied on next start' % result['version'])
            elif self.path.startswith('/__torati/otzaria/'):
                length = int(self.headers.get('Content-Length') or 0)
                req = json.loads(self.rfile.read(length).decode('utf-8') or '{}') if length else {}
                if self.path.startswith('/__torati/otzaria/text'):
                    result = OTZARIA.text(req.get('ref') or {})
                elif self.path.startswith('/__torati/otzaria/commentary'):
                    result = OTZARIA.commentary(req.get('ref') or {}, req.get('names') or [])
                elif self.path.startswith('/__torati/otzaria/path'):
                    result = OTZARIA.set_path(req.get('path') or '')
                else:
                    return self.send_error(404)
                return self._json(200, result)
            elif self.path.startswith('/__torati/apply'):
                result = apply_pending() or {'ok': False, 'error': 'אין עדכון ממתין'}
                if result.get('ok'):
                    print('Updated to version', result['version'])
            else:
                return self.send_error(404)
            self._json(200 if result.get('ok') else 409, result)
        except Exception as e:
            print('Request failed (%s):' % self.path.split('?')[0], repr(e))
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
    # עדכון שהורד בפעם הקודמת מוחל עכשיו, לפני שהתוכנה נפתחת
    try:
        done = apply_pending()
        if done:
            print('Updated to version', done['version'])
    except Exception as e:
        print('Applying update failed:', repr(e))
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
