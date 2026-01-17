import json
import base64
import requests
import threading
import time
from datetime import datetime, timedelta
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from api.utils import require_user
from api.db_utils import execute_query, execute_insert, execute_update
# =============================================================================
# SYNC JOB - Runs every 5 minutes automatically (like Node.js cron.schedule)
# =============================================================================
_sync_job_started = False
def sync_stuck_calls():
    """Background sync job for stuck calls - matches Node.js sync job exactly"""
    try:
        print('[SYNC JOB] Starting sync job for stuck calls')

        # Find stuck calls (older than 2 minutes)
        two_minutes_ago = datetime.now() - timedelta(minutes=2)

        stuck_calls = execute_query("""
            SELECT id, exotel_call_sid, caller_id, receiver_id
            FROM call_sessions
            WHERE status IN ('initiated', 'ringing', 'in_progress')
              AND created_at < %s
        """, [two_minutes_ago])

        if not stuck_calls:
            return

        print(f'[SYNC JOB] Found {len(stuck_calls)} stuck calls to sync')

        for call in stuck_calls:
            try:
                url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{settings.EXOTEL_SID}/Calls/{call['exotel_call_sid']}.json"

                auth_string = f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}"
                auth_header = base64.b64encode(auth_string.encode()).decode()

                response = requests.get(url, headers={
                    'Authorization': f'Basic {auth_header}'
                }, timeout=10)

                if not response.ok:
                    continue

                data = response.json()
                call_data = data.get('Call', {})

                status = (call_data.get('Status') or 'unknown').lower()
                duration = int(call_data.get('Duration') or 0)
                recording_url = call_data.get('RecordingUrl')
                conversation_duration = int(call_data.get('ConversationDuration') or 0)
                legs = call_data.get('Legs', [])

                duration_minutes = (duration + 59) // 60
                cost_per_minute = 1.0
                call_cost = duration_minutes * cost_per_minute if duration > 0 else 0

                # Update call session
                execute_update("""
                    UPDATE call_sessions
                    SET status = %s, duration = %s, cost = %s, ended_at = NOW(),
                        recording_url = %s, conversation_duration = %s,
                        leg1_status = %s, leg1_duration = %s,
                        leg2_status = %s, leg2_duration = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, [
                    status, duration, call_cost, recording_url, conversation_duration,
                    legs[0].get('Status') if len(legs) > 0 else None,
                    legs[0].get('OnCallDuration', 0) if len(legs) > 0 else 0,
                    legs[1].get('Status') if len(legs) > 1 else None,
                    legs[1].get('OnCallDuration', 0) if len(legs) > 1 else 0,
                    call['id']
                ])

                # Deduct credits if completed and no trigger
                if status == 'completed' and not getattr(settings, 'HAS_CREDIT_DEDUCTION_TRIGGER', False):
                    for user_id in [call['caller_id'], call['receiver_id']]:
                        execute_update("""
                            UPDATE user_call_credits
                            SET credits_remaining = GREATEST(0, credits_remaining - %s),
                                last_used_at = NOW(), updated_at = NOW()
                            WHERE user_id = %s
                              AND credits_remaining > 0
                              AND expires_at > NOW()
                            ORDER BY expires_at ASC
                            LIMIT 1
                        """, [duration_minutes, user_id])

                        execute_insert("""
                            INSERT INTO exotel_credit_log (
                                action, credits, user_id, call_session_id, reason, created_at
                            ) VALUES ('used', %s, %s, %s, 'Call synced', NOW())
                        """, [duration_minutes, user_id, call['id']])

                print(f"[SYNC JOB] Synced stuck call {call['id']} to status: {status}, duration: {duration}")

            except Exception as e:
                print(f"[SYNC JOB] Error syncing call {call['id']}: {e}")
                continue

    except Exception as e:
        print(f'[SYNC JOB] Sync job error: {e}')
def run_sync_job_loop():
    """Run sync job every 5 minutes - matches Node.js cron.schedule('*/5 * * * *')"""
    while True:
        try:
            sync_stuck_calls()
        except Exception as e:
            print(f"[SYNC JOB] Loop error: {e}")

        # Sleep for 5 minutes
        time.sleep(300)
def start_sync_job():
    """Start the sync job automatically when module loads - matches Node.js startSyncJob()"""
    global _sync_job_started

    if _sync_job_started:
        return

    _sync_job_started = True

    # Start background thread
    sync_thread = threading.Thread(target=run_sync_job_loop, daemon=True)
    sync_thread.start()

    print('[SYNC JOB] Call sync job started - will run every 5 minutes')
# Start sync job automatically when module is imported (like Node.js)
start_sync_job()
# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
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
        print('Initiating Exotel call with params:', {
            'From': caller_number,
            'To': receiver_number,
            'CallerId': settings.EXOTEL_VIRTUAL_NUMBER,
            'StatusCallback': f"{settings.APP_URL}/api/calls/webhook",
            'StatusCallbackEvents': ['terminal', 'answered']
        })
        response = requests.post(url, data=data, headers=headers)
        result = response.json()
        print('Exotel API Response:', result)
        if response.ok and result.get('Call', {}).get('Sid'):
            return {
                'success': True,
                'callSid': result['Call']['Sid'],
                'status': result['Call']['Status'],
                'virtualNumber': settings.EXOTEL_VIRTUAL_NUMBER
            }
        else:
            print('Exotel API Error:', result)
            raise Exception(
                result.get('RestException', {}).get('Message') or
                result.get('message') or
                'Exotel API call failed'
            )
    except Exception as e:
        print(f"Exotel API error: {e}")
        raise
# =============================================================================
# ENDPOINT 1: INITIATE CALL (GET & POST)
# =============================================================================
@csrf_exempt
@require_http_methods(["GET", "POST"])
@require_user
def initiate_call(request):
    """
    Initiate Call or Fetch Call Sessions
    POST /api/calls/initiate - Initiate a new call
    GET /api/calls/initiate - Fetch call sessions
    """
    try:
        user_id = request.user_data['userId']

        if request.method == 'POST':
            # POST: Initiate new call
            data = json.loads(request.body)
            target_user_id = data.get('targetUserId')

            if not target_user_id or not isinstance(target_user_id, int):
                return JsonResponse({'error': 'Valid target user ID is required'}, status=400)

            # Check Exotel config
            if not all([settings.EXOTEL_SID, settings.EXOTEL_API_KEY,
                       settings.EXOTEL_API_TOKEN, settings.EXOTEL_VIRTUAL_NUMBER]):
                print('Missing Exotel configuration')
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

            try:
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

                print(f"Call session {call_session_id} created for Exotel CallSid: {exotel_result['callSid']}")

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

            except Exception as exotel_error:
                print('Exotel call failed:', exotel_error)
                return JsonResponse({
                    'error': f"Failed to initiate call: {str(exotel_error)}",
                    'code': 'EXOTEL_ERROR'
                }, status=500)

        else:
            # GET: Fetch call sessions
            call_session_id = request.GET.get('callSessionId')
            exotel_call_sid = request.GET.get('exotelCallSid')
            fetch_logs = request.GET.get('logs') == 'true'

            if fetch_logs:
                # Fetch all call sessions for the user
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

                call_sessions = [{
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
                } for row in rows]

                return JsonResponse({
                    'success': True,
                    'callSessions': call_sessions
                })

            if not call_session_id and not exotel_call_sid:
                return JsonResponse(
                    {'error': 'callSessionId or exotelCallSid is required'},
                    status=400
                )

            # Fetch specific call session
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
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'error': 'Internal server error',
            'code': 'INTERNAL_ERROR'
        }, status=500)
# =============================================================================
# ENDPOINT 2: WEBHOOK (POST ONLY)
# =============================================================================
@csrf_exempt
@require_http_methods(["POST"])
def call_webhook(request):
    """
    Exotel Webhook Handler
    POST /api/calls/webhook

    Matches Node.js webhook handler exactly
    """
    webhook_data = None

    try:
        # Parse webhook data
        content_type = request.content_type or ''

        if 'application/json' in content_type:
            webhook_data = json.loads(request.body)
        elif 'application/x-www-form-urlencoded' in content_type:
            webhook_data = dict(request.POST.items())

            # Handle nested Legs array from form data
            if 'Legs[0][Status]' in webhook_data or 'Legs[1][Status]' in webhook_data:
                legs = []
                legs.append({
                    'Status': webhook_data.get('Legs[0][Status]', ''),
                    'OnCallDuration': int(webhook_data.get('Legs[0][OnCallDuration]', 0))
                })
                legs.append({
                    'Status': webhook_data.get('Legs[1][Status]', ''),
                    'OnCallDuration': int(webhook_data.get('Legs[1][OnCallDuration]', 0))
                })
                webhook_data['Legs'] = legs

            # Convert ConversationDuration to int
            if 'ConversationDuration' in webhook_data:
                webhook_data['ConversationDuration'] = int(webhook_data.get('ConversationDuration', 0))
        else:
            print('Unsupported content type:', content_type)
            return JsonResponse({'error': 'Unsupported content type'}, status=400)

        print('📞 Exotel Webhook Received:', json.dumps(webhook_data, indent=2))

        # Extract webhook data
        call_sid = webhook_data.get('CallSid')
        event_type = webhook_data.get('EventType')
        call_status = webhook_data.get('Status')
        conversation_duration = webhook_data.get('ConversationDuration', 0)
        recording_url = webhook_data.get('RecordingUrl')
        start_time = webhook_data.get('StartTime')
        end_time = webhook_data.get('EndTime')
        custom_field = webhook_data.get('CustomField')
        legs = webhook_data.get('Legs', [])

        if not call_sid:
            print('Missing CallSid in webhook')
            return JsonResponse({'error': 'CallSid is required'}, status=400)

        # Log the webhook
        execute_insert("""
            INSERT INTO webhook_logs (
                call_sid, event_type, status, payload, created_at, processed
            ) VALUES (%s, %s, %s, %s, NOW(), 0)
        """, [call_sid, event_type or 'unknown', call_status, json.dumps(webhook_data)])

        # Get session
        session = execute_query(
            "SELECT * FROM call_sessions WHERE exotel_call_sid = %s",
            [call_sid]
        )

        if not session:
            print(f'Call session not found for CallSid: {call_sid}')
            return JsonResponse({'message': 'Call session not found'}, status=200)

        s = session[0]

        # Parse CustomField if present
        user_id = None
        target_user_id = None
        if custom_field:
            try:
                custom_data = json.loads(custom_field)
                user_id = custom_data.get('userId')
                target_user_id = custom_data.get('targetUserId')
            except:
                pass

        duration = conversation_duration or 0
        duration_minutes = (duration + 59) // 60 # Ceiling division
        cost_per_minute = s.get('cost_per_minute', 1.0)
        call_cost = duration_minutes * cost_per_minute if duration > 0 else 0

        update_query = ""
        update_params = []
        should_create_call_logs = False
        final_status = (call_status or 'unknown').lower()

        # Handle different event types - matches Node.js switch/case exactly
        if (event_type or '').lower() == 'answered':
            final_status = 'in_progress'
            start = start_time if start_time else datetime.now()
            update_query = """
                UPDATE call_sessions
                SET status = 'in_progress', started_at = %s, updated_at = NOW()
                WHERE id = %s
            """
            update_params = [start, s['id']]

        elif (event_type or '').lower() == 'terminal':
            final_status = (call_status or 'unknown').lower()
            should_create_call_logs = final_status == 'completed'
            end = end_time if end_time else datetime.now()

            update_query = """
                UPDATE call_sessions
                SET status = %s, duration = %s, cost = %s, ended_at = %s,
                    recording_url = %s, conversation_duration = %s,
                    leg1_status = %s, leg1_duration = %s,
                    leg2_status = %s, leg2_duration = %s,
                    updated_at = NOW()
                WHERE id = %s
            """
            update_params = [
                final_status,
                duration,
                call_cost,
                end,
                recording_url or None,
                conversation_duration or 0,
                legs[0].get('Status') if len(legs) > 0 else None,
                legs[0].get('OnCallDuration', 0) if len(legs) > 0 else 0,
                legs[1].get('Status') if len(legs) > 1 else None,
                legs[1].get('OnCallDuration', 0) if len(legs) > 1 else 0,
                s['id']
            ]
        else:
            print(f'Unknown event type: {event_type}')
            return JsonResponse({'success': True})

        # Execute update query
        if update_query:
            execute_update(update_query, update_params)
            print(f"Updated call session {s['id']} with status: {final_status}")

        # Create call logs and deduct credits if completed
        if should_create_call_logs and duration > 0:
            print('Creating call logs for completed call')

            # Create call logs
            execute_insert("""
                INSERT INTO call_logs (
                    user_id, other_user_id, call_session_id, call_type,
                    duration, cost, created_at
                ) VALUES (%s, %s, %s, 'outgoing', %s, %s, NOW())
            """, [s['caller_id'], s['receiver_id'], s['id'], duration, call_cost])

            execute_insert("""
                INSERT INTO call_logs (
                    user_id, other_user_id, call_session_id, call_type,
                    duration, cost, created_at
                ) VALUES (%s, %s, %s, 'incoming', %s, %s, NOW())
            """, [s['receiver_id'], s['caller_id'], s['id'], duration, call_cost])

            # Only deduct credits if no database trigger handles it
            has_trigger = getattr(settings, 'HAS_CREDIT_DEDUCTION_TRIGGER', False)
            if not has_trigger:
                # Deduct credits for caller
                execute_update("""
                    UPDATE user_call_credits
                    SET credits_remaining = GREATEST(0, credits_remaining - %s),
                        last_used_at = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s
                      AND credits_remaining > 0
                      AND expires_at > NOW()
                    ORDER BY expires_at ASC
                    LIMIT 1
                """, [duration_minutes, s['caller_id']])

                # Deduct credits for receiver
                execute_update("""
                    UPDATE user_call_credits
                    SET credits_remaining = GREATEST(0, credits_remaining - %s),
                        last_used_at = NOW(),
                        updated_at = NOW()
                    WHERE user_id = %s
                      AND credits_remaining > 0
                      AND expires_at > NOW()
                    ORDER BY expires_at ASC
                    LIMIT 1
                """, [duration_minutes, s['receiver_id']])

                # Log credit usage
                execute_insert("""
                    INSERT INTO exotel_credit_log (
                        action, credits, user_id, call_session_id, reason, created_at
                    ) VALUES
                        ('used', %s, %s, %s, 'Call completed - caller', NOW()),
                        ('used', %s, %s, %s, 'Call completed - receiver', NOW())
                """, [
                    duration_minutes, s['caller_id'], s['id'],
                    duration_minutes, s['receiver_id'], s['id']
                ])

                print(f"Call logs created and credits deducted for session {s['id']}")
            else:
                print(f"Call logs created for session {s['id']} (credits handled by trigger)")

        # Mark webhook as processed
        execute_update(
            "UPDATE webhook_logs SET processed = 1 WHERE call_sid = %s AND event_type = %s",
            [call_sid, event_type]
        )

        return JsonResponse({'success': True})

    except Exception as e:
        print(f"Webhook processing error: {e}")
        import traceback
        traceback.print_exc()

        # Try to log the error
        if webhook_data:
            try:
                execute_insert("""
                    INSERT INTO webhook_logs (
                        call_sid, event_type, status, payload, created_at, processed
                    ) VALUES (%s, %s, %s, %s, NOW(), 0)
                """, [
                    webhook_data.get('CallSid') or 'unknown',
                    webhook_data.get('EventType') or 'unknown',
                    webhook_data.get('Status') or 'unknown',
                    json.dumps(webhook_data)
                ])
            except Exception as log_e:
                print(f"Failed to log webhook: {log_e}")

        return JsonResponse({
            'error': 'Webhook processing failed',
            'details': str(e)
        }, status=500)
