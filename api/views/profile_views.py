import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from api.utils import require_user
from api.db_utils import execute_query, execute_insert, execute_update

@csrf_exempt
@require_http_methods(["POST"])
@require_user
def create_profile(request):
    """
    Create User Profile
    POST /api/profile/create
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)

        # Required fields
        required_fields = ['age', 'gender', 'caste', 'religion', 'education',
                          'occupation', 'state', 'city', 'marital_status']

        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'error': f'{field} is required'}, status=400)

        # Check if profile exists
        existing = execute_query(
            "SELECT id FROM user_profiles WHERE user_id = %s",
            [user_id]
        )

        if existing:
            return JsonResponse({'error': 'Profile already exists'}, status=409)

        # Insert profile
        execute_insert("""
            INSERT INTO user_profiles (
                user_id, age, gender, height, weight, caste, religion, mother_tongue,
                marital_status, education, occupation, income, state, city, family_type,
                family_status, about_me, partner_preferences, profile_photo, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, [
            user_id, data['age'], data['gender'],
            data.get('height'), data.get('weight'),
            data['caste'], data['religion'], data.get('mother_tongue'),
            data['marital_status'], data['education'], data['occupation'],
            data.get('income'), data['state'], data['city'],
            data.get('family_type'), data.get('family_status'),
            data.get('about_me'), data.get('partner_preferences'),
            data.get('profile_photo')
        ])

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Profile creation error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
@require_user
def edit_profile(request):
    """
    Edit User Profile
    PUT /api/profile/edit
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)

        # Required fields
        required_fields = ['age', 'gender', 'caste', 'religion', 'education',
                          'occupation', 'state', 'city', 'marital_status']

        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'error': f'{field} is required'}, status=400)

        # Check if profile exists
        existing = execute_query(
            "SELECT id FROM user_profiles WHERE user_id = %s",
            [user_id]
        )

        if not existing:
            return JsonResponse({'error': 'Profile not found'}, status=404)

        # Update profile
        execute_update("""
            UPDATE user_profiles SET
                age = %s, gender = %s, height = %s, weight = %s, caste = %s,
                religion = %s, mother_tongue = %s, marital_status = %s,
                education = %s, occupation = %s, income = %s, state = %s,
                city = %s, family_type = %s, family_status = %s, about_me = %s,
                partner_preferences = %s, profile_photo = %s, updated_at = NOW()
            WHERE user_id = %s
        """, [
            data['age'], data['gender'], data.get('height'), data.get('weight'),
            data['caste'], data['religion'], data.get('mother_tongue'),
            data['marital_status'], data['education'], data['occupation'],
            data.get('income'), data['state'], data['city'],
            data.get('family_type'), data.get('family_status'),
            data.get('about_me'), data.get('partner_preferences'),
            data.get('profile_photo'), user_id
        ])

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Profile update error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def my_profile(request):
    """
    Get My Profile
    GET /api/profile/me
    """
    try:
        user_id = request.user_data['userId']

        profile = execute_query("""
            SELECT u.id, u.name, u.email,
                   up.age, up.gender, up.height, up.weight, up.caste, up.religion,
                   up.mother_tongue, up.marital_status, up.education, up.occupation,
                   up.income, up.state, up.city, up.family_type, up.family_status,
                   up.about_me, up.partner_preferences, up.profile_photo
            FROM users u
            JOIN user_profiles up ON u.id = up.user_id
            WHERE u.id = %s
        """, [user_id])

        if not profile:
            return JsonResponse({'error': 'Profile not found'}, status=404)

        return JsonResponse({'profile': profile[0]})

    except Exception as e:
        print(f"Profile fetch error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)



