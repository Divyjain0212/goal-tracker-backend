# Goal Tracker Backend API

This is the backend API for the Goal Tracker project built with Flask.

## 🏗️ Structure

```
backend/
├── api/              # Vercel API endpoints
│   ├── index.py      # Main API entry point
│   └── requirements.txt
├── app.py           # Flask application
├── instance/        # Database files
├── requirements.txt # Dependencies
├── .env            # Environment variables
├── vercel.json     # Vercel deployment config
└── README.md       # This file
```

## 🚀 API Endpoints

- `GET /` - Landing page
- `GET /health` - Health check
- `POST /api/login` - User authentication
- `GET /api/goals` - Get user goals
- `POST /api/goals` - Create new goal
- `PUT /api/goals/<id>` - Update goal
- `DELETE /api/goals/<id>` - Delete goal
- `GET /api/analytics` - User analytics

## 🚀 Deployment

### Vercel Deployment

1. Connect your backend repository to Vercel
2. Set environment variables:
   - `MONGO_URI` - MongoDB connection string
   - `SECRET_KEY` - Flask secret key
   - `FLASK_ENV` - Set to "production"

### Environment Variables

- `MONGO_URI` - MongoDB connection string (required)
- `SECRET_KEY` - Flask secret key for sessions (required)
- `FLASK_ENV` - Environment (production/development)
- `GOOGLE_OAUTH_CLIENT_ID` - Google OAuth client ID (optional)
- `GOOGLE_OAUTH_CLIENT_SECRET` - Google OAuth secret (optional)

## 🔧 Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python app.py
```

## 🧪 Testing

```bash
# Test API import
cd api
python -c "import index; print('✅ API import successful')"

# Test health endpoint
curl http://localhost:5000/health
```