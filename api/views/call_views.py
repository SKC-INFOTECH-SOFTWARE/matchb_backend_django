import json
import base64
import requests
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from api.utils import require_user
from api.db_utils import execute_query, execute_insert, execute_update

def initiate_exotel_call(caller_number, receiver_number, user_id, target_user_id):
    """Helper function to initiate Exotel call"""
    try:
        url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{settings.EXOTEL_SID}/Calls/connect.json"

        custom_field = json.dumps({
            'userId': user_id,
            'targetUserId': target_user_id,
            'timestamp': str(int(__import__('time').time() * 1000))
        })

        data = {
            'From': caller_number,
            'To': receiver_number,
            'CallerId': settings.EXOTEL_VIRTUAL_NUMBER,
            'CallType': 'trans',
            'TimeLimit': '3600',
            'TimeOut': '30',
            'StatusCallback': f"{settings.APP_URL}/api/calls/webhook",
            'StatusCallbackEvents[0]': 'terminal',
            'StatusCallbackEvents[1]': 'answered',
            'StatusCallbackContentType': 'application/json',
            'Record': 'true',
            'CustomField': custom_field
        }

        auth_string = f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}"
        auth_header = base64.b64encode(auth_string.encode()).decode()

        headers = {
            'Authorization': f'Basic {auth_header}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }

        response = requests.post(url, data=data, headers=headers)
        result = response.json()

        if response.ok and result.get('Call', {}).get('Sid'):
            return {
                'success': True,
                'callSid': result['Call']['Sid'],
                'status': result['Call']['Status'],
                'virtualNumber': settings.EXOTEL_VIRTUAL_NUMBER
            }
        else:
            raise Exception(result.get('RestException', {}).get('Message') or 'Exotel API call failed')

    except Exception as e:
        print(f"Exotel API error: {e}")
        raise


@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_user
def initiate_call(request):
    """
    Initiate Call or Fetch Call Sessions
    POST /api/calls/initiate - Initiate a new call
    Body: { targetUserId }

    GET /api/calls/initiate - Fetch call sessions
    Query Params:
    - logs=true: Fetch all recent call sessions (logs)
    - callSessionId: Fetch specific by ID
    - exotelCallSid: Fetch specific by Exotel SID
    """
    try:
        user_id = request.user_data['userId']
        if request.method == 'POST':
            data = json.loads(request.body)
            target_user_id = data.get('targetUserId')
            if not target_user_id:
                return JsonResponse({'error': 'Valid target user ID is required'}, status=400)
            # Check Exotel config
            if not all([settings.EXOTEL_SID, settings.EXOTEL_API_KEY,
                       settings.EXOTEL_API_TOKEN, settings.EXOTEL_VIRTUAL_NUMBER]):
                return JsonResponse({
                    'error': 'Call service not configured',
                    'code': 'CONFIG_ERROR'
                }, status=500)
            # Check caller credits
            caller_credits = execute_query("""
                SELECT id, credits_remaining, expires_at
                FROM user_call_credits
                WHERE user_id = %s AND credits_remaining > 0 AND expires_at > NOW()
                ORDER BY expires_at ASC
                LIMIT 1
            """, [user_id])
            if not caller_credits:
                return JsonResponse({
                    'error': "You don't have active call credits. Please purchase a call plan.",
                    'code': 'NO_CREDITS'
                }, status=403)
            # Check receiver credits
            receiver_credits = execute_query("""
                SELECT id, credits_remaining
                FROM user_call_credits
                WHERE user_id = %s AND credits_remaining > 0 AND expires_at > NOW()
                LIMIT 1
            """, [target_user_id])
            if not receiver_credits:
                return JsonResponse({
                    'error': "The user you're trying to call doesn't have active call credits.",
                    'code': 'TARGET_NO_CREDITS'
                }, status=403)
            # Get user details
            users = execute_query("""
                SELECT u.id, u.name, u.phone, u.status, up.profile_photo
                FROM users u
                JOIN user_profiles up ON u.id = up.user_id
                WHERE u.id IN (%s, %s) AND u.status = 'active'
            """, [user_id, target_user_id])
            if len(users) != 2:
                return JsonResponse({'error': 'One or both users not found'}, status=404)
            caller = next(u for u in users if u['id'] == user_id)
            receiver = next(u for u in users if u['id'] == target_user_id)
            if not caller['phone'] or not receiver['phone']:
                return JsonResponse({
                    'error': 'Phone numbers are required for both users',
                    'code': 'MISSING_PHONE'
                }, status=400)
            # Check if matched
            match_check = execute_query("""
                SELECT id FROM matches
                WHERE (user_id = %s AND matched_user_id = %s)
                   OR (user_id = %s AND matched_user_id = %s)
                LIMIT 1
            """, [user_id, target_user_id, target_user_id, user_id])
            if not match_check:
                return JsonResponse({
                    'error': "You can only call users you've matched with",
                    'code': 'NOT_MATCHED'
                }, status=403)
            # Initiate Exotel call
            exotel_result = initiate_exotel_call(
                caller['phone'],
                receiver['phone'],
                user_id,
                target_user_id
            )
            # Create call session
            call_session_id = execute_insert("""
                INSERT INTO call_sessions (
                    caller_id, receiver_id, exotel_call_sid, status,
                    caller_virtual_number, receiver_virtual_number,
                    caller_real_number, receiver_real_number,
                    cost_per_minute, created_at, updated_at
                ) VALUES (%s, %s, %s, 'initiated', %s, %s, %s, %s, 1.0, NOW(), NOW())
            """, [
                user_id, target_user_id, exotel_result['callSid'],
                settings.EXOTEL_VIRTUAL_NUMBER, settings.EXOTEL_VIRTUAL_NUMBER,
                caller['phone'], receiver['phone']
            ])
            # Log credit events
            execute_insert("""
                INSERT INTO exotel_credit_log
                (action, credits, user_id, call_session_id, reason, created_at)
                VALUES
                    ('call_initiated', 0, %s, %s, 'Call initiated to Exotel', NOW()),
                    ('call_initiated', 0, %s, %s, 'Call initiated to Exotel', NOW())
            """, [user_id, call_session_id, target_user_id, call_session_id])
            return JsonResponse({
                'success': True,
                'callSessionId': call_session_id,
                'message': 'Call initiated successfully',
                'status': 'initiated',
                'callerName': caller['name'],
                'receiverName': receiver['name'],
                'instructions': 'Exotel will call both users automatically. Please answer your phone when it rings.',
                'exotelCallSid': exotel_result['callSid']
            })
        else:  # GET
            call_session_id = request.GET.get('callSessionId')
            exotel_call_sid = request.GET.get('exotelCallSid')
            fetch_logs = request.GET.get('logs') == 'true'
            if fetch_logs:
                query = """
                    SELECT cs.id, cs.caller_id, cs.receiver_id, cs.exotel_call_sid, cs.status,
                           cs.duration, cs.cost, cs.recording_url, cs.conversation_duration,
                           cs.started_at, cs.ended_at, cs.created_at, cs.updated_at,
                           u1.name AS caller_name, u2.name AS receiver_name,
                           up1.profile_photo AS caller_photo, up2.profile_photo AS receiver_photo
                    FROM call_sessions cs
                    JOIN users u1 ON cs.caller_id = u1.id
                    JOIN users u2 ON cs.receiver_id = u2.id
                    LEFT JOIN user_profiles up1 ON cs.caller_id = up1.user_id
                    LEFT JOIN user_profiles up2 ON cs.receiver_id = up2.user_id
                    WHERE cs.caller_id = %s OR cs.receiver_id = %s
                    ORDER BY cs.created_at DESC
                    LIMIT 50
                """
                rows = execute_query(query, [user_id, user_id])
                call_sessions = [
                    {
                        'id': row['id'],
                        'exotelCallSid': row['exotel_call_sid'],
                        'status': row['status'],
                        'duration': row['duration'] or 0,
                        'cost': row['cost'] or 0,
                        'recording_url': row['recording_url'],
                        'conversation_duration': row['conversation_duration'] or 0,
                        'caller_id': row['caller_id'],
                        'receiver_id': row['receiver_id'],
                        'caller_name': row['caller_name'],
                        'receiver_name': row['receiver_name'],
                        'caller_photo': row['caller_photo'],
                        'receiver_photo': row['receiver_photo'],
                        'started_at': str(row['started_at']) if row['started_at'] else None,
                        'ended_at': str(row['ended_at']) if row['ended_at'] else None,
                        'created_at': str(row['created_at']) if row['created_at'] else None,
                        'updated_at': str(row['updated_at']) if row['updated_at'] else None
                    } for row in rows
                ]
                return JsonResponse({
                    'success': True,
                    'callSessions': call_sessions
                })
            if not call_session_id and not exotel_call_sid:
                return JsonResponse(
                    {'error': "callSessionId or exotelCallSid is required"},
                    status=400
                )
            query = """
                SELECT cs.id, cs.caller_id, cs.receiver_id, cs.exotel_call_sid, cs.status,
                       cs.duration, cs.cost, cs.recording_url, cs.conversation_duration,
                       cs.started_at, cs.ended_at, cs.created_at, cs.updated_at,
                       u1.name AS caller_name, u2.name AS receiver_name
                FROM call_sessions cs
                JOIN users u1 ON cs.caller_id = u1.id
                JOIN users u2 ON cs.receiver_id = u2.id
                WHERE (cs.id = %s OR cs.exotel_call_sid = %s)
                  AND (cs.caller_id = %s OR cs.receiver_id = %s)
            """
            rows = execute_query(query, [
                int(call_session_id) if call_session_id else 0,
                exotel_call_sid or '',
                user_id,
                user_id
            ])
            if not rows:
                return JsonResponse({'error': 'Call session not found'}, status=404)
            session = rows[0]
            return JsonResponse({
                'success': True,
                'callSession': {
                    'id': session['id'],
                    'exotelCallSid': session['exotel_call_sid'],
                    'status': session['status'],
                    'duration': session['duration'] or 0,
                    'cost': session['cost'] or 0,
                    'recordingUrl': session['recording_url'],
                    'conversationDuration': session['conversation_duration'] or 0,
                    'caller': {'id': session['caller_id'], 'name': session['caller_name']},
                    'receiver': {'id': session['receiver_id'], 'name': session['receiver_name']},
                    'startedAt': str(session['started_at']) if session['started_at'] else None,
                    'endedAt': str(session['ended_at']) if session['ended_at'] else None,
                    'createdAt': str(session['created_at']) if session['created_at'] else None,
                    'updatedAt': str(session['updated_at']) if session['updated_at'] else None
                }
            })
    except Exception as e:
        print(f"Call initiation or fetch error: {e}")
        return JsonResponse({
            'error': 'Internal server error',
            'code': 'INTERNAL_ERROR'
        }, status=500)

@csrf_exempt
@require_http_methods(["GET"])
@require_user
def call_status(request, call_session_id):
    """
    Get Call Status
    GET /api/calls/status/<call_session_id>
    """
    try:
        user_id = request.user_data['userId']

        session = execute_query("""
            SELECT status, duration, started_at, ended_at, recording_url, exotel_call_sid
            FROM call_sessions
            WHERE id = %s AND (caller_id = %s OR receiver_id = %s)
        """, [call_session_id, user_id, user_id])

        if not session:
            return JsonResponse({'error': 'Call session not found'}, status=404)

        s = session[0]
        return JsonResponse({
            'success': True,
            'callSessionId': call_session_id,
            'status': s['status'],
            'duration': s['duration'] or 0,
            'startedAt': str(s['started_at']) if s['started_at'] else None,
            'endedAt': str(s['ended_at']) if s['ended_at'] else None,
            'recordingUrl': s['recording_url'],
            'exotelCallSid': s['exotel_call_sid']
        })

    except Exception as e:
        print(f"Call status error: {e}")
        return JsonResponse({'error': 'Failed to check call status'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def sync_call_status(request, call_sid):
    """
    Sync Call Status from Exotel
    GET /api/calls/sync-status/<call_sid>
    """
    try:
        user_id = request.user_data['userId']

        # Get session
        session = execute_query("""
            SELECT id, caller_id, status
            FROM call_sessions
            WHERE exotel_call_sid = %s AND (caller_id = %s OR receiver_id = %s)
        """, [call_sid, user_id, user_id])

        if not session:
            return JsonResponse({'error': 'Call session not found'}, status=404)

        # Fetch from Exotel
        url = f"https://api.exotel.com/v1/Accounts/{settings.EXOTEL_SID}/Calls/{call_sid}.json"
        auth_string = f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}"
        auth_header = base64.b64encode(auth_string.encode()).decode()

        response = requests.get(url, headers={'Authorization': f'Basic {auth_header}'})

        if not response.ok:
            raise Exception(f"Exotel API error: {response.status_text}")

        data = response.json()
        call_data = data.get('Call', {})

        status = (call_data.get('Status') or 'unknown').lower()
        duration = int(call_data.get('Duration') or 0)
        recording_url = call_data.get('RecordingUrl')

        # Map status
        valid_statuses = ['initiated', 'ringing', 'in-progress', 'completed',
                         'busy', 'no-answer', 'failed', 'canceled', 'unknown']
        effective_status = 'in-progress' if status == 'answered' else (
            status if status in valid_statuses else 'unknown'
        )

        # Update session
        execute_update("""
            UPDATE call_sessions
            SET status = %s, duration = %s,
                started_at = CASE WHEN %s = 'in-progress' THEN NOW() ELSE started_at END,
                ended_at = CASE WHEN %s IN ('completed', 'busy', 'no-answer', 'failed', 'canceled')
                          THEN NOW() ELSE NULL END,
                recording_url = %s, updated_at = NOW()
            WHERE id = %s
        """, [effective_status, duration, effective_status, effective_status,
              recording_url, session[0]['id']])

        # Deduct credits if completed
        if effective_status == 'completed' and not settings.HAS_CREDIT_DEDUCTION_TRIGGER:
            duration_minutes = (duration + 59) // 60  # Ceiling division

            execute_update("""
                UPDATE user_call_credits
                SET credits_remaining = GREATEST(0, credits_remaining - %s),
                    last_used_at = NOW(), updated_at = NOW()
                WHERE user_id = %s AND credits_remaining > 0 AND expires_at > NOW()
                ORDER BY expires_at ASC
                LIMIT 1
            """, [duration_minutes, session[0]['caller_id']])

        return JsonResponse({
            'success': True,
            'status': effective_status,
            'duration': duration
        })

    except Exception as e:
        print(f"Sync error: {e}")
        return JsonResponse({'error': 'Failed to sync status'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
@require_user
def call_logs(request):
    """
    Get User Call Logs
    GET /api/calls/logs
    """
    try:
        user_id = request.user_data['userId']

        logs = execute_query("""
            SELECT cl.id, cl.call_type, cl.duration, cl.created_at,
                   other_user.name as other_user_name,
                   other_profile.profile_photo as other_user_photo,
                   cs.status as call_status
            FROM call_logs cl
            JOIN users other_user ON cl.other_user_id = other_user.id
            JOIN user_profiles other_profile ON cl.other_user_id = other_profile.user_id
            JOIN call_sessions cs ON cl.call_session_id = cs.id
            WHERE cl.user_id = %s
            ORDER BY cl.created_at DESC
            LIMIT 50
        """, [user_id])

        return JsonResponse({'success': True, 'logs': logs})

    except Exception as e:
        print(f"Call logs error: {e}")
        return JsonResponse({'error': 'Failed to fetch call logs'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def call_webhook(request):
    """
    Exotel Webhook Handler
    POST /api/calls/webhook
    """
    try:
        # Parse webhook data
        content_type = request.content_type or ''

        if 'application/json' in content_type:
            webhook_data = json.loads(request.body)
        elif 'application/x-www-form-urlencoded' in content_type:
            webhook_data = dict(request.POST.items())
        else:
            return JsonResponse({'error': 'Unsupported content type'}, status=400)

        call_sid = webhook_data.get('CallSid')
        event_type = webhook_data.get('EventType', 'unknown')
        status = webhook_data.get('Status', 'unknown')
        duration = int(webhook_data.get('ConversationDuration', 0))
        recording_url = webhook_data.get('RecordingUrl')

        if not call_sid:
            return JsonResponse({'error': 'CallSid is required'}, status=400)

        # Log webhook
        execute_insert("""
            INSERT INTO webhook_logs (call_sid, event_type, status, payload, created_at, processed)
            VALUES (%s, %s, %s, %s, NOW(), 0)
        """, [call_sid, event_type, status, json.dumps(webhook_data)])

        # Get session
        session = execute_query(
            "SELECT * FROM call_sessions WHERE exotel_call_sid = %s",
            [call_sid]
        )

        if not session:
            return JsonResponse({'message': 'Call session not found'}, status=200)

        s = session[0]
        final_status = status.lower()

        # Handle event types
        if event_type.lower() == 'answered':
            execute_update("""
                UPDATE call_sessions
                SET status = 'in_progress', started_at = NOW(), updated_at = NOW()
                WHERE id = %s
            """, [s['id']])

        elif event_type.lower() == 'terminal':
            duration_minutes = (duration + 59) // 60
            cost = duration_minutes * 1.0

            execute_update("""
                UPDATE call_sessions
                SET status = %s, duration = %s, cost = %s, ended_at = NOW(),
                    recording_url = %s, conversation_duration = %s, updated_at = NOW()
                WHERE id = %s
            """, [final_status, duration, cost, recording_url, duration, s['id']])

            # Create call logs and deduct credits if completed
            if final_status == 'completed' and duration > 0:
                # Create logs
                execute_insert("""
                    INSERT INTO call_logs
                    (user_id, other_user_id, call_session_id, call_type, duration, cost, created_at)
                    VALUES
                        (%s, %s, %s, 'outgoing', %s, %s, NOW()),
                        (%s, %s, %s, 'incoming', %s, %s, NOW())
                """, [s['caller_id'], s['receiver_id'], s['id'], duration, cost,
                      s['receiver_id'], s['caller_id'], s['id'], duration, cost])

                # Deduct credits if no trigger
                if not settings.HAS_CREDIT_DEDUCTION_TRIGGER:
                    for uid in [s['caller_id'], s['receiver_id']]:
                        execute_update("""
                            UPDATE user_call_credits
                            SET credits_remaining = GREATEST(0, credits_remaining - %s),
                                last_used_at = NOW(), updated_at = NOW()
                            WHERE user_id = %s AND credits_remaining > 0 AND expires_at > NOW()
                            ORDER BY expires_at ASC
                            LIMIT 1
                        """, [duration_minutes, uid])

                        execute_insert("""
                            INSERT INTO exotel_credit_log
                            (action, credits, user_id, call_session_id, reason, created_at)
                            VALUES ('used', %s, %s, %s, 'Call completed', NOW())
                        """, [duration_minutes, uid, s['id']])

        # Mark webhook processed
        execute_update(
            "UPDATE webhook_logs SET processed = 1 WHERE call_sid = %s AND event_type = %s",
            [call_sid, event_type]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Webhook error: {e}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)
