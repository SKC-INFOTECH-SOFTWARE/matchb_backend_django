# api/utils.py
import jwt
import bcrypt
from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework import status

def custom_exception_handler(exc, context):
    """Custom exception handler for REST framework"""
    response = Response({
        'error': str(exc),
        'details': getattr(exc, 'detail', None)
    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    return response

def get_token_from_request(request):
    """Extract JWT token from Authorization header"""
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.replace('Bearer ', '')
    return None

def verify_token(token):
    """Verify JWT token and return decoded data"""
    try:
        decoded = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return decoded
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def hash_password(password):
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(password, hashed):
    """Verify password against hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False

def create_jwt_token(user_data):
    """Create JWT token"""
    import datetime
    payload = {
        'userId': user_data['id'],
        'email': user_data.get('email'),
        'role': user_data.get('role', 'user'),
        'type': user_data.get('role', 'user'),
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token

# Decorators
def require_auth(f):
    """Decorator to require authentication"""
    @wraps(f)
    def decorated_function(request, *args, **kwargs):
        token = get_token_from_request(request)
        if not token:
            return JsonResponse({'error': 'No token provided'}, status=401)

        decoded = verify_token(token)
        if not decoded:
            return JsonResponse({'error': 'Invalid token'}, status=401)

        request.user_data = decoded
        return f(request, *args, **kwargs)
    return decorated_function

def require_admin(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(request, *args, **kwargs):
        token = get_token_from_request(request)
        if not token:
            return JsonResponse({'error': 'No token provided'}, status=401)

        decoded = verify_token(token)
        if not decoded:
            return JsonResponse({'error': 'Invalid token'}, status=401)

        if decoded.get('role') != 'admin':
            return JsonResponse({'error': 'Admin access required'}, status=403)

        request.user_data = decoded
        return f(request, *args, **kwargs)
    return decorated_function

def require_user(f):
    """Decorator to require user role"""
    @wraps(f)
    def decorated_function(request, *args, **kwargs):
        token = get_token_from_request(request)
        if not token:
            return JsonResponse({'error': 'No token provided'}, status=401)

        decoded = verify_token(token)
        if not decoded:
            return JsonResponse({'error': 'Invalid token'}, status=401)

        if decoded.get('role') != 'user':
            return JsonResponse({'error': 'User access required'}, status=403)

        request.user_data = decoded
        return f(request, *args, **kwargs)
    return decorated_function
