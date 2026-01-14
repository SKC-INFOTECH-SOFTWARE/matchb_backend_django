import json
import random
import string
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from api.utils import require_admin, hash_password, verify_password
from api.db_utils import execute_query, execute_insert, execute_update

# ==================== STATS API ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_stats(request):
    """
    Admin Dashboard Stats API
    GET /api/admin/stats
    Returns: User counts, match stats, revenue, etc.
    """
    try:
        stats_queries = {
            'totalUsers': "SELECT COUNT(*) as count FROM users WHERE role = 'user'",
            'activeUsers': "SELECT COUNT(*) as count FROM users WHERE role = 'user' AND status = 'active'",
            'maleUsers': "SELECT COUNT(*) as count FROM user_profiles WHERE gender = 'Male' AND status = 'approved'",
            'femaleUsers': "SELECT COUNT(*) as count FROM user_profiles WHERE gender = 'Female' AND status = 'approved'",
            'pendingProfiles': "SELECT COUNT(*) as count FROM user_profiles WHERE status = 'pending'",
            'approvedProfiles': "SELECT COUNT(*) as count FROM user_profiles WHERE status = 'approved'",
            'totalMatches': "SELECT COUNT(*) as count FROM matches",
            'activeCallSessions': "SELECT COUNT(*) as count FROM call_sessions WHERE status IN ('initiated', 'ringing', 'in_progress')",
            'callMinutesUsed': """SELECT COALESCE(SUM(duration), 0) as count
                                 FROM call_sessions
                                 WHERE status = 'completed'
                                 AND MONTH(created_at) = MONTH(NOW())
                                 AND YEAR(created_at) = YEAR(NOW())""",
            'totalRevenue': """SELECT COALESCE(SUM(amount), 0) as count
                              FROM payments
                              WHERE status = 'verified'
                              AND MONTH(created_at) = MONTH(NOW())
                              AND YEAR(created_at) = YEAR(NOW())""",
            'normalSubscriptions': """SELECT COUNT(*) as count
                                     FROM user_subscriptions us
                                     JOIN plans p ON us.plan_id = p.id
                                     WHERE us.status = 'active'
                                     AND p.type = 'normal'
                                     AND us.expires_at > NOW()""",
            'callSubscriptions': """SELECT COUNT(*) as count
                                   FROM user_call_credits uc
                                   JOIN plans p ON uc.plan_id = p.id
                                   WHERE uc.credits_remaining > 0
                                   AND p.type = 'call'
                                   AND uc.expires_at > NOW()"""
        }

        stats = {}
        for key, query in stats_queries.items():
            result = execute_query(query)
            stats[key] = result[0]['count'] if result else 0

        return JsonResponse(stats)

    except Exception as e:
        print(f"Stats error: {e}")
        return JsonResponse({'error': 'Failed to fetch stats'}, status=500)


