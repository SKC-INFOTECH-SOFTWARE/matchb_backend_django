import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from api.utils import require_user, verify_password, hash_password
from api.db_utils import execute_query, execute_insert, execute_update

# ==================== MATCHES ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_user
def user_matches(request):
    """
    Get User's Matches with Block Status
    GET /api/user/matches
    """
    try:
        user_id = request.user_data['userId']

        query = """
            SELECT
                u.id, u.name, u.email, u.phone,
                up.age, up.gender, up.height, up.weight, up.caste, up.religion,
                up.mother_tongue, up.marital_status, up.education, up.occupation,
                up.income, up.state, up.city, up.family_type, up.family_status,
                up.about_me, up.partner_preferences, up.profile_photo,
                m.created_at as matched_at, m.created_by_admin,
                admin_user.name as matched_by_admin_name,
                CASE WHEN ub_me.id IS NOT NULL THEN 1 ELSE 0 END as i_blocked_them,
                CASE WHEN ub_them.id IS NOT NULL THEN 1 ELSE 0 END as they_blocked_me,
                ub_me.created_at as blocked_by_me_at,
                ub_them.created_at as blocked_me_at,
                COALESCE(ub_me.call_allowed, 0) as call_allowed
            FROM matches m
            JOIN users u ON m.matched_user_id = u.id
            JOIN user_profiles up ON u.id = up.user_id
            LEFT JOIN users admin_user ON m.created_by_admin = admin_user.id
            LEFT JOIN user_blocks ub_me ON ub_me.blocker_id = %s AND ub_me.blocked_id = u.id
            LEFT JOIN user_blocks ub_them ON ub_them.blocker_id = u.id AND ub_them.blocked_id = %s
            WHERE m.user_id = %s
                AND u.status = 'active'
                AND up.status = 'approved'
            ORDER BY m.created_at DESC
        """

        matches = execute_query(query, [user_id, user_id, user_id])

        return JsonResponse({
            'matches': matches,
            'total': len(matches)
        })

    except Exception as e:
        print(f"User matches error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_user
def get_match_details(request):
    """
    Get Single Match Profile Details (requires subscription)
    POST /api/user/matches
    Body: { matchedUserId }
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)
        matched_user_id = data.get('matchedUserId')

        if not matched_user_id:
            return JsonResponse({'error': 'Matched user ID is required'}, status=400)

        # Check subscription
        subscription = execute_query("""
            SELECT us.*, p.can_view_details
            FROM user_subscriptions us
            JOIN plans p ON us.plan_id = p.id
            WHERE us.user_id = %s
                AND us.status = 'active'
                AND p.type = 'normal'
                AND us.expires_at > NOW()
            ORDER BY us.expires_at DESC
            LIMIT 1
        """, [user_id])

        if not subscription or not subscription[0]['can_view_details']:
            return JsonResponse({
                'error': 'Premium subscription required to view profile details'
            }, status=403)

        # Verify match exists
        match_check = execute_query(
            "SELECT id FROM matches WHERE user_id = %s AND matched_user_id = %s",
            [user_id, matched_user_id]
        )

        if not match_check:
            return JsonResponse({'error': 'Match not found'}, status=404)

        # Get profile
        profile = execute_query("""
            SELECT u.id, u.name, u.email, u.phone,
                   up.age, up.gender, up.height, up.weight, up.caste, up.religion,
                   up.mother_tongue, up.marital_status, up.education, up.occupation,
                   up.income, up.state, up.city, up.family_type, up.family_status,
                   up.about_me, up.partner_preferences, up.profile_photo,
                   up.created_at, up.updated_at
            FROM users u
            JOIN user_profiles up ON u.id = up.user_id
            WHERE u.id = %s AND u.status = 'active' AND up.status = 'approved'
        """, [matched_user_id])

        if not profile:
            return JsonResponse({'error': 'Profile not found'}, status=404)

        return JsonResponse({'profile': profile[0]})

    except Exception as e:
        print(f"Match profile error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def profile_details(request, profile_id):
    """
    Get Profile Details by ID (requires subscription)
    GET /api/user/profile-details/<profile_id>
    """
    try:
        user_id = request.user_data['userId']

        # Check subscription
        subscription = execute_query("""
            SELECT us.*, p.can_view_details
            FROM user_subscriptions us
            JOIN plans p ON us.plan_id = p.id
            WHERE us.user_id = %s
                AND us.status = 'active'
                AND p.type = 'normal'
                AND us.expires_at > NOW()
            ORDER BY us.expires_at DESC
            LIMIT 1
        """, [user_id])

        if not subscription or not subscription[0]['can_view_details']:
            return JsonResponse({
                'error': 'Premium subscription required to view profile details'
            }, status=403)

        # Check if matched
        match_check = execute_query("""
            SELECT 1 FROM matches
            WHERE (user_id = %s AND matched_user_id = %s)
               OR (user_id = %s AND matched_user_id = %s)
        """, [user_id, profile_id, profile_id, user_id])

        is_matched = len(match_check) > 0

        # Get profile
        profile = execute_query("""
            SELECT u.id, u.name, u.email, u.phone,
                   up.age, up.gender, up.height, up.weight, up.caste, up.religion,
                   up.mother_tongue, up.marital_status, up.education, up.occupation,
                   up.income, up.state, up.city, up.family_type, up.family_status,
                   up.about_me, up.partner_preferences, up.profile_photo,
                   up.created_at, up.updated_at
            FROM users u
            JOIN user_profiles up ON u.id = up.user_id
            WHERE u.id = %s AND u.status = 'active' AND up.status = 'approved'
        """, [profile_id])

        if not profile:
            return JsonResponse({'error': 'Profile not found'}, status=404)

        profile_data = profile[0]
        profile_data['is_matched'] = is_matched

        return JsonResponse({'profile': profile_data})

    except Exception as e:
        print(f"Profile details error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

# ==================== SEARCH ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_user
def search_profiles(request):
    """
    Search Profiles by Location and Gender
    GET /api/user/search?location=<state>&gender=<gender>
    """
    try:
        state = request.GET.get('location') or request.GET.get('state', '')
        gender = request.GET.get('gender', '')

        if not state or not gender:
            return JsonResponse({
                'availableCount': 0,
                'message': 'Please select both state and gender to search'
            }, status=400)

        # Get visibility settings
        visibility = execute_query("""
            SELECT visible_count
            FROM search_visibility_settings
            WHERE state = %s AND gender = %s
        """, [state, gender])

        available_count = visibility[0]['visible_count'] if visibility else 0

        return JsonResponse({
            'availableCount': available_count,
            'state': state,
            'gender': gender,
            'message': f"{available_count} profiles available for {gender} in {state}" if available_count > 0
                      else f"No profiles available for {gender} in {state}"
        })

    except Exception as e:
        print(f"Search error: {e}")
        return JsonResponse({'error': 'Search failed'}, status=500)

# ==================== BLOCKING ====================
@csrf_exempt
@require_http_methods(["POST"])
@require_user
def block_user(request):
    """
    Block a User
    POST /api/user/block
    Body: { blockedUserId }
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)
        blocked_user_id = data.get('blockedUserId')

        if not blocked_user_id:
            return JsonResponse({'error': 'Blocked user ID is required'}, status=400)

        if user_id == blocked_user_id:
            return JsonResponse({'error': 'You cannot block yourself'}, status=400)

        # Check if already blocked
        existing = execute_query(
            "SELECT id FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s",
            [user_id, blocked_user_id]
        )

        if existing:
            return JsonResponse({'error': 'User is already blocked'}, status=400)

        # Insert block
        execute_insert(
            "INSERT INTO user_blocks (blocker_id, blocked_id, call_allowed, created_at) VALUES (%s, %s, 0, NOW())",
            [user_id, blocked_user_id]
        )

        return JsonResponse({
            'success': True,
            'message': 'User blocked successfully'
        })

    except Exception as e:
        print(f"Block user error: {e}")
        return JsonResponse({'error': 'Failed to block user'}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
@require_user
def unblock_user(request):
    """
    Unblock a User
    DELETE /api/user/block
    Body: { blockedUserId }
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)
        blocked_user_id = data.get('blockedUserId')

        if not blocked_user_id:
            return JsonResponse({'error': 'Blocked user ID is required'}, status=400)

        # Delete block
        rows_affected = execute_update(
            "DELETE FROM user_blocks WHERE blocker_id = %s AND blocked_id = %s",
            [user_id, blocked_user_id]
        )

        if rows_affected == 0:
            return JsonResponse({'error': 'Block record not found'}, status=404)

        return JsonResponse({
            'success': True,
            'message': 'User unblocked successfully'
        })

    except Exception as e:
        print(f"Unblock user error: {e}")
        return JsonResponse({'error': 'Failed to unblock user'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def get_blocked_users(request):
    """
    Get Blocked Users List
    GET /api/user/block
    """
    try:
        user_id = request.user_data['userId']

        # Users blocked by me
        blocked_by_me = execute_query("""
            SELECT ub.id as block_id, ub.blocked_id, ub.call_allowed,
                   ub.created_at as blocked_at,
                   u.name, u.email, up.profile_photo, up.age, up.city
            FROM user_blocks ub
            JOIN users u ON ub.blocked_id = u.id
            LEFT JOIN user_profiles up ON u.id = up.user_id
            WHERE ub.blocker_id = %s
            ORDER BY ub.created_at DESC
        """, [user_id])

        # Users who blocked me
        blocked_me = execute_query("""
            SELECT ub.id as block_id, ub.blocker_id, ub.call_allowed,
                   ub.created_at as blocked_at, u.name, u.email
            FROM user_blocks ub
            JOIN users u ON ub.blocker_id = u.id
            WHERE ub.blocked_id = %s
            ORDER BY ub.created_at DESC
        """, [user_id])

        return JsonResponse({
            'success': True,
            'blockedByMe': blocked_by_me,
            'blockedMe': blocked_me
        })

    except Exception as e:
        print(f"Get blocked users error: {e}")
        return JsonResponse({'error': 'Failed to fetch blocked users'}, status=500)

@csrf_exempt
@require_http_methods(["POST", "DELETE", "GET"])
@require_user
def block_user_handler(request):
    """
    Combined handler for blocking
    POST: Block user
    DELETE: Unblock user
    GET: Get blocked users
    """
    if request.method == "POST":
        return block_user(request)
    elif request.method == "DELETE":
        return unblock_user(request)
    elif request.method == "GET":
        return get_blocked_users(request)

# ==================== SUBSCRIPTION & CREDITS ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_user
def subscription_status(request):
    """
    Get Subscription Status
    GET /api/user/subscription-status
    """
    try:
        user_id = request.user_data['userId']

        # Check normal subscription
        normal_sub = execute_query("""
            SELECT us.*, p.name as plan_name, p.price, p.duration_months,
                   p.can_view_details, p.can_make_calls
            FROM user_subscriptions us
            JOIN plans p ON us.plan_id = p.id
            WHERE us.user_id = %s
                AND us.status = 'active'
                AND p.type = 'normal'
                AND us.expires_at > NOW()
            ORDER BY us.expires_at DESC
            LIMIT 1
        """, [user_id])

        # Check call credits
        call_credits = execute_query("""
            SELECT uc.*, p.name as plan_name, p.price, p.call_credits
            FROM user_call_credits uc
            JOIN plans p ON uc.plan_id = p.id
            WHERE uc.user_id = %s
                AND uc.credits_remaining > 0
                AND uc.expires_at > NOW()
            ORDER BY uc.expires_at DESC
            LIMIT 1
        """, [user_id])

        # Check profile completion
        profile = execute_query("""
            SELECT CASE
                WHEN about_me IS NOT NULL AND about_me != ''
                AND partner_preferences IS NOT NULL AND partner_preferences != ''
                AND profile_photo IS NOT NULL AND profile_photo != ''
                THEN 1 ELSE 0 END as profile_complete
            FROM user_profiles WHERE user_id = %s
        """, [user_id])

        profile_complete = profile[0]['profile_complete'] == 1 if profile else False

        # Build response
        from datetime import datetime
        now = datetime.now()

        normal_plan_data = None
        if normal_sub:
            sub = normal_sub[0]
            expires_at = sub['expires_at']
            days_left = (expires_at - now).days if expires_at > now else 0

            normal_plan_data = {
                'plan_name': sub['plan_name'],
                'price': float(sub['price']),
                'duration_months': sub['duration_months'],
                'expires_at': str(sub['expires_at']),
                'days_left': max(0, days_left),
                'is_active': True
            }

        call_plan_data = None
        if call_credits:
            cc = call_credits[0]
            expires_at = cc['expires_at']
            days_left = (expires_at - now).days if expires_at > now else 0

            call_plan_data = {
                'plan_name': cc['plan_name'],
                'credits_remaining': cc['credits_remaining'],
                'expires_at': str(cc['expires_at']),
                'days_left': max(0, days_left),
                'is_active': True
            }

        # Recommendations
        recommendations = []
        if not normal_plan_data:
            recommendations.append("Upgrade to Premium to view full profile details and contact information")
            recommendations.append("Premium members get unlimited profile views and advanced search filters")
        if not call_plan_data:
            recommendations.append("Purchase call credits to make secure calls to your matches")
        if not profile_complete:
            recommendations.append("Complete your profile to get better matches")

        return JsonResponse({
            'subscription_status': {
                'is_premium': normal_plan_data is not None,
                'can_view_details': normal_sub[0]['can_view_details'] if normal_sub else False,
                'can_make_calls': normal_sub[0]['can_make_calls'] if normal_sub else False,
                'has_call_credits': call_plan_data is not None,
                'profile_complete': profile_complete,
                'normal_plan': normal_plan_data,
                'call_plan': call_plan_data,
                'recommendations': recommendations
            }
        })

    except Exception as e:
        print(f"Subscription status error: {e}")
        return JsonResponse({'error': 'Failed to fetch subscription status'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def active_plan(request):
    """
    Get Active Plans
    GET /api/user/active-plan
    """
    try:
        user_id = request.user_data['userId']

        # Normal plan
        normal_plan = execute_query("""
            SELECT p.name AS plan_name, p.price, p.duration_months,
                   us.expires_at, DATEDIFF(us.expires_at, NOW()) AS days_left, us.status
            FROM user_subscriptions us
            JOIN plans p ON us.plan_id = p.id
            WHERE us.user_id = %s
                AND us.status = 'active'
                AND us.expires_at > NOW()
            ORDER BY us.expires_at DESC
            LIMIT 1
        """, [user_id])

        # Call plan
        call_plan = execute_query("""
            SELECT p.name AS plan_name, p.price, ucc.credits_remaining,
                   ucc.expires_at, DATEDIFF(ucc.expires_at, NOW()) AS days_left, p.call_credits
            FROM user_call_credits ucc
            JOIN plans p ON ucc.plan_id = p.id
            WHERE ucc.user_id = %s
                AND ucc.expires_at > NOW()
            ORDER BY ucc.expires_at DESC
            LIMIT 1
        """, [user_id])

        normal_plan_data = None
        if normal_plan:
            np = normal_plan[0]
            normal_plan_data = {
                'plan_name': np['plan_name'],
                'price': float(np['price']),
                'duration_months': np['duration_months'],
                'expires_at': str(np['expires_at']),
                'daysLeft': max(0, np['days_left']),
                'isActive': np['status'] == 'active'
            }

        call_plan_data = None
        if call_plan:
            cp = call_plan[0]
            call_plan_data = {
                'plan_name': cp['plan_name'],
                'price': float(cp['price']),
                'credits_remaining': cp['credits_remaining'],
                'expires_at': str(cp['expires_at']),
                'daysLeft': max(0, cp['days_left']),
                'isActive': cp['credits_remaining'] > 0
            }

        return JsonResponse({
            'plans': {
                'normal_plan': normal_plan_data,
                'call_plan': call_plan_data
            }
        })

    except Exception as e:
        print(f"Active plan error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def call_credits(request):
    """
    Get Call Credits Info
    GET /api/user/call-credits
    """
    try:
        user_id = request.user_data['userId']

        # Get active credits
        credits = execute_query("""
            SELECT uc.id, uc.credits_remaining, uc.credits_purchased,
                   uc.expires_at, uc.admin_allocated, uc.allocation_notes,
                   uc.last_used_at, p.name as plan_name, p.duration_months
            FROM user_call_credits uc
            LEFT JOIN plans p ON uc.plan_id = p.id
            WHERE uc.user_id = %s AND uc.expires_at > NOW()
            ORDER BY uc.expires_at ASC
        """, [user_id])

        # Calculate totals
        total_remaining = sum(c['credits_remaining'] for c in credits)
        total_purchased = sum(c['credits_purchased'] for c in credits)

        # Get call stats
        call_stats = execute_query("""
            SELECT COUNT(*) as total_calls, SUM(duration) as total_duration,
                   MAX(created_at) as last_call_date
            FROM call_logs
            WHERE user_id = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        """, [user_id])

        stats = call_stats[0] if call_stats else {}

        # Format allocations
        allocations = []
        for c in credits:
            allocations.append({
                'id': c['id'],
                'planName': c['plan_name'] or 'Manual Allocation',
                'creditsRemaining': c['credits_remaining'],
                'creditsPurchased': c['credits_purchased'],
                'expiresAt': str(c['expires_at']),
                'isAdminAllocated': c['admin_allocated'] == 1,
                'allocationNotes': c['allocation_notes'],
                'lastUsed': str(c['last_used_at']) if c['last_used_at'] else None
            })

        return JsonResponse({
            'success': True,
            'canMakeCalls': total_remaining > 0,
            'totalCreditsRemaining': total_remaining,
            'totalCreditsPurchased': total_purchased,
            'creditsUsed': total_purchased - total_remaining,
            'activeAllocations': len(credits),
            'nextExpiryDate': str(credits[0]['expires_at']) if credits else None,
            'recentCalls': {
                'total': stats.get('total_calls', 0),
                'totalDuration': stats.get('total_duration', 0),
                'lastCallDate': str(stats['last_call_date']) if stats.get('last_call_date') else None
            },
            'allocations': allocations
        })

    except Exception as e:
        print(f"Call credits error: {e}")
        return JsonResponse({'error': 'Failed to fetch credit status'}, status=500)

# ==================== SETTINGS ====================
@csrf_exempt
@require_http_methods(["PUT"])
@require_user
def change_password(request):
    """
    Change User Password
    PUT /api/user/change-password
    Body: { currentPassword, newPassword }
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)
        current_password = data.get('currentPassword')
        new_password = data.get('newPassword')

        # Validation
        if not current_password or not new_password:
            return JsonResponse({
                'error': 'Current password and new password are required'
            }, status=400)

        if len(new_password) < 6:
            return JsonResponse({
                'error': 'New password must be at least 6 characters long'
            }, status=400)

        if current_password == new_password:
            return JsonResponse({
                'error': 'New password must be different from current password'
            }, status=400)

        # Get current password
        user = execute_query("SELECT password FROM users WHERE id = %s", [user_id])

        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)

        # Verify current password
        if not verify_password(current_password, user[0]['password']):
            return JsonResponse({'error': 'Current password is incorrect'}, status=400)

        # Hash new password
        hashed_new_password = hash_password(new_password)

        # Update password
        execute_update(
            "UPDATE users SET password = %s WHERE id = %s",
            [hashed_new_password, user_id]
        )

        return JsonResponse({
            'success': True,
            'message': 'Password updated successfully'
        })

    except Exception as e:
        print(f"Change password error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)
