import json
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from api.utils import require_user
from api.db_utils import execute_query, execute_insert


@csrf_exempt
@require_http_methods(["GET"])
def get_plans(request):
    """
    Get Active Plans (Public)
    GET /api/plans
    """
    try:
        plans = execute_query("""
            SELECT * FROM plans
            WHERE is_active = 1
            ORDER BY type, price ASC
        """)

        # Parse features
        formatted_plans = []
        for plan in plans:
            plan_data = dict(plan)
            if plan_data.get('features'):
                plan_data['features'] = [
                    f.strip() for f in plan_data['features'].split(',')
                    if f.strip()
                ]
            else:
                plan_data['features'] = None
            formatted_plans.append(plan_data)

        return JsonResponse({'plans': formatted_plans})

    except Exception as e:
        print(f"Plans fetch error: {e}")
        return JsonResponse({'error': 'Failed to fetch plans'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
@require_user
def submit_payment(request):
    """
    Submit Payment for Verification
    POST /api/payments/submit
    Body: { planId, transactionId, screenshot }
    """
    try:
        user_id = request.user_data['userId']
        data = json.loads(request.body)
        plan_id = data.get('planId')
        transaction_id = data.get('transactionId')
        screenshot = data.get('screenshot')

        if not plan_id or not transaction_id:
            return JsonResponse({
                'error': 'Plan ID and transaction ID are required'
            }, status=400)

        # Check duplicate transaction
        existing = execute_query(
            "SELECT id FROM payments WHERE transaction_id = %s",
            [transaction_id]
        )

        if existing:
            return JsonResponse({'error': 'Transaction ID already exists'}, status=409)

        # Get plan details
        plan = execute_query(
            "SELECT id, name, price FROM plans WHERE id = %s AND is_active = true",
            [plan_id]
        )

        if not plan:
            return JsonResponse({'error': 'Plan not found'}, status=404)

        # Create payment record
        execute_insert("""
            INSERT INTO payments
            (user_id, plan_id, transaction_id, amount, screenshot, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', NOW())
        """, [user_id, plan_id, transaction_id, plan[0]['price'], screenshot])

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Payment submission error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def payment_history(request):
    """
    Get Payment History
    GET /api/payments
    """
    try:
        user_id = request.user_data['userId']

        payments = execute_query("""
            SELECT p.id, p.transaction_id, p.amount, p.status, p.admin_notes,
                   p.created_at, p.verified_at,
                   pl.name as plan_name, pl.duration_months
            FROM payments p
            JOIN plans pl ON p.plan_id = pl.id
            WHERE p.user_id = %s
            ORDER BY p.created_at DESC
        """, [user_id])

        return JsonResponse({'payments': payments})

    except Exception as e:
        print(f"Payment history error: {e}")
        return JsonResponse({'error': 'Internal server error'}, status=500)
