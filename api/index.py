import sys
import os

# Add the backend directory to the path
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(current_dir)
sys.path.insert(0, backend_dir)

# Import the Flask app
try:
    from app import app
    print("✅ Flask app imported successfully")
except Exception as e:
    print(f"❌ Error importing Flask app: {e}")
    raise

# This is the main export for Vercel
# Vercel looks for 'app' or 'handler' or 'application'
def application(environ, start_response):
    return app(environ, start_response)

# Alternative exports for compatibility
handler = app
main = app