import cloudinary
import cloudinary.uploader
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET
)

@csrf_exempt
@require_http_methods(["POST"])
def upload_file(request):
    """
    Upload File to Cloudinary
    POST /api/upload
    """
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        file = request.FILES['file']

        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
        if file.content_type not in allowed_types:
            return JsonResponse({
                'error': 'Invalid file type. Only JPEG, PNG, and WebP are allowed.'
            }, status=400)

        # Validate file size (5MB max)
        if file.size > 5 * 1024 * 1024:
            return JsonResponse({
                'error': 'File size too large. Maximum 5MB allowed.'
            }, status=400)

        # Upload to Cloudinary
        upload_result = cloudinary.uploader.upload(
            file,
            folder='matchb-profiles',
            transformation=[
                {'width': 500, 'height': 500, 'crop': 'limit'},
                {'quality': 'auto:good'}
            ]
        )

        return JsonResponse({
            'success': True,
            'url': upload_result['secure_url'],
            'filename': upload_result['public_id']
        })

    except Exception as e:
        print(f"Upload error: {e}")
        return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)
