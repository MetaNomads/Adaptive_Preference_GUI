# backend/auth.py
from functools import wraps
from flask import request, jsonify
import os, time, json, base64, hmac, hashlib

ALG = 'HS256'

def _get_secret()->bytes:
    s = os.environ.get('ADAPTIVE_PREF_JWT_SECRET', 'dev-secret')
    return s.encode('utf-8')

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def _b64url_decode(data: str) -> bytes:
    padding = '=' * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + padding)

def _sign(msg: bytes, secret: bytes) -> str:
    return _b64url(hmac.new(secret, msg, hashlib.sha256).digest())

def jwt_encode(payload: dict, exp_seconds: int = 3600) -> str:
    header = {'alg': ALG, 'typ': 'JWT'}
    payload = dict(payload)
    payload.setdefault('iat', int(time.time()))
    payload.setdefault('exp', int(time.time()) + exp_seconds)
    header_b64 = _b64url(json.dumps(header, separators=(',',':')).encode())
    payload_b64 = _b64url(json.dumps(payload, separators=(',',':')).encode())
    secret = _get_secret()
    sig = _sign(f'{header_b64}.{payload_b64}'.encode(), secret)
    return f'{header_b64}.{payload_b64}.{sig}'

def jwt_decode(token: str) -> dict:
    try:
        header_b64, payload_b64, sig = token.split('.')
    except ValueError:
        raise ValueError('Malformed token')
    secret = _get_secret()
    expected = _sign(f'{header_b64}.{payload_b64}'.encode(), secret)
    if not hmac.compare_digest(sig, expected):
        raise ValueError('Invalid signature')
    payload = json.loads(_b64url_decode(payload_b64))
    now = int(time.time())
    if payload.get('exp') and now > payload['exp']:
        raise ValueError('Token expired')
    return payload

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get('Authorization','')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Missing bearer token'}), 401
        token = auth.split(' ',1)[1].strip()
        try:
            payload = jwt_decode(token)
        except Exception as e:
            return jsonify({'error': f'Invalid token: {e}'}), 401
        request.user = payload
        return f(*args, **kwargs)
    return wrapper

def require_roles(roles):
    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(request, 'user', None)
            if not user or user.get('role') not in roles:
                return jsonify({'error': 'Forbidden'}), 403
            return f(*args, **kwargs)
        return wrapper
    return deco

def jwt_issue_pair_token(payload: dict, exp_seconds: int = 6*3600) -> str:
    required = ['session_id','trial_number','stimulus_a_id','stimulus_b_id','presentation_order']
    for k in required:
        if k not in payload: raise ValueError(f'missing {k}')
    payload = dict(payload)
    payload['kind'] = 'pair_token'
    payload['ts'] = int(time.time())
    return jwt_encode(payload, exp_seconds)

def jwt_decode_pair_token(token: str) -> dict:
    payload = jwt_decode(token)
    if payload.get('kind') != 'pair_token':
        raise ValueError('wrong token kind')
    return payload

