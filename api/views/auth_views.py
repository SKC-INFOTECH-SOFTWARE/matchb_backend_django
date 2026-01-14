import json
import re
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from api.utils import hash_password, verify_password, create_jwt_token, verify_token, get_token_from_request
from api.db_utils import execute_query, execute_insert

@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    """
    User Registration API
    POST /api/auth/register
    Body: { email, password, name, phone }
    """
    try:
        data = json.loads(request.body)
        email = data.get('email')
        password = data.get('password')
        name = data.get('name')
        phone = data.get('phone')

        # Validate inputs
        if not all([email, password, name, phone]):
            return JsonResponse({'error': 'All fields are required'}, status=400)

        if len(password) < 6:
            return JsonResponse({'error': 'Password must be at least 6 characters'}, status=400)

        phone_regex = r'^\+?[\d\s\-\(\)]{10,}$'
        if not re.match(phone_regex, phone.strip()):
            return JsonResponse({'error': 'Invalid phone number format'}, status=400)

        # Check if user exists
        existing_users = execute_query(
            "SELECT id FROM users WHERE email = %s OR phone = %s",
            [email, phone]
        )

        if existing_users:
            return JsonResponse({
                'error': 'User with this email or phone number already exists'
            }, status=409)

        # Hash password
        hashed_password = hash_password(password)

        # Generate recovery password
        import random
        import string
        recovery_password = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))

        # Create user
        user_id = execute_insert(
            """INSERT INTO users
               (name, email, phone, password, recovery_password, role, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
            [name, email, phone, hashed_password, recovery_password, 'user']
        )

        # Create JWT token
        token = create_jwt_token({
            'id': user_id,
            'email': email,
            'phone': phone,
            'role': 'user'
        })

        return JsonResponse({
            'token': token,
            'user': {
                'id': user_id,
                'email': email,
                'name': name,
                'phone': phone,
                'role': 'user',
                'profileComplete': False
            }
        })

    except Exception as e:
        print(f"Registration error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    """
    User/Admin Login API
    POST /api/auth/login
    Body: { identifier, password, type }
    """
    try:
        data = json.loads(request.body)
        identifier = data.get('identifier')
        password = data.get('password')
        login_type = data.get('type')

        if not all([identifier, password, login_type]):
            return JsonResponse({
                'error': 'Identifier, password, and type are required'
            }, status=400)

        # Build query based on login type
        if login_type == 'admin':
            query = """SELECT * FROM users
                      WHERE (email = %s OR phone = %s OR name = %s)
                      AND status = 'active' AND role = 'admin'"""
            params = [identifier, identifier, identifier]
        else:
            query = """SELECT * FROM users
                      WHERE (email = %s OR phone = %s)
                      AND status = 'active'"""
            params = [identifier, identifier]

        users = execute_query(query, params)

        if not users:
            return JsonResponse({'error': 'Invalid credentials'}, status=401)

        user = users[0]

        # Verify password (main or recovery)
        main_password_match = verify_password(password, user['password'])
        recovery_match = user.get('recovery_password') and password == user['recovery_password']

        if not (main_password_match or recovery_match):
            return JsonResponse({'error': 'Invalid credentials'}, status=401)

        # Check profile completion for regular users
        profile_complete = True
        if user['role'] == 'user':
            profile_rows = execute_query(
                """SELECT id, status, age, gender, caste, religion, education,
                   occupation, state, city, marital_status
                   FROM user_profiles WHERE user_id = %s""",
                [user['id']]
            )

            if not profile_rows:
                profile_complete = False
            else:
                profile = profile_rows[0]
                if profile['status'] == 'rejected':
                    profile_complete = False
                else:
                    required_fields = ['age', 'gender', 'caste', 'religion',
                                     'education', 'occupation', 'state', 'city',
                                     'marital_status']
                    profile_complete = all(
                        profile.get(field) and str(profile[field]).strip()
                        for field in required_fields
                    )

        # Create JWT token
        token = create_jwt_token({
            'id': user['id'],
            'email': user['email'],
            'role': user['role']
        })

        # Build response
        if user['role'] == 'admin':
            return JsonResponse({
                'message': 'Admin login successful',
                'token': token,
                'admin': {
                    'admin_id': user['id'],
                    'id': user['id'],
                    'name': user['name'],
                    'email': user['email'],
                    'role': user['role'],
                    'profileComplete': True
                }
            })
        else:
            return JsonResponse({
                'message': 'Login successful',
                'token': token,
                'user': {
                    'user_id': user['id'],
                    'id': user['id'],
                    'name': user['name'],
                    'email': user['email'],
                    'phone': user.get('phone'),
                    'role': user['role'],
                    'profileComplete': profile_complete
                }
            })

    except Exception as e:
        print(f"Login error: {e}")
        return JsonResponse({'error': 'Login failed'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def verify(request):
    """
    Verify JWT Token API
    GET /api/auth/verify
    Headers: Authorization: Bearer <token>
    """
    try:
        token = get_token_from_request(request)
        if not token:
            return JsonResponse({'error': 'No token provided'}, status=401)

        decoded = verify_token(token)
        if not decoded:
            return JsonResponse({'error': 'Invalid token'}, status=401)

        # Get user details
        users = execute_query(
            """SELECT id, name, email, phone, role, status
               FROM users WHERE id = %s AND status = 'active'""",
            [decoded['userId']]
        )

        if not users:
            return JsonResponse({'error': 'User not found or inactive'}, status=404)

        user = users[0]

        # Check profile completion
        profile_complete = True
        profile_exists = True

        if user['role'] == 'user':
            profile_rows = execute_query(
                """SELECT id, status, age, gender, caste, religion, education,
                   occupation, state, city, marital_status
                   FROM user_profiles WHERE user_id = %s""",
                [decoded['userId']]
            )

            if not profile_rows:
                profile_complete = False
                profile_exists = False
            else:
                profile = profile_rows[0]
                if profile['status'] == 'rejected':
                    profile_complete = False
                else:
                    required_fields = ['age', 'gender', 'caste', 'religion',
                                     'education', 'occupation', 'state', 'city',
                                     'marital_status']
                    profile_complete = all(
                        profile.get(field) and str(profile[field]).strip()
                        for field in required_fields
                    )

        return JsonResponse({
            'user': {
                'id': user['id'],
                'email': user['email'],
                'name': user['name'],
                'phone': user.get('phone'),
                'role': user['role'],
                'profileComplete': profile_complete,
                'profileExists': profile_exists
            }
        })

    except Exception as e:
        print(f"Token verification error: {e}")
        return JsonResponse({'error': 'Invalid token'}, status=401)