# ==================== PROFILES API ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_profiles(request):
    """
    Admin Get All Profiles API
    GET /api/admin/profiles
    Returns: All user profiles with status
    """
    try:
        query = """
            SELECT
                u.id as user_id, u.name, u.email, u.phone, u.recovery_password,
                u.status as user_status, u.created_at as user_created_at,
                up.id as profile_id, up.age, up.gender, up.height, up.weight,
                up.caste, up.religion, up.mother_tongue, up.marital_status,
                up.education, up.occupation, up.income, up.state, up.city,
                up.family_type, up.family_status, up.about_me, up.partner_preferences,
                up.profile_photo, up.status as profile_status, up.rejection_reason,
                up.created_at as profile_created_at, up.updated_at as profile_updated_at,
                CASE WHEN ns.id IS NOT NULL THEN 1 ELSE 0 END as has_normal_plan,
                CASE WHEN cc.id IS NOT NULL THEN 1 ELSE 0 END as has_call_plan,
                COALESCE(cc.credits_remaining, 0) as call_credits_remaining,
                (SELECT COUNT(*) FROM matches WHERE user_id = u.id OR matched_user_id = u.id) as total_matches,
                CASE WHEN up.id IS NULL THEN 'incomplete_registration' ELSE up.status END as computed_status
            FROM users u
            LEFT JOIN user_profiles up ON up.user_id = u.id
            LEFT JOIN user_subscriptions ns ON ns.user_id = u.id AND ns.status = 'active' AND ns.expires_at > NOW()
            LEFT JOIN user_call_credits cc ON cc.user_id = u.id AND cc.credits_remaining > 0 AND cc.expires_at > NOW()
            WHERE u.role = 'user'
            ORDER BY
                CASE WHEN up.id IS NULL THEN 0 ELSE 1 END,
                u.created_at DESC
        """

        profiles = execute_query(query)

        # Format response
        formatted_profiles = []
        for row in profiles:
            formatted_profiles.append({
                'id': row['profile_id'] or f"incomplete_{row['user_id']}",
                'user_id': row['user_id'],
                'name': row['name'],
                'email': row['email'],
                'phone': row['phone'],
                'recovery_password': row['recovery_password'],
                'user_created_at': str(row['user_created_at']),
                'age': row['age'],
                'gender': row['gender'],
                'height': row['height'],
                'weight': row['weight'],
                'caste': row['caste'],
                'religion': row['religion'],
                'mother_tongue': row['mother_tongue'],
                'marital_status': row['marital_status'],
                'education': row['education'],
                'occupation': row['occupation'],
                'income': row['income'],
                'state': row['state'],
                'city': row['city'],
                'family_type': row['family_type'],
                'family_status': row['family_status'],
                'about_me': row['about_me'],
                'partner_preferences': row['partner_preferences'],
                'profile_photo': row['profile_photo'],
                'status': row['computed_status'],
                'rejection_reason': row['rejection_reason'],
                'created_at': str(row['profile_created_at'] or row['user_created_at']),
                'updated_at': str(row['profile_updated_at']) if row['profile_updated_at'] else None,
                'user_status': row['user_status'],
                'has_normal_plan': row['has_normal_plan'] == 1,
                'has_call_plan': row['has_call_plan'] == 1,
                'call_credits_remaining': row['call_credits_remaining'],
                'total_matches': row['total_matches'],
                'is_incomplete_registration': row['profile_id'] is None
            })

        return JsonResponse(formatted_profiles, safe=False)

    except Exception as e:
        print(f"Profiles error: {e}")
        return JsonResponse({'error': 'Failed to fetch profiles'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def approve_profile(request):
    """
    Admin Approve/Reject Profile API
    POST /api/admin/approve-profile
    Body: { profileId, status, rejectionReason? }
    """
    try:
        data = json.loads(request.body)
        profile_id = data.get('profileId')
        status = data.get('status')
        rejection_reason = data.get('rejectionReason')

        if not all([profile_id, status]):
            return JsonResponse({
                'error': 'Profile ID and status are required'
            }, status=400)

        if status not in ['approved', 'rejected']:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        if status == 'rejected' and not rejection_reason:
            return JsonResponse({
                'error': 'Rejection reason is required'
            }, status=400)

        execute_update(
            """UPDATE user_profiles
               SET status = %s, rejection_reason = %s, updated_at = NOW()
               WHERE id = %s""",
            [status, rejection_reason if status == 'rejected' else None, profile_id]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Profile approval error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def update_user_status(request):
    """
    Admin Update User Status API
    POST /api/admin/update-status
    Body: { userId, status }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('userId')
        status = data.get('status')

        if not all([user_id, status]):
            return JsonResponse({
                'error': 'User ID and status are required'
            }, status=400)

        if status not in ['active', 'inactive', 'banned']:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        execute_update(
            "UPDATE users SET status = %s WHERE id = %s AND role = 'user'",
            [status, user_id]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Update status error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)



# ==================== PROFILES API ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_profiles(request):
    """
    Admin Get All Profiles API
    GET /api/admin/profiles
    Returns: All user profiles with status
    """
    try:
        query = """
            SELECT
                u.id as user_id, u.name, u.email, u.phone, u.recovery_password,
                u.status as user_status, u.created_at as user_created_at,
                up.id as profile_id, up.age, up.gender, up.height, up.weight,
                up.caste, up.religion, up.mother_tongue, up.marital_status,
                up.education, up.occupation, up.income, up.state, up.city,
                up.family_type, up.family_status, up.about_me, up.partner_preferences,
                up.profile_photo, up.status as profile_status, up.rejection_reason,
                up.created_at as profile_created_at, up.updated_at as profile_updated_at,
                CASE WHEN ns.id IS NOT NULL THEN 1 ELSE 0 END as has_normal_plan,
                CASE WHEN cc.id IS NOT NULL THEN 1 ELSE 0 END as has_call_plan,
                COALESCE(cc.credits_remaining, 0) as call_credits_remaining,
                (SELECT COUNT(*) FROM matches WHERE user_id = u.id OR matched_user_id = u.id) as total_matches,
                CASE WHEN up.id IS NULL THEN 'incomplete_registration' ELSE up.status END as computed_status
            FROM users u
            LEFT JOIN user_profiles up ON up.user_id = u.id
            LEFT JOIN user_subscriptions ns ON ns.user_id = u.id AND ns.status = 'active' AND ns.expires_at > NOW()
            LEFT JOIN user_call_credits cc ON cc.user_id = u.id AND cc.credits_remaining > 0 AND cc.expires_at > NOW()
            WHERE u.role = 'user'
            ORDER BY
                CASE WHEN up.id IS NULL THEN 0 ELSE 1 END,
                u.created_at DESC
        """

        profiles = execute_query(query)

        # Format response
        formatted_profiles = []
        for row in profiles:
            formatted_profiles.append({
                'id': row['profile_id'] or f"incomplete_{row['user_id']}",
                'user_id': row['user_id'],
                'name': row['name'],
                'email': row['email'],
                'phone': row['phone'],
                'recovery_password': row['recovery_password'],
                'user_created_at': str(row['user_created_at']),
                'age': row['age'],
                'gender': row['gender'],
                'height': row['height'],
                'weight': row['weight'],
                'caste': row['caste'],
                'religion': row['religion'],
                'mother_tongue': row['mother_tongue'],
                'marital_status': row['marital_status'],
                'education': row['education'],
                'occupation': row['occupation'],
                'income': row['income'],
                'state': row['state'],
                'city': row['city'],
                'family_type': row['family_type'],
                'family_status': row['family_status'],
                'about_me': row['about_me'],
                'partner_preferences': row['partner_preferences'],
                'profile_photo': row['profile_photo'],
                'status': row['computed_status'],
                'rejection_reason': row['rejection_reason'],
                'created_at': str(row['profile_created_at'] or row['user_created_at']),
                'updated_at': str(row['profile_updated_at']) if row['profile_updated_at'] else None,
                'user_status': row['user_status'],
                'has_normal_plan': row['has_normal_plan'] == 1,
                'has_call_plan': row['has_call_plan'] == 1,
                'call_credits_remaining': row['call_credits_remaining'],
                'total_matches': row['total_matches'],
                'is_incomplete_registration': row['profile_id'] is None
            })

        return JsonResponse(formatted_profiles, safe=False)

    except Exception as e:
        print(f"Profiles error: {e}")
        return JsonResponse({'error': 'Failed to fetch profiles'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def approve_profile(request):
    """
    Admin Approve/Reject Profile API
    POST /api/admin/approve-profile
    Body: { profileId, status, rejectionReason? }
    """
    try:
        data = json.loads(request.body)
        profile_id = data.get('profileId')
        status = data.get('status')
        rejection_reason = data.get('rejectionReason')

        if not all([profile_id, status]):
            return JsonResponse({
                'error': 'Profile ID and status are required'
            }, status=400)

        if status not in ['approved', 'rejected']:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        if status == 'rejected' and not rejection_reason:
            return JsonResponse({
                'error': 'Rejection reason is required'
            }, status=400)

        execute_update(
            """UPDATE user_profiles
               SET status = %s, rejection_reason = %s, updated_at = NOW()
               WHERE id = %s""",
            [status, rejection_reason if status == 'rejected' else None, profile_id]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Profile approval error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def update_user_status(request):
    """
    Admin Update User Status API
    POST /api/admin/update-status
    Body: { userId, status }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('userId')
        status = data.get('status')

        if not all([user_id, status]):
            return JsonResponse({
                'error': 'User ID and status are required'
            }, status=400)

        if status not in ['active', 'inactive', 'banned']:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        execute_update(
            "UPDATE users SET status = %s WHERE id = %s AND role = 'user'",
            [status, user_id]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Update status error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


# ==================== PLANS API ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_get_plans(request):
    """
    Admin Get All Plans API
    GET /api/admin/plans
    Returns: All plans (including inactive)
    """
    try:
        query = """
            SELECT id, name, price, duration_months, call_credits, features,
                   description, type, can_view_details, can_make_calls,
                   is_active, created_at, updated_at
            FROM plans
            ORDER BY created_at DESC
        """
        plans = execute_query(query)
        return JsonResponse({'plans': plans}, safe=False)

    except Exception as e:
        print(f"Plans fetch error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def admin_create_plan(request):
    """
    Admin Create Plan API
    POST /api/admin/plans
    Body: { name, price, duration_months, call_credits?, features?, description?, type?, can_view_details?, can_make_calls?, is_active? }
    """
    try:
        data = json.loads(request.body)
        name = data.get('name')
        price = data.get('price')
        duration_months = data.get('duration_months')
        call_credits = data.get('call_credits')
        features = data.get('features')
        description = data.get('description')
        plan_type = data.get('type', 'normal')
        can_view_details = data.get('can_view_details', True)
        can_make_calls = data.get('can_make_calls', False)
        is_active = data.get('is_active', True)

        # Validate
        if not all([name, price, duration_months]):
            return JsonResponse({
                'error': 'Name, price, and duration are required'
            }, status=400)

        if float(price) <= 0 or int(duration_months) <= 0:
            return JsonResponse({
                'error': 'Price and duration must be positive'
            }, status=400)

        if plan_type not in ['normal', 'call']:
            return JsonResponse({
                'error': "Plan type must be 'normal' or 'call'"
            }, status=400)

        if plan_type == 'call' and (not call_credits or int(call_credits) <= 0):
            return JsonResponse({
                'error': 'Call credits are required for call plans'
            }, status=400)

        # Check duplicate
        existing = execute_query("SELECT id FROM plans WHERE name = %s", [name])
        if existing:
            return JsonResponse({
                'error': 'Plan with this name already exists'
            }, status=409)

        # Insert plan
        plan_id = execute_insert(
            """INSERT INTO plans
               (name, price, duration_months, call_credits, features, description,
                type, can_view_details, can_make_calls, is_active, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())""",
            [name.strip(), price, duration_months,
             call_credits if plan_type == 'call' else None,
             features.strip() if features else None,
             description.strip() if description else None,
             plan_type, can_view_details, can_make_calls, is_active]
        )

        return JsonResponse({
            'success': True,
            'planId': plan_id,
            'message': 'Plan created successfully'
        })

    except Exception as e:
        print(f"Plan creation error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
@require_admin
def admin_plan_detail(request, plan_id):
    """
    Update Plan
    PUT /api/admin/plans/<plan_id>
    """
    try:
        data = json.loads(request.body)

        # Check if plan exists
        existing = execute_query("SELECT id, name, type FROM plans WHERE id = %s", [plan_id])
        if not existing:
            return JsonResponse({'error': 'Plan not found'}, status=404)

        # Check if only toggling status
        if len(data) == 1 and 'is_active' in data:
            execute_update(
                "UPDATE plans SET is_active = %s, updated_at = NOW() WHERE id = %s",
                [data['is_active'], plan_id]
            )
        else:
            # Full update
            name = data.get('name')
            price = data.get('price')
            duration_months = data.get('duration_months')
            call_credits = data.get('call_credits')
            features = data.get('features')
            description = data.get('description')
            plan_type = data.get('type')
            can_view_details = data.get('can_view_details')
            can_make_calls = data.get('can_make_calls')
            is_active = data.get('is_active')

            if not all([name, price is not None, duration_months]):
                return JsonResponse({
                    'error': 'Name, price, and duration are required'
                }, status=400)

            if float(price) <= 0 or int(duration_months) <= 0:
                return JsonResponse({
                    'error': 'Price and duration must be greater than 0'
                }, status=400)

            if plan_type and plan_type not in ['normal', 'call']:
                return JsonResponse({
                    'error': "Plan type must be 'normal' or 'call'"
                }, status=400)

            if plan_type == 'call' and (not call_credits or int(call_credits) <= 0):
                return JsonResponse({
                    'error': 'Call credits are required for call plans'
                }, status=400)

            # Check duplicate name
            duplicate = execute_query(
                "SELECT id FROM plans WHERE name = %s AND id != %s",
                [name, plan_id]
            )
            if duplicate:
                return JsonResponse({
                    'error': 'Plan with this name already exists'
                }, status=409)

            execute_update("""
                UPDATE plans SET
                    name = %s, price = %s, duration_months = %s, call_credits = %s,
                    features = %s, description = %s, type = %s,
                    can_view_details = %s, can_make_calls = %s, is_active = %s,
                    updated_at = NOW()
                WHERE id = %s
            """, [
                name.strip(), price, duration_months,
                call_credits if plan_type == 'call' else None,
                features.strip() if features else None,
                description.strip() if description else None,
                plan_type or 'normal',
                can_view_details if can_view_details is not None else True,
                can_make_calls if can_make_calls is not None else False,
                is_active if is_active is not None else True,
                plan_id
            ])

        return JsonResponse({
            'success': True,
            'message': 'Plan updated successfully'
        })

    except Exception as e:
        print(f"Plan update error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["DELETE"])
@require_admin
def admin_plan_delete(request, plan_id):
    """
    Delete Plan
    DELETE /api/admin/plans/<plan_id>
    """
    try:
        # Check if exists
        existing = execute_query("SELECT id FROM plans WHERE id = %s", [plan_id])
        if not existing:
            return JsonResponse({'error': 'Plan not found'}, status=404)

        # Check active payments
        active_payments = execute_query("""
            SELECT COUNT(*) as count FROM payments
            WHERE plan_id = %s AND status = 'verified'
        """, [plan_id])

        if active_payments[0]['count'] > 0:
            return JsonResponse({
                'error': 'Cannot delete plan with active payments. Consider deactivating instead.'
            }, status=400)

        execute_update("DELETE FROM plans WHERE id = %s", [plan_id])

        return JsonResponse({
            'success': True,
            'message': 'Plan deleted successfully'
        })

    except Exception as e:
        print(f"Plan deletion error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_admin
def admin_plans(request):
    """
    COMBINED HANDLER for /api/admin/plans
    GET: List all plans
    POST: Create new plan
    """
    if request.method == "GET":
        return admin_get_plans(request)
    elif request.method == "POST":
        return admin_create_plan(request)
    elif request.method == "PUT":
        return admin_update_plan(request)
    elif request.method == "DELETE":
        return admin_plan_delete(request)

# ==================== PAYMENT APIS ====================
@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_admin
def admin_payments(request):
    """
    GET: List Pending Payments
    POST: Verify/Reject Payment (Legacy)
    """
    if request.method == "GET":
        try:
            payments = execute_query("""
                SELECT p.id, p.user_id, u.name AS user_name,
                       p.plan_id, pl.name AS plan_name, pl.type AS plan_type,
                       p.amount, p.payment_method, p.transaction_id,
                       p.created_at, p.status, p.admin_notes, p.screenshot
                FROM payments p
                JOIN users u ON p.user_id = u.id
                JOIN plans pl ON p.plan_id = pl.id
                WHERE p.status = 'pending'
                ORDER BY p.created_at DESC
            """)

            return JsonResponse({'payments': payments})

        except Exception as e:
            print(f"Payments fetch error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)

    elif request.method == "POST":
        # Legacy payment verification (prefer PUT /api/admin/payments/<id>)
        try:
            data = json.loads(request.body)
            payment_id = data.get('paymentId')
            status = data.get('status')
            admin_notes = data.get('adminNotes')

            if not all([payment_id, status]):
                return JsonResponse({
                    'error': 'Payment ID and status are required'
                }, status=400)

            if status not in ['verified', 'rejected']:
                return JsonResponse({'error': 'Invalid status'}, status=400)

            # Update payment
            execute_update("""
                UPDATE payments
                SET status = %s, admin_notes = %s, verified_by = %s, verified_at = NOW()
                WHERE id = %s AND status = 'pending'
            """, [status, admin_notes, request.user_data['userId'], payment_id])

            if status == 'rejected':
                return JsonResponse({'success': True})

            # Get payment details
            payment = execute_query("""
                SELECT p.user_id, p.plan_id, pl.type, pl.duration_months, pl.call_credits
                FROM payments p
                JOIN plans pl ON p.plan_id = pl.id
                WHERE p.id = %s
            """, [payment_id])

            if not payment:
                return JsonResponse({'error': 'Payment not found'}, status=404)

            p = payment[0]
            expires_at = datetime.now() + timedelta(days=30 * (p['duration_months'] or 1))

            if p['type'] == 'normal':
                execute_insert("""
                    INSERT INTO user_subscriptions
                    (user_id, plan_id, start_date, expires_at, status, created_at, updated_at)
                    VALUES (%s, %s, NOW(), %s, 'active', NOW(), NOW())
                """, [p['user_id'], p['plan_id'], expires_at])

            elif p['type'] == 'call':
                execute_insert("""
                    INSERT INTO user_call_credits
                    (user_id, plan_id, credits_purchased, credits_remaining, expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                """, [p['user_id'], p['plan_id'], p['call_credits'], p['call_credits'], expires_at])

            return JsonResponse({'success': True})

        except Exception as e:
            print(f"Payment verification error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["PUT"])
@require_admin
def admin_payment_detail(request, payment_id):
    """
    Verify/Reject Payment
    PUT /api/admin/payments/<payment_id>
    """
    try:
        data = json.loads(request.body)
        status = data.get('status')
        admin_notes = data.get('adminNotes')

        if status not in ['verified', 'rejected']:
            return JsonResponse({'error': 'Invalid status'}, status=400)

        # Get payment
        payment = execute_query("SELECT * FROM payments WHERE id = %s", [payment_id])
        if not payment:
            return JsonResponse({'error': 'Payment not found'}, status=404)

        p = payment[0]

        # Get plan
        plan = execute_query("SELECT * FROM plans WHERE id = %s", [p['plan_id']])
        if not plan:
            return JsonResponse({'error': 'Plan not found'}, status=404)

        pl = plan[0]

        # Update payment
        execute_update("""
            UPDATE payments
            SET status = %s, admin_notes = %s, verified_by = %s, verified_at = NOW()
            WHERE id = %s
        """, [status, admin_notes, request.user_data['userId'], payment_id])

        if status == 'rejected':
            return JsonResponse({
                'success': True,
                'message': 'Payment rejected successfully'
            })

        # Create subscription/credits
        expires_at = datetime.now() + timedelta(days=30 * pl['duration_months'])

        if pl['type'] == 'normal':
            # Check existing subscription
            existing = execute_query("""
                SELECT * FROM user_subscriptions
                WHERE user_id = %s AND status = 'active'
                    AND plan_id IN (SELECT id FROM plans WHERE type = 'normal')
                ORDER BY expires_at DESC LIMIT 1
            """, [p['user_id']])

            if existing:
                # Extend subscription
                new_expiry = existing[0]['expires_at'] + timedelta(days=30 * pl['duration_months'])
                execute_update("""
                    UPDATE user_subscriptions
                    SET expires_at = %s, plan_id = %s, updated_at = NOW()
                    WHERE id = %s
                """, [new_expiry, pl['id'], existing[0]['id']])
            else:
                # Create new subscription
                execute_insert("""
                    INSERT INTO user_subscriptions
                    (user_id, plan_id, start_date, expires_at, payment_method,
                     transaction_id, status, created_at)
                    VALUES (%s, %s, NOW(), %s, %s, %s, 'active', NOW())
                """, [p['user_id'], pl['id'], expires_at, p.get('payment_method'), p.get('transaction_id')])

        elif pl['type'] == 'call':
            # Check existing credits
            existing = execute_query("""
                SELECT * FROM user_call_credits
                WHERE user_id = %s AND expires_at > NOW() AND credits_remaining > 0
                ORDER BY expires_at DESC LIMIT 1
            """, [p['user_id']])

            if existing:
                # Add credits
                execute_update("""
                    UPDATE user_call_credits
                    SET credits_remaining = credits_remaining + %s,
                        credits_purchased = credits_purchased + %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, [pl['call_credits'], pl['call_credits'], existing[0]['id']])
            else:
                # Create new credits
                execute_insert("""
                    INSERT INTO user_call_credits
                    (user_id, plan_id, credits_purchased, credits_remaining, expires_at, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, [p['user_id'], pl['id'], pl['call_credits'], pl['call_credits'], expires_at])

        return JsonResponse({
            'success': True,
            'message': f"Payment verified and {'subscription' if pl['type'] == 'normal' else 'credits'} activated successfully"
        })

    except Exception as e:
        print(f"Payment verification error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


# ==================== ADDITIONAL ADMIN APIS(create profile , change password) ====================
@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def create_profile(request):
    """
    Admin Create Profile
    POST /api/admin/create-profile
    """
    try:
        data = json.loads(request.body)

        # Validate required fields
        required_fields = ['name', 'email', 'phone', 'age', 'gender', 'caste',
                          'religion', 'education', 'occupation', 'state', 'city',
                          'marital_status']

        for field in required_fields:
            if not data.get(field):
                return JsonResponse({'error': f'{field} is required'}, status=400)

        # Check duplicates
        existing_user = execute_query("SELECT id FROM users WHERE email = %s", [data['email']])
        if existing_user:
            return JsonResponse({'error': 'Email already exists'}, status=409)

        if data.get('phone'):
            existing_phone = execute_query("SELECT id FROM users WHERE phone = %s", [data['phone']])
            if existing_phone:
                return JsonResponse({'error': 'Phone number already exists'}, status=409)

        # Generate passwords
        default_password = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        recovery_password = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        hashed_password = hash_password(default_password)

        # Create user
        user_id = execute_insert("""
            INSERT INTO users (name, email, phone, password, recovery_password, role, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'user', 'active', NOW())
        """, [data['name'], data['email'], data.get('phone'), hashed_password, recovery_password])

        # Create profile
        execute_insert("""
            INSERT INTO user_profiles (
                user_id, age, gender, height, weight, caste, religion, mother_tongue,
                marital_status, education, occupation, income, state, city, family_type,
                family_status, about_me, partner_preferences, profile_photo, status, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'approved', NOW())
        """, [
            user_id, data['age'], data['gender'], data.get('height'), data.get('weight'),
            data['caste'], data['religion'], data.get('mother_tongue'), data['marital_status'],
            data['education'], data['occupation'], data.get('income'), data['state'], data['city'],
            data.get('family_type'), data.get('family_status'), data.get('about_me'),
            data.get('partner_preferences'), data.get('profile_photo')
        ])

        return JsonResponse({
            'success': True,
            'userId': user_id,
            'defaultPassword': default_password,
            'recoveryPassword': recovery_password,
            'message': 'Profile created successfully. User can login with the default password. Recovery password for admin use.'
        })

    except Exception as e:
        print(f"Admin profile creation error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def admin_change_password(request):
    """
    Admin Change Password
    POST /api/admin/change-password
    """
    try:
        data = json.loads(request.body)
        current_password = data.get('currentPassword')
        new_password = data.get('newPassword')

        if not all([current_password, new_password]):
            return JsonResponse({
                'error': 'Current password and new password are required'
            }, status=400)

        if len(new_password) < 6:
            return JsonResponse({
                'error': 'New password must be at least 6 characters long'
            }, status=400)

        # Get admin user
        user = execute_query(
            "SELECT id, password, role FROM users WHERE id = %s",
            [request.user_data['userId']]
        )

        if not user or user[0]['role'] != 'admin':
            return JsonResponse({'error': 'Access denied'}, status=403)

        # Verify current password
        if not verify_password(current_password, user[0]['password']):
            return JsonResponse({'error': 'Current password is incorrect'}, status=400)

        # Update password
        hashed_new_password = hash_password(new_password)
        execute_update(
            "UPDATE users SET password = %s, updated_at = NOW() WHERE id = %s",
            [hashed_new_password, request.user_data['userId']]
        )

        return JsonResponse({
            'success': True,
            'message': 'Password changed successfully'
        })

    except Exception as e:
        print(f"Password change error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)



# ==================== CREDITS MANAGEMENT ====================
@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def adjust_credits(request):
    """
    Adjust User Credits
    POST /api/admin/adjust-credits
    Body: { userId, action, credits, reason }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('userId')
        action = data.get('action')  # add, remove, set
        credits = data.get('credits')
        reason = data.get('reason')

        if not all([user_id, action, credits, reason]):
            return JsonResponse({
                'error': 'User ID, action, credits, and reason are required'
            }, status=400)

        if credits <= 0:
            return JsonResponse({'error': 'Credits must be positive'}, status=400)

        # Get current credits
        current = execute_query("""
            SELECT * FROM user_call_credits
            WHERE user_id = %s AND expires_at > NOW()
            ORDER BY expires_at DESC LIMIT 1
        """, [user_id])

        if not current and action != 'add':
            return JsonResponse({'error': 'User has no active credit allocation'}, status=400)

        old_balance = current[0]['credits_remaining'] if current else 0

        if action == 'add':
            if current:
                new_remaining = current[0]['credits_remaining'] + credits
                new_purchased = current[0]['credits_purchased'] + credits
                execute_update("""
                    UPDATE user_call_credits
                    SET credits_remaining = %s, credits_purchased = %s, updated_at = NOW()
                    WHERE user_id = %s AND id = %s
                """, [new_remaining, new_purchased, user_id, current[0]['id']])
            else:
                # Create new allocation
                expiry = datetime.now() + timedelta(days=90)  # 3 months
                execute_insert("""
                    INSERT INTO user_call_credits
                    (user_id, plan_id, credits_purchased, credits_remaining, expires_at,
                     admin_allocated, allocation_notes, created_at, updated_at)
                    VALUES (%s, NULL, %s, %s, %s, 1, %s, NOW(), NOW())
                """, [user_id, credits, credits, expiry, reason])
                new_remaining = credits
                new_purchased = credits

        elif action == 'remove':
            if credits > current[0]['credits_remaining']:
                return JsonResponse({
                    'error': f"Cannot remove {credits} credits. User only has {current[0]['credits_remaining']} remaining."
                }, status=400)
            new_remaining = current[0]['credits_remaining'] - credits
            new_purchased = current[0]['credits_purchased']
            execute_update("""
                UPDATE user_call_credits
                SET credits_remaining = %s, updated_at = NOW()
                WHERE user_id = %s AND id = %s
            """, [new_remaining, user_id, current[0]['id']])

        elif action == 'set':
            new_remaining = credits
            new_purchased = current[0]['credits_purchased']
            execute_update("""
                UPDATE user_call_credits
                SET credits_remaining = %s, updated_at = NOW()
                WHERE user_id = %s AND id = %s
            """, [new_remaining, user_id, current[0]['id']])
        else:
            return JsonResponse({'error': 'Invalid action'}, status=400)

        # Log adjustment
        execute_insert("""
            INSERT INTO credit_adjustments
            (user_id, admin_id, action, credits, reason, old_balance, new_balance, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, [user_id, request.user_data['userId'], action, credits, reason, old_balance, new_remaining])

        log_action = {'add': 'manual_add', 'remove': 'manual_remove', 'set': 'manual_set'}[action]
        execute_insert("""
            INSERT INTO exotel_credit_log (action, credits, user_id, admin_id, reason, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, [log_action, credits, user_id, request.user_data['userId'], reason])

        return JsonResponse({
            'success': True,
            'message': 'Credits adjusted successfully',
            'oldBalance': old_balance,
            'newBalance': new_remaining,
            'action': action,
            'creditsAdjusted': credits
        })

    except Exception as e:
        print(f"Credit adjustment error: {e}")
        return JsonResponse({'error': 'Failed to adjust credits'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def credit_distributions(request):
    """
    Get Credit Distributions
    GET /api/admin/credit-distributions
    """
    try:
        distributions = execute_query("""
            SELECT uc.user_id, u.name as user_name,
                   uc.credits_purchased as allocated_credits,
                   (uc.credits_purchased - uc.credits_remaining) as used_credits,
                   uc.credits_remaining,
                   uc.expires_at,
                   CASE
                       WHEN uc.expires_at > NOW() AND uc.credits_remaining > 0 THEN 'active'
                       WHEN uc.expires_at <= NOW() THEN 'expired'
                       WHEN uc.credits_remaining <= 0 THEN 'exhausted'
                       ELSE 'inactive'
                   END as status,
                   last_call.last_call_date as last_call
            FROM user_call_credits uc
            JOIN users u ON uc.user_id = u.id
            LEFT JOIN (
                SELECT caller_id as user_id, MAX(created_at) as last_call_date
                FROM call_sessions
                WHERE status = 'completed'
                GROUP BY caller_id
            ) last_call ON uc.user_id = last_call.user_id
            WHERE uc.credits_purchased > 0
            ORDER BY uc.updated_at DESC
        """)

        return JsonResponse({'distributions': distributions})

    except Exception as e:
        print(f"Credit distributions error: {e}")
        return JsonResponse({'error': 'Failed to fetch credit distributions'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def exotel_credits(request):
    """
    Get Exotel Credits
    GET /api/admin/exotel-credits
    """
    try:
        # Get config
        config = execute_query(
            "SELECT * FROM exotel_config ORDER BY updated_at DESC LIMIT 1"
        )

        if not config:
            # Create default config
            execute_insert("""
                INSERT INTO exotel_config (total_credits, cost_per_minute, monthly_limit, created_at, updated_at)
                VALUES (10000, 1.0, 5000, NOW(), NOW())
            """)
            config = execute_query("SELECT * FROM exotel_config ORDER BY updated_at DESC LIMIT 1")

        cfg = config[0]

        # Calculate used credits
        used_data = execute_query("""
            SELECT
                COALESCE(SUM(CEIL(duration/60) * %s), 0) as used_credits,
                COALESCE(SUM(CASE
                    WHEN MONTH(created_at) = MONTH(NOW()) AND YEAR(created_at) = YEAR(NOW())
                    THEN CEIL(duration/60) * %s ELSE 0 END), 0) as current_month_usage
            FROM call_sessions
            WHERE status = 'completed' AND duration > 0
        """, [cfg['cost_per_minute'], cfg['cost_per_minute']])

        used = used_data[0]

        return JsonResponse({
            'credits': {
                'total_credits': cfg['total_credits'],
                'used_credits': used['used_credits'],
                'remaining_credits': max(0, cfg['total_credits'] - used['used_credits']),
                'cost_per_minute': float(cfg['cost_per_minute']),
                'monthly_limit': cfg['monthly_limit'],
                'current_month_usage': used['current_month_usage'],
                'last_updated': str(cfg['updated_at'])
            }
        })

    except Exception as e:
        print(f"Exotel credits error: {e}")
        return JsonResponse({'error': 'Failed to fetch Exotel credits'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def exotel_settings(request):
    """
    Update Exotel Settings
    POST /api/admin/exotel-settings
    """
    try:
        data = json.loads(request.body)
        total_credits = data.get('totalCredits')
        cost_per_minute = data.get('costPerMinute')
        monthly_limit = data.get('monthlyLimit')

        if not all([total_credits, cost_per_minute, monthly_limit]):
            return JsonResponse({
                'error': 'Total credits, cost per minute, and monthly limit are required'
            }, status=400)

        if any(v <= 0 for v in [total_credits, cost_per_minute, monthly_limit]):
            return JsonResponse({'error': 'All values must be positive'}, status=400)

        # Check if config exists
        existing = execute_query("SELECT id FROM exotel_config LIMIT 1")

        if existing:
            execute_update("""
                UPDATE exotel_config
                SET total_credits = %s, cost_per_minute = %s, monthly_limit = %s, updated_at = NOW()
                WHERE id = (SELECT id FROM exotel_config LIMIT 1)
            """, [total_credits, cost_per_minute, monthly_limit])
        else:
            execute_insert("""
                INSERT INTO exotel_config (total_credits, cost_per_minute, monthly_limit, created_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
            """, [total_credits, cost_per_minute, monthly_limit])

        # Log change
        execute_insert("""
            INSERT INTO exotel_credit_log (action, credits, admin_id, reason, created_at)
            VALUES ('settings_update', %s, %s, %s, NOW())
        """, [total_credits, request.user_data['userId'],
              f"Updated Exotel settings: {total_credits} credits, ₹{cost_per_minute}/min, {monthly_limit} monthly limit"])

        return JsonResponse({
            'success': True,
            'message': 'Exotel settings updated successfully'
        })

    except Exception as e:
        print(f"Exotel settings error: {e}")
        return JsonResponse({'error': 'Failed to update Exotel settings'}, status=500)

# ==================== MATCHES MANAGEMENT ====================
@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
@require_admin
def admin_matches(request):
    """
    Matches Management
    GET: Get potential matches for user
    POST: Create matches
    DELETE: Delete match
    """
    if request.method == "GET":
        try:
            user_id = request.GET.get('userId')
            if not user_id:
                return JsonResponse({'error': 'User ID is required'}, status=400)

            # Get user profile
            user_profile = execute_query("""
                SELECT u.name, up.gender, up.age, up.caste, up.religion, up.state
                FROM user_profiles up
                JOIN users u ON up.user_id = u.id
                WHERE up.user_id = %s
            """, [user_id])

            if not user_profile:
                return JsonResponse({'error': 'User profile not found'}, status=404)

            up = user_profile[0]
            opposite_gender = 'Female' if up['gender'] == 'Male' else 'Male'

            # Get potential matches
            potential = execute_query("""
                SELECT u.id, u.name, u.email,
                       up.age, up.gender, up.caste, up.religion, up.state, up.city,
                       up.occupation, up.education, up.profile_photo,
                       CASE WHEN m.id IS NOT NULL THEN 1 ELSE 0 END as already_matched
                FROM users u
                JOIN user_profiles up ON u.id = up.user_id
                LEFT JOIN matches m ON (m.user_id = %s AND m.matched_user_id = u.id)
                WHERE u.id != %s
                    AND up.gender = %s
                    AND up.status = 'approved'
                    AND u.status = 'active'
                    AND u.role = 'user'
                ORDER BY
                    already_matched ASC,
                    CASE WHEN up.religion = %s THEN 1 ELSE 2 END,
                    CASE WHEN up.state = %s THEN 1 ELSE 2 END,
                    CASE WHEN up.caste = %s THEN 1 ELSE 2 END,
                    ABS(up.age - %s) ASC
            """, [user_id, user_id, opposite_gender, up['religion'], up['state'], up['caste'], up['age']])

            # Get current matches
            current = execute_query("""
                SELECT u.id, u.name, up.age, up.gender, up.caste, up.state, up.city,
                       m.created_at as matched_at
                FROM matches m
                JOIN users u ON m.matched_user_id = u.id
                JOIN user_profiles up ON u.id = up.user_id
                WHERE m.user_id = %s
                ORDER BY m.created_at DESC
            """, [user_id])

            return JsonResponse({
                'potentialMatches': potential,
                'currentMatches': current,
                'userProfile': up
            })

        except Exception as e:
            print(f"Matches fetch error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)

    elif request.method == "POST":
        try:
            data = json.loads(request.body)
            user_id = data.get('userId')
            matched_user_ids = data.get('matchedUserIds')

            if not user_id or not matched_user_ids or not isinstance(matched_user_ids, list):
                return JsonResponse({
                    'error': 'User ID and matched user IDs are required'
                }, status=400)

            # Create bidirectional matches
            for matched_id in matched_user_ids:
                # User to matched
                execute_query("""
                    INSERT IGNORE INTO matches (user_id, matched_user_id, created_by_admin)
                    VALUES (%s, %s, %s)
                """, [user_id, matched_id, request.user_data['userId']])

                # Matched to user (bidirectional)
                execute_query("""
                    INSERT IGNORE INTO matches (user_id, matched_user_id, created_by_admin)
                    VALUES (%s, %s, %s)
                """, [matched_id, user_id, request.user_data['userId']])

            return JsonResponse({
                'success': True,
                'message': f'Created {len(matched_user_ids)} bidirectional matches successfully'
            })

        except Exception as e:
            print(f"Match creation error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)

    elif request.method == "DELETE":
        try:
            data = json.loads(request.body)
            user_id = data.get('userId')
            matched_user_id = data.get('matchedUserId')

            if not user_id or not matched_user_id:
                return JsonResponse({
                    'error': 'User ID and matched user ID are required'
                }, status=400)

            # Delete both directions
            execute_update("""
                DELETE FROM matches
                WHERE (user_id = %s AND matched_user_id = %s)
                   OR (user_id = %s AND matched_user_id = %s)
            """, [user_id, matched_user_id, matched_user_id, user_id])

            return JsonResponse({'success': True})

        except Exception as e:
            print(f"Match deletion error: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)


# ==================== BLOCKS MANAGEMENT ====================
@csrf_exempt
@require_http_methods(["GET", "DELETE", "PATCH"])
@require_admin
def admin_blocks(request):
    """
    Blocks Management
    GET: List all blocks
    DELETE: Admin unblock
    PATCH: Toggle call permission
    """
    if request.method == "GET":
        try:
            blocks = execute_query("""
                SELECT ub.id, ub.blocker_id, ub.blocked_id, ub.call_allowed,
                       ub.created_at, ub.updated_at,
                       blocker.name as blocker_name, blocker.email as blocker_email,
                       blocker_profile.profile_photo as blocker_photo,
                       blocked.name as blocked_name, blocked.email as blocked_email,
                       blocked_profile.profile_photo as blocked_photo
                FROM user_blocks ub
                JOIN users blocker ON ub.blocker_id = blocker.id
                JOIN users blocked ON ub.blocked_id = blocked.id
                LEFT JOIN user_profiles blocker_profile ON blocker.id = blocker_profile.user_id
                LEFT JOIN user_profiles blocked_profile ON blocked.id = blocked_profile.user_id
                ORDER BY ub.created_at DESC
            """)

            return JsonResponse({'success': True, 'blocks': blocks})

        except Exception as e:
            print(f"Blocks fetch error: {e}")
            return JsonResponse({'error': 'Failed to fetch blocks'}, status=500)

    elif request.method == "DELETE":
        try:
            data = json.loads(request.body)
            block_id = data.get('blockId')

            if not block_id:
                return JsonResponse({'error': 'Block ID is required'}, status=400)

            rows = execute_update("DELETE FROM user_blocks WHERE id = %s", [block_id])

            if rows == 0:
                return JsonResponse({'error': 'Block record not found'}, status=404)

            return JsonResponse({
                'success': True,
                'message': 'Block removed successfully by admin'
            })

        except Exception as e:
            print(f"Unblock error: {e}")
            return JsonResponse({'error': 'Failed to remove block'}, status=500)

    elif request.method == "PATCH":
        try:
            data = json.loads(request.body)
            block_id = data.get('blockId')
            call_allowed = data.get('callAllowed')

            if not block_id or call_allowed is None:
                return JsonResponse({
                    'error': 'Block ID and callAllowed status are required'
                }, status=400)

            rows = execute_update("""
                UPDATE user_blocks SET call_allowed = %s, updated_at = NOW()
                WHERE id = %s
            """, [1 if call_allowed else 0, block_id])

            if rows == 0:
                return JsonResponse({'error': 'Block record not found'}, status=404)

            return JsonResponse({
                'success': True,
                'message': f"Call permission {'enabled' if call_allowed else 'disabled'} successfully",
                'callAllowed': call_allowed
            })

        except Exception as e:
            print(f"Toggle call permission error: {e}")
            return JsonResponse({'error': 'Failed to update call permission'}, status=500)



# ==================== CALL SESSIONS ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_call_sessions(request):
    """
    Get Call Sessions
    GET /api/admin/call-sessions
    """
    try:
        sessions = execute_query("""
            SELECT cs.*, caller.name as caller_name, receiver.name as receiver_name,
                   caller.phone as caller_phone, receiver.phone as receiver_phone
            FROM call_sessions cs
            JOIN users caller ON cs.caller_id = caller.id
            JOIN users receiver ON cs.receiver_id = receiver.id
            ORDER BY cs.created_at DESC
            LIMIT 100
        """)

        formatted = []
        for row in sessions:
            formatted.append({
                'id': row['id'],
                'caller_name': row['caller_name'],
                'receiver_name': row['receiver_name'],
                'caller_phone': row['caller_phone'],
                'receiver_phone': row['receiver_phone'],
                'status': row['status'],
                'duration': row['duration'] or 0,
                'cost': float(row['cost']) if row['cost'] else 0,
                'created_at': str(row['created_at']),
                'ended_at': str(row['ended_at']) if row['ended_at'] else None,
                'caller_virtual_number': row['caller_virtual_number'],
                'receiver_virtual_number': row['receiver_virtual_number']
            })

        return JsonResponse({'sessions': formatted})

    except Exception as e:
        print(f"Call sessions error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

# ==================== CALL SUBSCRIPTIONS ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def call_subscriptions(request):
    """
    Get Call Subscriptions
    GET /api/admin/call-subscriptions
    """
    try:
        subscriptions = execute_query("""
            SELECT
                p.*,
                u.name as user_name,
                u.email as user_email,
                u.phone as user_phone,
                up.profile_photo as user_photo,
                pl.name as plan_name,
                pl.call_credits as plan_credits,
                uc.credits_purchased,
                uc.credits_remaining,
                (uc.credits_purchased - uc.credits_remaining) as credits_used,
                uc.expires_at,
                CASE WHEN uc.expires_at > NOW() AND uc.credits_remaining > 0 THEN 1 ELSE 0 END as is_active,
                COALESCE(call_stats.total_calls, 0) as total_calls_made,
                COALESCE(call_stats.total_duration, 0) as total_call_duration,
                admin.name as verified_by,
                p.verified_at
            FROM payments p
            JOIN users u ON p.user_id = u.id
            JOIN user_profiles up ON u.id = up.user_id
            JOIN plans pl ON p.plan_id = pl.id AND pl.type = 'call'
            LEFT JOIN user_call_credits uc ON p.user_id = uc.user_id AND p.plan_id = uc.plan_id
            LEFT JOIN users admin ON p.verified_by = admin.id
            LEFT JOIN (
                SELECT caller_id as user_id,
                       COUNT(*) as total_calls,
                       SUM(CASE WHEN duration > 0 THEN duration ELSE 0 END) as total_duration
                FROM call_sessions
                WHERE status = 'completed'
                GROUP BY caller_id
            ) call_stats ON p.user_id = call_stats.user_id
            ORDER BY p.created_at DESC
        """)

        formatted = []
        for row in subscriptions:
            formatted.append({
                'id': row['id'],
                'user_id': row['user_id'],
                'user_name': row['user_name'],
                'user_email': row['user_email'],
                'user_phone': row['user_phone'],
                'user_photo': row['user_photo'],
                'plan_name': row['plan_name'],
                'plan_id': row['plan_id'],
                'credits_purchased': row['credits_purchased'] or row['plan_credits'] or 0,
                'credits_remaining': row['credits_remaining'] or 0,
                'credits_used': row['credits_used'] or 0,
                'amount_paid': float(row['amount']) if row['amount'] else 0,
                'payment_status': row['status'],
                'payment_screenshot': row.get('screenshot'),
                'transaction_id': row.get('transaction_id'),
                'admin_notes': row.get('admin_notes', ''),
                'expires_at': str(row['expires_at']) if row['expires_at'] else None,
                'created_at': str(row['created_at']),
                'verified_at': str(row['verified_at']) if row['verified_at'] else None,
                'verified_by': row['verified_by'],
                'is_active': row['is_active'] == 1,
                'total_call_duration': int(row['total_call_duration']) if row['total_call_duration'] else 0,
                'total_calls_made': int(row['total_calls_made']) if row['total_calls_made'] else 0
            })

        return JsonResponse({'subscriptions': formatted})

    except Exception as e:
        print(f"Call subscriptions error: {e}")
        return JsonResponse({'error': 'Failed to fetch call subscriptions'}, status=500)


# ==================== VERIFY CALL PAYMENT ====================
@csrf_exempt
@require_http_methods(["POST"])
@require_admin
def verify_call_payment(request):
    """
    Verify Call Payment
    POST /api/admin/verify-call-payment
    """
    try:
        from datetime import datetime, timedelta

        data = json.loads(request.body)
        subscription_id = data.get('subscriptionId')
        action = data.get('action')
        admin_notes = data.get('adminNotes')

        if not subscription_id or not action:
            return JsonResponse({
                'error': 'Subscription ID and action are required'
            }, status=400)

        # Get payment details
        payment = execute_query("""
            SELECT p.*, pl.call_credits, pl.name as plan_name
            FROM payments p
            JOIN plans pl ON p.plan_id = pl.id
            WHERE p.id = %s AND pl.type = 'call'
        """, [subscription_id])

        if not payment:
            return JsonResponse({'error': 'Payment not found'}, status=404)

        p = payment[0]
        new_status = 'verified' if action == 'verify' else 'rejected'

        # Update payment status
        execute_update("""
            UPDATE payments
            SET status = %s, admin_notes = %s, verified_by = %s, verified_at = NOW()
            WHERE id = %s
        """, [new_status, admin_notes, request.user_data['userId'], subscription_id])

        if action == 'verify':
            # Create or update credits
            existing = execute_query(
                "SELECT * FROM user_call_credits WHERE user_id = %s AND plan_id = %s",
                [p['user_id'], p['plan_id']]
            )

            expiration_date = datetime.now() + timedelta(days=90)  # 3 months

            if existing:
                execute_update("""
                    UPDATE user_call_credits
                    SET credits_remaining = credits_remaining + %s,
                        credits_purchased = credits_purchased + %s,
                        expires_at = %s,
                        updated_at = NOW()
                    WHERE user_id = %s AND plan_id = %s
                """, [p['call_credits'], p['call_credits'], expiration_date, p['user_id'], p['plan_id']])
            else:
                execute_insert("""
                    INSERT INTO user_call_credits
                    (user_id, plan_id, credits_purchased, credits_remaining, expires_at, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                """, [p['user_id'], p['plan_id'], p['call_credits'], p['call_credits'], expiration_date])

            # Log credit allocation
            execute_insert("""
                INSERT INTO exotel_credit_log (action, credits, user_id, admin_id, reason, created_at)
                VALUES ('allocated', %s, %s, %s, %s, NOW())
            """, [p['call_credits'], p['user_id'], request.user_data['userId'],
                  f"Payment verified: {p['plan_name']}"])

        return JsonResponse({
            'success': True,
            'message': 'Payment verified and credits activated' if action == 'verify' else 'Payment rejected',
            'status': new_status
        })

    except Exception as e:
        print(f"Payment verification error: {e}")
        return JsonResponse({'error': 'Failed to process payment verification'}, status=500)


# ==================== MISSING: ADMIN USER CALL LOGS ====================
@csrf_exempt
@require_http_methods(["GET"])
@require_admin
def admin_user_call_logs(request):
    """
    Get User Call Logs (Admin)
    GET /api/admin/user-call-logs?userId=<id>&page=<page>&limit=<limit>
    """
    try:
        user_id = request.GET.get('userId')
        page = int(request.GET.get('page', 1))
        limit = min(100, max(1, int(request.GET.get('limit', 20))))
        offset = (page - 1) * limit

        if user_id:
            # Get specific user's call logs
            call_logs_query = f"""
                SELECT
                    cs.id as session_id,
                    cs.caller_id,
                    cs.receiver_id,
                    cs.status,
                    COALESCE(cs.duration, 0) as duration,
                    COALESCE(cs.cost, 0) as cost,
                    cs.caller_virtual_number,
                    cs.receiver_virtual_number,
                    COALESCE(cs.started_at, cs.created_at) as started_at,
                    cs.ended_at,
                    cs.created_at
                FROM call_sessions cs
                WHERE (cs.caller_id = %s OR cs.receiver_id = %s)
                ORDER BY cs.created_at DESC
                LIMIT {limit} OFFSET {offset}
            """

            call_logs = execute_query(call_logs_query, [user_id, user_id])

            # Enrich with user details
            enriched = []
            for log in call_logs:
                other_user_id = log['receiver_id'] if log['caller_id'] == int(user_id) else log['caller_id']
                call_type = 'outgoing' if log['caller_id'] == int(user_id) else 'incoming'

                other_user = execute_query(
                    "SELECT name, phone FROM users WHERE id = %s",
                    [other_user_id]
                )

                photo = execute_query(
                    "SELECT profile_photo FROM user_profiles WHERE user_id = %s",
                    [other_user_id]
                )

                caller = execute_query("SELECT name FROM users WHERE id = %s", [log['caller_id']])
                receiver = execute_query("SELECT name FROM users WHERE id = %s", [log['receiver_id']])

                enriched.append({
                    'session_id': log['session_id'],
                    'call_type': call_type,
                    'other_party_name': other_user[0]['name'] if other_user else 'Unknown',
                    'other_party_phone': other_user[0]['phone'] if other_user else 'Unknown',
                    'other_party_photo': photo[0]['profile_photo'] if photo else None,
                    'status': log['status'],
                    'duration': int(log['duration']),
                    'cost': float(log['cost']),
                    'virtual_number': log['caller_virtual_number'] if call_type == 'outgoing' else log['receiver_virtual_number'],
                    'started_at': str(log['started_at']),
                    'ended_at': str(log['ended_at']) if log['ended_at'] else None,
                    'created_at': str(log['created_at']),
                    'caller_name': caller[0]['name'] if caller else 'Unknown',
                    'receiver_name': receiver[0]['name'] if receiver else 'Unknown'
                })

            # Get total count
            total_count = execute_query(
                "SELECT COUNT(*) as total FROM call_sessions WHERE (caller_id = %s OR receiver_id = %s)",
                [user_id, user_id]
            )

            return JsonResponse({
                'callLogs': enriched,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total_count[0]['total'] if total_count else 0,
                    'totalPages': (total_count[0]['total'] + limit - 1) // limit if total_count else 0
                }
            })

        else:
            # Get all users with call activity
            users_query = f"""
                SELECT DISTINCT u.id, u.name, u.email, u.phone
                FROM users u
                WHERE u.role = 'user'
                AND u.id IN (
                    SELECT DISTINCT caller_id FROM call_sessions
                    UNION
                    SELECT DISTINCT receiver_id FROM call_sessions
                )
                ORDER BY u.id
                LIMIT {limit} OFFSET {offset}
            """

            users = execute_query(users_query)

            enriched_users = []
            for user in users:
                # Get profile photo
                profile = execute_query(
                    "SELECT profile_photo FROM user_profiles WHERE user_id = %s",
                    [user['id']]
                )

                # Get call stats
                outgoing = execute_query(
                    "SELECT COUNT(*) as count FROM call_sessions WHERE caller_id = %s",
                    [user['id']]
                )

                incoming = execute_query(
                    "SELECT COUNT(*) as count FROM call_sessions WHERE receiver_id = %s",
                    [user['id']]
                )

                completed = execute_query(
                    "SELECT COUNT(*) as count FROM call_sessions WHERE (caller_id = %s OR receiver_id = %s) AND status = 'completed'",
                    [user['id'], user['id']]
                )

                stats = execute_query("""
                    SELECT
                        SUM(CASE WHEN status = 'completed' THEN CEIL(COALESCE(duration, 0)/60) ELSE 0 END) as minutes,
                        SUM(COALESCE(cost, 0)) as total_cost,
                        AVG(CASE WHEN status = 'completed' AND duration > 0 THEN duration END) as avg_duration,
                        MAX(created_at) as last_call
                    FROM call_sessions
                    WHERE caller_id = %s OR receiver_id = %s
                """, [user['id'], user['id']])

                credits = execute_query("""
                    SELECT credits_remaining, credits_purchased, expires_at
                    FROM user_call_credits
                    WHERE user_id = %s AND expires_at > NOW()
                    ORDER BY expires_at DESC
                    LIMIT 1
                """, [user['id']])

                s = stats[0] if stats else {}
                c = credits[0] if credits else {}

                enriched_users.append({
                    'id': user['id'],
                    'name': user['name'],
                    'email': user['email'],
                    'phone': user['phone'],
                    'profile_photo': profile[0]['profile_photo'] if profile else None,
                    'outgoing_calls': outgoing[0]['count'] if outgoing else 0,
                    'incoming_calls': incoming[0]['count'] if incoming else 0,
                    'total_calls': (outgoing[0]['count'] if outgoing else 0) + (incoming[0]['count'] if incoming else 0),
                    'completed_outgoing': 0,
                    'completed_incoming': 0,
                    'completed_calls': completed[0]['count'] if completed else 0,
                    'total_minutes': int(s.get('minutes', 0) or 0),
                    'avg_call_duration': int(s.get('avg_duration', 0) or 0),
                    'total_cost': float(s.get('total_cost', 0) or 0),
                    'last_call_date': str(s['last_call']) if s.get('last_call') else None,
                    'credits_remaining': c.get('credits_remaining', 0),
                    'credits_purchased': c.get('credits_purchased', 0),
                    'credits_expire': str(c['expires_at']) if c.get('expires_at') else None,
                    'has_active_credits': bool(c.get('credits_remaining', 0) > 0 and c.get('expires_at'))
                })

            # Get total count
            total = execute_query("""
                SELECT COUNT(DISTINCT u.id) as total
                FROM users u
                WHERE u.role = 'user'
                AND u.id IN (
                    SELECT DISTINCT caller_id FROM call_sessions
                    UNION
                    SELECT DISTINCT receiver_id FROM call_sessions
                )
            """)

            return JsonResponse({
                'users': enriched_users,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total[0]['total'] if total else 0,
                    'totalPages': (total[0]['total'] + limit - 1) // limit if total else 0
                }
            })

    except Exception as e:
        print(f"User call logs error: {e}")
        return JsonResponse({'error': 'Failed to fetch user call logs'}, status=500)


# ====================  SEARCH VISIBILITY ====================
@csrf_exempt
@require_http_methods(["GET", "POST", "DELETE"])
@require_admin
def search_visibility(request):
    """
    Search Visibility Management
    GET: List all settings
    POST: Create/Update setting
    DELETE: Remove setting
    """
    if request.method == "GET":
        try:
            settings = execute_query(
                "SELECT * FROM search_visibility_settings ORDER BY state, gender"
            )
            return JsonResponse({'settings': settings})
        except Exception as e:
            print(f"Fetch visibility error: {e}")
            return JsonResponse({'error': 'Failed to fetch settings'}, status=500)

    elif request.method == "POST":
        try:
            data = json.loads(request.body)
            state = data.get('state')
            gender = data.get('gender')
            visible_count = data.get('visible_count')

            if not all([state, gender, visible_count is not None]):
                return JsonResponse({
                    'error': 'State, gender, and visible_count are required'
                }, status=400)

            if visible_count < 0:
                return JsonResponse({
                    'error': 'Visible count cannot be negative'
                }, status=400)

            # Check if exists
            existing = execute_query(
                "SELECT id FROM search_visibility_settings WHERE state = %s AND gender = %s",
                [state, gender]
            )

            if existing:
                execute_update("""
                    UPDATE search_visibility_settings
                    SET visible_count = %s, updated_at = NOW()
                    WHERE state = %s AND gender = %s
                """, [visible_count, state, gender])
            else:
                execute_insert("""
                    INSERT INTO search_visibility_settings (state, gender, visible_count, created_at, updated_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                """, [state, gender, visible_count])

            return JsonResponse({
                'message': 'Visibility setting updated successfully',
                'data': {'state': state, 'gender': gender, 'visible_count': visible_count}
            })

        except Exception as e:
            print(f"Update visibility error: {e}")
            return JsonResponse({'error': 'Failed to update setting'}, status=500)

    elif request.method == "DELETE":
        try:
            setting_id = request.GET.get('id')
            if not setting_id:
                return JsonResponse({'error': 'ID is required'}, status=400)

            execute_update("DELETE FROM search_visibility_settings WHERE id = %s", [setting_id])

            return JsonResponse({'message': 'Setting deleted successfully'})

        except Exception as e:
            print(f"Delete visibility error: {e}")
            return JsonResponse({'error': 'Failed to delete setting'}, status=500)
