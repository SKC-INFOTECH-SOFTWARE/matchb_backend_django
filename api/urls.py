from django.urls import path
from api.views import (
    auth_views,
    admin_views,
    user_views,
    profile_views,
    payment_views,
    call_views,
    upload_views,
)

urlpatterns = [
    # ==================== AUTHENTICATION (3 APIs) ====================
    path('auth/register', auth_views.register, name='register'),
    path('auth/login', auth_views.login, name='login'),
    path('auth/verify', auth_views.verify, name='verify'),

    # ==================== ADMIN - DASHBOARD (1 API) ====================
    path('admin/stats', admin_views.admin_stats, name='admin_stats'),

    # ==================== ADMIN - USER MANAGEMENT (5 APIs) ====================
    path('admin/profiles', admin_views.admin_profiles, name='admin_profiles'),
    path('admin/approve-profile', admin_views.approve_profile, name='approve_profile'),
    path('admin/update-status', admin_views.update_user_status, name='update_user_status'),
    path('admin/create-profile', admin_views.create_profile, name='create_profile'),
    path('admin/change-password', admin_views.admin_change_password, name='admin_change_password'),

    # ==================== ADMIN - PLANS MANAGEMENT (4 APIs) ====================
    path('admin/plans', admin_views.admin_plans, name='admin_plans'),  # GET & POST combined
    path('admin/plans/<int:plan_id>', admin_views.admin_plan_detail, name='admin_plan_detail'),  # PUT & DELETE

    # ==================== ADMIN - PAYMENTS (4 APIs) ====================
    path('admin/payments', admin_views.admin_payments, name='admin_payments'),  # GET & POST (legacy)
    path('admin/payments/<int:payment_id>', admin_views.admin_payment_detail, name='admin_payment_detail'),  # PUT
    path('admin/verify-call-payment', admin_views.verify_call_payment, name='verify_call_payment'),  # POST
    path('admin/call-subscriptions', admin_views.call_subscriptions, name='call_subscriptions'),  # GET

    # ==================== ADMIN - MATCHES (3 APIs) ====================
    path('admin/matches', admin_views.admin_matches, name='admin_matches'),  # GET, POST, DELETE

    # ==================== ADMIN - BLOCKS (3 APIs) ====================
    path('admin/blocks', admin_views.admin_blocks, name='admin_blocks'),  # GET, DELETE, PATCH

    # ==================== ADMIN - CALLS (2 APIs) ====================
    path('admin/call-sessions', admin_views.admin_call_sessions, name='admin_call_sessions'),
    path('admin/user-call-logs', admin_views.admin_user_call_logs, name='admin_user_call_logs'),

    # ==================== ADMIN - CREDITS (4 APIs) ====================
    path('admin/adjust-credits', admin_views.adjust_credits, name='adjust_credits'),
    path('admin/credit-distributions', admin_views.credit_distributions, name='credit_distributions'),
    path('admin/exotel-credits', admin_views.exotel_credits, name='exotel_credits'),
    path('admin/exotel-settings', admin_views.exotel_settings, name='exotel_settings'),

    # ==================== ADMIN - SEARCH VISIBILITY (3 APIs) ====================
    path('admin/search-visibility', admin_views.search_visibility, name='search_visibility'),  # GET, POST, DELETE

    # ==================== USER - PROFILE (3 APIs) ====================
    path('profile/create', profile_views.create_profile, name='create_profile'),
    path('profile/edit', profile_views.edit_profile, name='edit_profile'),
    path('profile/me', profile_views.my_profile, name='my_profile'),

    # ==================== USER - MATCHES (4 APIs) ====================
    path('matches', user_views.get_match_details, name='get_matches'),  # POST for match details
    path('user/matches', user_views.user_matches, name='user_matches'),  # GET for list
    path('user/profile-details/<int:profile_id>', user_views.profile_details, name='profile_details'),

    # ==================== USER - SEARCH (1 API) ====================
    path('user/search', user_views.search_profiles, name='search_profiles'),

    # ==================== USER - BLOCKING (1 API - handles POST, DELETE, GET) ====================
    path('user/block', user_views.block_user_handler, name='block_user_handler'),  # POST, DELETE, GET combined

    # ==================== USER - SUBSCRIPTIONS (3 APIs) ====================
    path('user/subscription-status', user_views.subscription_status, name='subscription_status'),
    path('user/active-plan', user_views.active_plan, name='active_plan'),
    path('user/call-credits', user_views.call_credits, name='call_credits'),

    # ==================== USER - SETTINGS (1 API) ====================
    path('user/change-password', user_views.change_password, name='change_password'),

    # ==================== PLANS & PAYMENTS (3 APIs) ====================
    path('plans', payment_views.get_plans, name='get_public_plans'),  # Public
    path('payments/submit', payment_views.submit_payment, name='submit_payment'),
    path('payments', payment_views.payment_history, name='payment_history'),  # GET payment history

    # ==================== CALLS (5 APIs) ====================
    path('calls/initiate', call_views.initiate_call, name='initiate_call'),
    path('calls/status/<int:call_session_id>', call_views.call_status, name='call_status'),
    path('calls/sync-status/<str:call_sid>', call_views.sync_call_status, name='sync_call_status'),
    path('calls/logs', call_views.call_logs, name='call_logs'),
    path('calls/webhook', call_views.call_webhook, name='call_webhook'),

    # User call logs (additional)
    path('user/call-logs', call_views.call_logs, name='user_call_logs_alias'),  # Same as calls/logs

    # ==================== FILE UPLOAD (1 API) ====================
    path('upload', upload_views.upload_file, name='upload_file'),
]
