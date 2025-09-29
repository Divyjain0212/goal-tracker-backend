import sys
import os

# Add the backend directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)  # Now we're in backend/api, so parent is backend
sys.path.insert(0, backend_dir)

# Import the Flask app from backend (already configured with correct paths)
from app import app

# Export for Vercel
def handler(request):
    return app

# Also export app directly
app_instance = app