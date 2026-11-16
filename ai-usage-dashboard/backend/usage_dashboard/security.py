"""Local app authentication only. Never reads supplier auth files."""
import hashlib
import hmac
import re
import secrets
import threading
from urllib.parse import urlsplit

from .common import APIError, iso, now_ms
from .store import insert


def digest(secret):
    return hashlib.sha256(('session-v1:'+secret).encode()).hexdigest()


def csrf(secret):
    return hmac.new(secret.encode(),b'aud-csrf-v1',hashlib.sha256).hexdigest()


class Auth:
    def __init__(self,origin,dev_origin=None,bearer=None,clock=now_ms):
        self.origin,self.clock = origin,clock
        self.origins = {origin}
        if dev_origin:
            parsed = urlsplit(dev_origin)
            if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError('Dev origin must be an exact http://127.0.0.1:PORT origin')
            self.origins.add(dev_origin)
        if bearer is not None and not re.fullmatch(r'aud_[A-Za-z0-9_-]{32,128}',bearer):
            raise ValueError('Use a dedicated aud_ local application token, not a supplier credential')
        self.bearer_digest = hashlib.sha256(bearer.encode()).digest() if bearer else None
        self.lock = threading.Lock()
        self.pairing_code = secrets.token_urlsafe(24)
        self.pairing_digest = hashlib.sha256(self.pairing_code.encode()).digest()
        self.pairing_created = clock()
        self.pairing_used = False
        self.attempts = []

    def check_host_origin(self,headers):
        if headers.get('host')!=urlsplit(self.origin).netloc:
            raise APIError(403,'forbidden_host','Request Host is not allowed')
        if 'origin' in headers and headers['origin'] not in self.origins:
            raise APIError(403,'forbidden_origin','Request Origin is not allowed')

    def browser_origin(self,headers,unsafe=False):
        origin = headers.get('origin')
        if origin is not None:
            if origin in self.origins:
                return origin
            raise APIError(403,'forbidden_origin','Request Origin is not allowed')
        if unsafe:
            raise APIError(403,'forbidden_origin','Origin required for browser writes')
        referer = headers.get('referer')
        if referer:
            value = urlsplit(referer)
            candidate = value.scheme+'://'+value.netloc
            if candidate in self.origins and not value.username:
                return candidate
            raise APIError(403,'forbidden_origin','Referer is not same origin')
        if headers.get('sec-fetch-site')=='same-origin':
            return self.origin
        raise APIError(403,'forbidden_origin','Same-origin browser context required')

    def pair(self,db,headers,body):
        origin = self.browser_origin(headers,True)
        if headers.get('x-dashboard-pairing')!='1':
            raise APIError(403,'forbidden_origin','Pairing request header required')
        now = self.clock()
        with self.lock:
            self.attempts = [t for t in self.attempts if t>now-300000]
            if len(self.attempts)>=5:
                wait = max(1,(self.attempts[0]+300000-now+999)//1000)
                raise APIError(429,'too_many_attempts','Pairing temporarily rate limited',headers={'Retry-After':str(wait)})
            self.attempts.append(now)
            value = body.get('pairing_code') if isinstance(body,dict) else None
            if not isinstance(body,dict) or set(body)!={'pairing_code'} or not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{22,128}',value):
                raise APIError(422,'invalid_body','Invalid pairing body')
            valid = hmac.compare_digest(hashlib.sha256(value.encode()).digest(),self.pairing_digest)
            if self.pairing_used or now-self.pairing_created>=300000 or not valid:
                raise APIError(401,'pairing_invalid','Pairing code invalid or expired')
            secret = secrets.token_urlsafe(32)
            expires = now+604800000
            insert(db,'app_sessions',{'id':'session_'+secrets.token_hex(16),'token_digest':digest(secret),
                'origin':origin,'created_ms':now,'last_seen_ms':now,'expires_ms':expires})
            self.pairing_used = True
        return self.session_data(secret,expires),{'Set-Cookie':'aud_session='+secret+'; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=604800'}

    def authenticate(self,db,headers,method,cookie_only=False):
        cookie = None
        for entry in headers.get('cookie','').split(';'):
            key,sep,value = entry.strip().partition('=')
            if sep and key=='aud_session':
                if cookie is not None:
                    raise APIError(401,'unauthorized','Duplicate session cookie')
                cookie = value
        authorization = headers.get('authorization')
        if cookie is not None and authorization is not None:
            raise APIError(401,'unauthorized','Use one authentication method')
        if authorization is not None:
            scheme,sep,token = authorization.partition(' ')
            valid = (scheme.lower()=='bearer' and sep and self.bearer_digest is not None and
                hmac.compare_digest(hashlib.sha256(token.encode()).digest(),self.bearer_digest))
            if cookie_only or not valid:
                raise APIError(401,'unauthorized','Local application authentication required')
            return None
        if cookie is None or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}',cookie):
            raise APIError(401,'unauthorized','Pair this browser with the local application')
        origin = self.browser_origin(headers,method in ('POST','PATCH','DELETE'))
        now = self.clock()
        row = db.execute('SELECT * FROM app_sessions WHERE token_digest=?',(digest(cookie),)).fetchone()
        if row is None or row['origin']!=origin or row['revoked_ms'] is not None or row['expires_ms']<=now or row['last_seen_ms']<=now-86400000:
            raise APIError(401,'unauthorized','Application session invalid or expired',headers={
                'Set-Cookie':'aud_session=; HttpOnly; SameSite=Strict; Path=/api/v1; Max-Age=0'})
        submitted_csrf = headers.get('x-csrf-token','')
        if method in ('POST','PATCH','DELETE') and (not re.fullmatch(r'[0-9a-f]{64}',submitted_csrf) or not hmac.compare_digest(submitted_csrf,csrf(cookie))):
            raise APIError(403,'csrf_invalid','Valid CSRF header required')
        db.execute('UPDATE app_sessions SET last_seen_ms=MAX(last_seen_ms,?) WHERE id=?',(now,row['id']))
        return row,cookie

    @staticmethod
    def session_data(secret,expires):
        return {'authenticated':True,'auth_mode':'cookie_session','csrf_token':csrf(secret),
                'expires_at':iso(expires),'idle_timeout_seconds':86400}
