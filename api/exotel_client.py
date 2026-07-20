# api/exotel_client.py
"""
Thin client for talking to the live Exotel account.

Kept in its own module so both admin_views (balance display) and call_views
(per-call price capture) can use it without importing each other.
"""
import base64
import requests
from django.conf import settings


def _auth_header():
    """HTTP Basic auth header from the API key / token in settings."""
    auth_string = f"{settings.EXOTEL_API_KEY}:{settings.EXOTEL_API_TOKEN}"
    return "Basic " + base64.b64encode(auth_string.encode()).decode()


def _creds_configured():
    return all([
        settings.EXOTEL_SUBDOMAIN,
        settings.EXOTEL_SID,
        settings.EXOTEL_API_KEY,
        settings.EXOTEL_API_TOKEN,
    ])


def get_account_balance(timeout=10):
    """
    Fetch the live wallet balance from Exotel.
    GET https://<subdomain>/v1/Accounts/<sid>/Balance.json

    Exotel's exact field names for this resource are not fully documented, so we
    parse defensively and always return the raw payload for verification.

    Returns:
        {'available': True, 'amount': float|None, 'currency': str, 'raw': dict}
        {'available': False, 'error': str}
    """
    if not _creds_configured():
        return {'available': False, 'error': 'Exotel credentials not configured'}

    url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{settings.EXOTEL_SID}/Balance.json"

    try:
        resp = requests.get(url, headers={'Authorization': _auth_header()}, timeout=timeout)
    except requests.RequestException as e:
        return {'available': False, 'error': f'Network error contacting Exotel: {e}'}

    if not resp.ok:
        return {'available': False, 'error': f'Exotel API returned HTTP {resp.status_code}'}

    try:
        data = resp.json()
    except ValueError:
        return {'available': False, 'error': 'Exotel returned a non-JSON response'}

    # The balance object may sit under a wrapper key, or be the top-level object.
    container = data
    for wrapper in ('Balance', 'Account', 'balance', 'account'):
        if isinstance(data.get(wrapper), dict):
            container = data[wrapper]
            break

    amount = _first_present(container, (
        'BalanceAmount', 'Balance', 'AvailableCredit', 'available_credit',
        'AvailableBalance', 'Amount', 'balance',
    ))
    currency = _first_present(container, ('Currency', 'currency')) or 'INR'

    parsed_amount = None
    if amount is not None:
        try:
            parsed_amount = float(str(amount).replace(',', ''))
        except (TypeError, ValueError):
            parsed_amount = None

    return {
        'available': True,
        'amount': parsed_amount,
        'currency': currency,
        'raw': data,
    }


def get_call_details(call_sid, timeout=10):
    """
    Fetch a single call's details from Exotel, including the actual `Price` charged.
    GET https://<subdomain>/v1/Accounts/<sid>/Calls/<CallSid>.json

    Returns the inner Call dict, or None on any failure.
    """
    if not _creds_configured() or not call_sid:
        return None

    url = f"https://{settings.EXOTEL_SUBDOMAIN}/v1/Accounts/{settings.EXOTEL_SID}/Calls/{call_sid}.json"

    try:
        resp = requests.get(url, headers={'Authorization': _auth_header()}, timeout=timeout)
        if not resp.ok:
            return None
        return resp.json().get('Call', {})
    except (requests.RequestException, ValueError):
        return None


def parse_price(value):
    """
    Normalise an Exotel `Price` value (often a negative string like "-0.7000")
    into a positive float amount, or None if it can't be parsed.
    """
    if value is None:
        return None
    try:
        return abs(float(str(value).replace(',', '')))
    except (TypeError, ValueError):
        return None


def _first_present(obj, keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if obj.get(key) is not None:
            return obj[key]
    return None
