# Vercel Python entrypoint for Flask
import os
import sys

# Ensure project root is on path for imports
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
  sys.path.append(PROJECT_ROOT)

from app import create_app

# Export WSGI app for Vercel
app = create_app()

# Optional handler (not required but harmless)
def handler(request, response):
  return app(request.environ, response.start_response)


