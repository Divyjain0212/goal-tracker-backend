from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, render_template_string, make_response
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SelectField, DateField, BooleanField
from wtforms.validators import DataRequired, Length, Email, EqualTo
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from bson.errors import InvalidId
from flask_cors import CORS
try:
    from flask_dance.contrib.google import make_google_blueprint, google
    from flask_dance.consumer.storage.sqla import OAuthConsumerMixin, SQLAlchemyStorage
    from flask_dance.consumer import oauth_authorized
    GOOGLE_OAUTH_AVAILABLE = True
except ImportError as e:
    GOOGLE_OAUTH_AVAILABLE = False
    print(
        f"Warning: Flask-Dance not properly configured: {e}. Google OAuth will be disabled.")
from datetime import datetime, date, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

# Allow OAuth over HTTP for development only
if os.environ.get('FLASK_ENV') != 'production':
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

# Configure paths for the new folder structure
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
frontend_dir = os.path.join(project_root, 'frontend')
template_dir = os.path.join(frontend_dir, 'templates')
static_dir = os.path.join(frontend_dir, 'static')

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)

# Enable CORS for cross-origin requests from frontend
CORS(app, origins=["*"])  # In production, specify your frontend domain

app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'your-secret-key-change-this-in-production')

# MongoDB Configuration
app.config['MONGO_URI'] = os.environ.get(
    'MONGO_URI', 'mongodb://localhost:27017/achievify_db')

# Google OAuth setup (you'll need to set these environment variables)
app.config['GOOGLE_OAUTH_CLIENT_ID'] = os.environ.get('GOOGLE_OAUTH_CLIENT_ID')
app.config['GOOGLE_OAUTH_CLIENT_SECRET'] = os.environ.get(
    'GOOGLE_OAUTH_CLIENT_SECRET')

# Initialize MongoDB with error handling
mongo = None
try:
    mongo = PyMongo(app)
    # For serverless environments, don't test connection during initialization
    # Connection will be tested when actually needed
    if os.environ.get('FLASK_ENV') != 'production':
        mongo.db.command('ping')
        print("✅ MongoDB connected successfully!")
except Exception as e:
    print(f"❌ MongoDB connection failed: {e}")
    if os.environ.get('FLASK_ENV') != 'production':
        print("📝 Please ensure MongoDB is running or check your MONGO_URI configuration")
        print("💡 Quick setup options:")
        print("   1. Install MongoDB locally: https://www.mongodb.com/try/download/community")
        print("   2. Use MongoDB Atlas (free): https://cloud.mongodb.com/")
        print("   3. Run with Docker: docker run -d -p 27017:27017 --name mongodb mongo:latest")
    mongo = None
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

# Context processor to make user preferences available in all templates
@app.context_processor
def inject_user_preferences():
    if current_user.is_authenticated and mongo:
        try:
            user_prefs = mongo.db.user_preferences.find_one({'user_id': current_user.id})
            if user_prefs:
                return {'user_theme': user_prefs.get('theme', 'light')}
        except Exception as e:
            print(f"Error fetching user preferences: {e}")
    return {'user_theme': 'light'}

# Google OAuth Blueprint
google_bp = None

# Simple health check route for debugging
@app.route('/health')
def health_check():
    return {
        "status": "ok",
        "flask_env": os.environ.get('FLASK_ENV', 'not_set'),
        "mongo_connected": mongo is not None
    }

# MongoDB Document Models


class User(UserMixin):
    def __init__(self, username=None, email=None, password_hash=None, google_id=None, profile_pic=None, _id=None, created_at=None):
        self.id = str(_id) if _id else None
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.google_id = google_id
        self.profile_pic = profile_pic
        self.created_at = created_at or datetime.utcnow()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def save(self):
        user_data = {
            'username': self.username,
            'email': self.email,
            'password_hash': self.password_hash,
            'google_id': self.google_id,
            'profile_pic': self.profile_pic,
            'created_at': self.created_at
        }
        if self.id:
            # Update existing user
            mongo.db.users.update_one(
                {'_id': ObjectId(self.id)}, {'$set': user_data})
        else:
            # Create new user
            result = mongo.db.users.insert_one(user_data)
            self.id = str(result.inserted_id)
        return self

    @staticmethod
    def find_by_id(user_id):
        if not mongo:
            return None
        try:
            user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
            if user_data:
                return User(
                    username=user_data['username'],
                    email=user_data['email'],
                    password_hash=user_data.get('password_hash'),
                    google_id=user_data.get('google_id'),
                    profile_pic=user_data.get('profile_pic'),
                    _id=user_data['_id'],
                    created_at=user_data.get('created_at')
                )
        except (InvalidId, KeyError):
            pass
        return None

    @staticmethod
    def find_by_username(username):
        user_data = mongo.db.users.find_one({'username': username})
        if user_data:
            return User(
                username=user_data['username'],
                email=user_data['email'],
                password_hash=user_data.get('password_hash'),
                google_id=user_data.get('google_id'),
                profile_pic=user_data.get('profile_pic'),
                _id=user_data['_id'],
                created_at=user_data.get('created_at')
            )
        return None

    @staticmethod
    def find_by_email(email):
        user_data = mongo.db.users.find_one({'email': email})
        if user_data:
            return User(
                username=user_data['username'],
                email=user_data['email'],
                password_hash=user_data.get('password_hash'),
                google_id=user_data.get('google_id'),
                profile_pic=user_data.get('profile_pic'),
                _id=user_data['_id'],
                created_at=user_data.get('created_at')
            )
        return None

    @staticmethod
    def find_by_google_id(google_id):
        user_data = mongo.db.users.find_one({'google_id': google_id})
        if user_data:
            return User(
                username=user_data['username'],
                email=user_data['email'],
                password_hash=user_data.get('password_hash'),
                google_id=user_data.get('google_id'),
                profile_pic=user_data.get('profile_pic'),
                _id=user_data['_id'],
                created_at=user_data.get('created_at')
            )
        return None


class Goal:
    def __init__(self, text=None, user_id=None, completed=False, priority='medium', category='general',
                 due_date=None, _id=None, created_at=None, updated_at=None):
        self.id = str(_id) if _id else None
        self.text = text
        self.user_id = user_id
        self.completed = completed
        self.priority = priority
        self.category = category
        self.due_date = due_date
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def save(self):
        # Convert date to datetime for MongoDB compatibility
        due_date_dt = None
        if self.due_date:
            if isinstance(self.due_date, date) and not isinstance(self.due_date, datetime):
                due_date_dt = datetime.combine(
                    self.due_date, datetime.min.time())
            else:
                due_date_dt = self.due_date

        goal_data = {
            'text': self.text,
            'user_id': self.user_id,
            'completed': self.completed,
            'priority': self.priority,
            'category': self.category,
            'due_date': due_date_dt,
            'created_at': self.created_at,
            'updated_at': datetime.utcnow()
        }
        if self.id:
            # Update existing goal
            mongo.db.goals.update_one(
                {'_id': ObjectId(self.id)}, {'$set': goal_data})
        else:
            # Create new goal
            result = mongo.db.goals.insert_one(goal_data)
            self.id = str(result.inserted_id)
        return self

    def delete(self):
        if self.id:
            mongo.db.goals.delete_one({'_id': ObjectId(self.id)})

    @staticmethod
    def find_by_id(goal_id):
        try:
            goal_data = mongo.db.goals.find_one({'_id': ObjectId(goal_id)})
            if goal_data:
                # Convert datetime back to date for due_date
                due_date = None
                if goal_data.get('due_date'):
                    if isinstance(goal_data['due_date'], datetime):
                        due_date = goal_data['due_date'].date()
                    else:
                        due_date = goal_data['due_date']

                return Goal(
                    text=goal_data['text'],
                    user_id=goal_data['user_id'],
                    completed=goal_data['completed'],
                    priority=goal_data.get('priority', 'medium'),
                    category=goal_data.get('category', 'general'),
                    due_date=due_date,
                    _id=goal_data['_id'],
                    created_at=goal_data.get('created_at'),
                    updated_at=goal_data.get('updated_at')
                )
        except (InvalidId, KeyError):
            pass
        return None

    @staticmethod
    def find_by_user_id(user_id):
        goals = []
        for goal_data in mongo.db.goals.find({'user_id': user_id}):
            # Convert datetime back to date for due_date
            due_date = None
            if goal_data.get('due_date'):
                if isinstance(goal_data['due_date'], datetime):
                    due_date = goal_data['due_date'].date()
                else:
                    due_date = goal_data['due_date']

            goals.append(Goal(
                text=goal_data['text'],
                user_id=goal_data['user_id'],
                completed=goal_data['completed'],
                priority=goal_data.get('priority', 'medium'),
                category=goal_data.get('category', 'general'),
                due_date=due_date,
                _id=goal_data['_id'],
                created_at=goal_data.get('created_at'),
                updated_at=goal_data.get('updated_at')
            ))
        return goals

    def to_dict(self):
        return {
            'id': self.id,
            'text': self.text,
            'completed': self.completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'priority': self.priority,
            'category': self.category,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Habit:
    def __init__(self, name=None, user_id=None, frequency='daily', target_count=1,
                 description=None, category='general', _id=None, created_at=None, is_active=True):
        self.id = str(_id) if _id else None
        self.name = name
        self.user_id = user_id
        self.frequency = frequency  # daily, weekly
        self.target_count = target_count
        self.description = description
        self.category = category
        self.is_active = is_active
        self.created_at = created_at or datetime.utcnow()

    def save(self):
        habit_data = {
            'name': self.name,
            'user_id': self.user_id,
            'frequency': self.frequency,
            'target_count': self.target_count,
            'description': self.description,
            'category': self.category,
            'is_active': self.is_active,
            'created_at': self.created_at
        }
        if self.id:
            mongo.db.habits.update_one(
                {'_id': ObjectId(self.id)}, {'$set': habit_data})
        else:
            result = mongo.db.habits.insert_one(habit_data)
            self.id = str(result.inserted_id)
        return self

    def delete(self):
        if self.id:
            mongo.db.habits.delete_one({'_id': ObjectId(self.id)})

    @staticmethod
    def find_by_user_id(user_id):
        habits = []
        for habit_data in mongo.db.habits.find({'user_id': user_id, 'is_active': True}):
            habits.append(Habit(
                name=habit_data['name'],
                user_id=habit_data['user_id'],
                frequency=habit_data.get('frequency', 'daily'),
                target_count=habit_data.get('target_count', 1),
                description=habit_data.get('description'),
                category=habit_data.get('category', 'general'),
                is_active=habit_data.get('is_active', True),
                _id=habit_data['_id'],
                created_at=habit_data.get('created_at')
            ))
        return habits


class HabitLog:
    def __init__(self, habit_id=None, user_id=None, completed_count=1, notes=None,
                 date=None, _id=None):
        self.id = str(_id) if _id else None
        self.habit_id = habit_id
        self.user_id = user_id
        self.completed_count = completed_count
        self.notes = notes
        self.date = date or datetime.now().date()

    def save(self):
        # Convert date to datetime for MongoDB compatibility
        date_dt = None
        if self.date:
            if isinstance(self.date, date) and not isinstance(self.date, datetime):
                date_dt = datetime.combine(self.date, datetime.min.time())
            else:
                date_dt = self.date

        log_data = {
            'habit_id': ObjectId(self.habit_id) if isinstance(self.habit_id, str) else self.habit_id,
            'user_id': self.user_id,
            'completed_count': self.completed_count,
            'notes': self.notes,
            'date': date_dt
        }
        if self.id:
            mongo.db.habit_logs.update_one(
                {'_id': ObjectId(self.id)}, {'$set': log_data})
        else:
            result = mongo.db.habit_logs.insert_one(log_data)
            self.id = str(result.inserted_id)
        return self


class UtilityBill:
    def __init__(self, bill_type=None, user_id=None, amount=0.0, date=None,
                 consumption=0.0, unit='liters', notes=None, _id=None):
        self.id = str(_id) if _id else None
        self.bill_type = bill_type  # 'milk' or 'water'
        self.user_id = user_id
        self.amount = amount
        self.date = date or datetime.now().date()
        self.consumption = consumption
        self.unit = unit
        self.notes = notes

    def save(self):
        # Convert date to datetime for MongoDB compatibility
        date_dt = None
        if self.date:
            if isinstance(self.date, date) and not isinstance(self.date, datetime):
                date_dt = datetime.combine(self.date, datetime.min.time())
            else:
                date_dt = self.date

        bill_data = {
            'bill_type': self.bill_type,
            'user_id': self.user_id,
            'amount': self.amount,
            'date': date_dt,
            'consumption': self.consumption,
            'unit': self.unit,
            'notes': self.notes
        }
        if self.id:
            mongo.db.utility_bills.update_one(
                {'_id': ObjectId(self.id)}, {'$set': bill_data})
        else:
            result = mongo.db.utility_bills.insert_one(bill_data)
            self.id = str(result.inserted_id)
        return self

    @staticmethod
    def find_by_user_and_type(user_id, bill_type):
        bills = []
        for bill_data in mongo.db.utility_bills.find({'user_id': user_id, 'bill_type': bill_type}).sort('date', 1):
            # Convert datetime back to date
            bill_date = None
            if bill_data.get('date'):
                if isinstance(bill_data['date'], datetime):
                    bill_date = bill_data['date'].date()
                else:
                    bill_date = bill_data['date']

            bills.append(UtilityBill(
                bill_type=bill_data['bill_type'],
                user_id=bill_data['user_id'],
                amount=bill_data['amount'],
                date=bill_date,
                consumption=bill_data.get('consumption', 0.0),
                unit=bill_data.get('unit', 'liters'),
                notes=bill_data.get('notes'),
                _id=bill_data['_id']
            ))
        return bills

# OAuth Token Storage for MongoDB (simple session-based storage)
# We'll use session-based storage instead of database storage for OAuth tokens


@login_manager.user_loader
def load_user(user_id):
    return User.find_by_id(user_id)

# Forms


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[
                           DataRequired(), Length(min=4, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[
                             DataRequired(), Length(min=6)])
    password2 = PasswordField('Confirm Password', validators=[
                              DataRequired(), EqualTo('password')])


class GoalForm(FlaskForm):
    text = TextAreaField('Goal Text', validators=[
                         DataRequired(), Length(min=1, max=500)])
    priority = SelectField('Priority', choices=[(
        'low', 'Low'), ('medium', 'Medium'), ('high', 'High')], default='medium')
    category = StringField('Category', default='general')
    due_date = DateField('Due Date', format='%Y-%m-%d', validators=[])

# Routes


@app.route('/')
def index():
    if not current_user.is_authenticated:
        return render_template('landing.html')

    # Get filter parameters
    category_filter = request.args.get('category', '')
    priority_filter = request.args.get('priority', '')
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '')

    # Build MongoDB query
    query_filter = {'user_id': current_user.id}

    # Apply filters
    if category_filter:
        query_filter['category'] = category_filter
    if priority_filter:
        query_filter['priority'] = priority_filter
    if status_filter == 'completed':
        query_filter['completed'] = True
    elif status_filter == 'pending':
        query_filter['completed'] = False
    if search_query:
        query_filter['text'] = {'$regex': search_query, '$options': 'i'}

    # Get goals sorted by created_at descending
    goals_data = mongo.db.goals.find(query_filter).sort('created_at', -1)
    goals = []
    for goal_data in goals_data:
        # Convert datetime back to date for due_date
        due_date = None
        if goal_data.get('due_date'):
            if isinstance(goal_data['due_date'], datetime):
                due_date = goal_data['due_date'].date()
            else:
                due_date = goal_data['due_date']

        goals.append(Goal(
            text=goal_data['text'],
            user_id=goal_data['user_id'],
            completed=goal_data['completed'],
            priority=goal_data.get('priority', 'medium'),
            category=goal_data.get('category', 'general'),
            due_date=due_date,
            _id=goal_data['_id'],
            created_at=goal_data.get('created_at'),
            updated_at=goal_data.get('updated_at')
        ))

    # Get categories for filter dropdown
    categories = mongo.db.goals.distinct(
        'category', {'user_id': current_user.id})

    return render_template('index.html', goals=goals, categories=categories)


@app.route('/add', methods=['GET', 'POST'])
@login_required
def add_goal():
    form = GoalForm()
    if form.validate_on_submit():
        goal = Goal(
            text=form.text.data,
            priority=form.priority.data,
            category=form.category.data or 'general',
            due_date=form.due_date.data,
            user_id=current_user.id
        )
        goal.save()
        flash('Goal added successfully!', 'success')
        return redirect(url_for('index'))
    return render_template('add_goal.html', form=form)


@app.route('/edit/<goal_id>', methods=['GET', 'POST'])
@login_required
def edit_goal(goal_id):
    goal = Goal.find_by_id(goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Goal not found!', 'error')
        return redirect(url_for('index'))

    form = GoalForm()
    if request.method == 'GET':
        form.text.data = goal.text
        form.priority.data = goal.priority
        form.category.data = goal.category
        form.due_date.data = goal.due_date

    if form.validate_on_submit():
        goal.text = form.text.data
        goal.priority = form.priority.data
        goal.category = form.category.data or 'general'
        goal.due_date = form.due_date.data
        goal.updated_at = datetime.utcnow()
        goal.save()
        flash('Goal updated successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('edit_goal.html', form=form, goal=goal)


@app.route('/toggle/<goal_id>')
@login_required
def toggle_goal(goal_id):
    goal = Goal.find_by_id(goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Goal not found!', 'error')
        return redirect(url_for('index'))

    goal.completed = not goal.completed
    goal.updated_at = datetime.utcnow()
    goal.save()
    return redirect(url_for('index'))


@app.route('/delete/<goal_id>')
@login_required
def delete_goal(goal_id):
    goal = Goal.find_by_id(goal_id)
    if not goal or goal.user_id != current_user.id:
        flash('Goal not found!', 'error')
        return redirect(url_for('index'))

    goal.delete()
    flash('Goal deleted successfully!', 'success')
    return redirect(url_for('index'))


@app.route('/bulk_action', methods=['POST'])
@login_required
def bulk_action():
    action = request.form.get('action')
    goal_ids = request.form.getlist('goal_ids')

    if not goal_ids:
        flash('No goals selected!', 'warning')
        return redirect(url_for('index'))

    # Convert string IDs to ObjectIds and filter by user
    valid_goals = []
    for goal_id in goal_ids:
        goal = Goal.find_by_id(goal_id)
        if goal and goal.user_id == current_user.id:
            valid_goals.append(goal)

    if action == 'complete':
        for goal in valid_goals:
            goal.completed = True
            goal.updated_at = datetime.utcnow()
            goal.save()
        flash(f'{len(valid_goals)} goals marked as completed!', 'success')
    elif action == 'delete':
        for goal in valid_goals:
            goal.delete()
        flash(f'{len(valid_goals)} goals deleted!', 'success')
    return redirect(url_for('index'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.find_by_username(form.username.data)
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        flash('Invalid username or password!', 'danger')

    return render_template('login.html', form=form)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegisterForm()
    if form.validate_on_submit():
        if User.find_by_username(form.username.data):
            flash('Username already exists!', 'danger')
        elif User.find_by_email(form.email.data):
            flash('Email already registered!', 'danger')
        else:
            user = User(username=form.username.data, email=form.email.data)
            user.set_password(form.password.data)
            user.save()
            flash('Registration successful!', 'success')
            return redirect(url_for('login'))

    return render_template('register.html', form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out!', 'info')
    return redirect(url_for('index'))


@app.route('/google_login')
def google_login():
    """Redirect to Google OAuth - the callback will be handled automatically"""
    if not GOOGLE_OAUTH_AVAILABLE or not google_bp:
        flash('Google login is not configured!', 'warning')
        return redirect(url_for('login'))

    # Simply redirect to Google's OAuth
    return redirect(url_for("google.login"))

# OAuth callback is handled by Flask-Dance automatically
# No need for a manual route here


@app.route('/oauth_debug')
def oauth_debug():
    """Debug route to help with OAuth setup"""
    if not GOOGLE_OAUTH_AVAILABLE:
        return render_template_string("""
        <html><body style="font-family: Arial; padding: 20px;">
        <h2>❌ Google OAuth Not Available</h2>
        <p>Flask-Dance is not properly installed.</p>
        <p>Run: <code>pip install flask-dance[sqla]</code></p>
        </body></html>
        """)

    if not google_bp:
        return render_template_string("""
        <html><body style="font-family: Arial; padding: 20px;">
        <h2>⚠️ Google OAuth Not Configured</h2>
        <p>Google OAuth credentials not found in environment variables.</p>
        <p>Check your .env file for GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET</p>
        </body></html>
        """)

    # Get the redirect URI that Flask-Dance is using
    try:
        redirect_uri = url_for("google.authorized", _external=True)
    except Exception as e:
        redirect_uri = f"Error getting redirect URI: {e}"

    client_id = app.config.get('GOOGLE_OAUTH_CLIENT_ID', 'Not set')

    return render_template_string("""
    <html><body style="font-family: Arial; padding: 20px; background: #f5f5f5;">
    <div style="background: white; padding: 30px; border-radius: 10px; max-width: 800px;">
        <h2 style="color: #28a745;">✅ Google OAuth Configuration Status</h2>
        
        <h3>📋 Current Configuration:</h3>
        <ul>
            <li><strong>Status:</strong> {{ status }}</li>
            <li><strong>Client ID:</strong> {{ client_id_display }}</li>
            <li><strong>Redirect URI:</strong> <code style="background: #e9ecef; padding: 2px 6px; border-radius: 3px;">{{ redirect_uri }}</code></li>
        </ul>
        
        <h3>🔧 Google Console Setup:</h3>
        <p>In your Google Cloud Console OAuth settings, make sure you have <strong>EXACTLY</strong> these redirect URIs:</p>
        <div style="background: #e9ecef; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <code>http://127.0.0.1:5000/auth/google/authorized</code><br>
            <code>http://localhost:5000/auth/google/authorized</code>
        </div>
        
        <h3>🌐 JavaScript Origins:</h3>
        <p>Also add these authorized JavaScript origins:</p>
        <div style="background: #e9ecef; padding: 15px; border-radius: 5px; margin: 10px 0;">
            <code>http://127.0.0.1:5000</code><br>
            <code>http://localhost:5000</code>
        </div>
        
        <h3>🔗 Quick Links:</h3>
        <ul>
            <li><a href="https://console.cloud.google.com/apis/credentials" target="_blank">Google Cloud Console - Credentials</a></li>
            <li><a href="{{ url_for('index') }}">Back to Todo App</a></li>
            <li><a href="{{ google_login_url }}" style="background: #4285f4; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">🔗 Test Google Login</a></li>
        </ul>
        
        <p style="margin-top: 30px; color: #6c757d; font-size: 14px;">
            💡 After updating Google Console, wait 1-2 minutes for changes to take effect.
        </p>
    </div>
    </body></html>
    """,
                                  status="✅ Configured and Ready",
                                  client_id_display=client_id[:20] + "..." if client_id and len(
                                      client_id) > 20 else client_id,
                                  redirect_uri=redirect_uri,
                                  google_login_url=url_for("google.login") if google_bp else "#")


@app.route('/test_google_auth')
def test_google_auth():
    """JSON endpoint for OAuth status"""
    return redirect(url_for('oauth_debug'))


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/settings')
@login_required
def settings():
    # Get user preferences from database
    user_prefs = mongo.db.user_preferences.find_one(
        {'user_id': current_user.id})
    if not user_prefs:
        # Create default preferences
        user_prefs = {
            'user_id': current_user.id,
            'default_priority': 'medium',
            'default_category': 'general',
            'date_format': 'MM/DD/YYYY',
            'theme': 'light',
            'goals_per_page': 20,
            'auto_archive': False,
            'show_animations': True,
            'confirm_delete': True,
            'email_notifications': True,
            'due_date_reminders': True,
            'weekly_summary': False
        }
        mongo.db.user_preferences.insert_one(user_prefs)

    return render_template('settings.html', preferences=user_prefs)


@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    try:
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()

        if not username or not email:
            flash('Username and email are required.', 'error')
            return redirect(url_for('settings'))

        # Check if username is already taken by another user
        existing_user = mongo.db.users.find_one({
            'username': username,
            '_id': {'$ne': ObjectId(current_user.id)}
        })
        if existing_user:
            flash('Username is already taken.', 'error')
            return redirect(url_for('settings'))

        # Check if email is already taken by another user
        existing_email = mongo.db.users.find_one({
            'email': email,
            '_id': {'$ne': ObjectId(current_user.id)}
        })
        if existing_email:
            flash('Email is already registered.', 'error')
            return redirect(url_for('settings'))

        # Update user profile
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'username': username, 'email': email}}
        )

        # Update current_user object
        current_user.username = username
        current_user.email = email

        flash('Profile updated successfully!', 'success')
        return redirect(url_for('settings'))

    except Exception as e:
        flash('An error occurred while updating profile.', 'error')
        return redirect(url_for('settings'))


@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    try:
        if current_user.google_id:
            flash('Cannot change password for Google accounts.', 'error')
            return redirect(url_for('settings'))

        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not all([current_password, new_password, confirm_password]):
            flash('All password fields are required.', 'error')
            return redirect(url_for('settings'))

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('settings'))

        if new_password != confirm_password:
            flash('New passwords do not match.', 'error')
            return redirect(url_for('settings'))

        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'error')
            return redirect(url_for('settings'))

        # Update password
        password_hash = generate_password_hash(new_password)
        mongo.db.users.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'password_hash': password_hash}}
        )

        flash('Password updated successfully!', 'success')
        return redirect(url_for('settings'))

    except Exception as e:
        flash('An error occurred while updating password.', 'error')
        return redirect(url_for('settings'))


@app.route('/update_preferences', methods=['POST'])
@login_required
def update_preferences():
    try:
        preferences = {
            'user_id': current_user.id,
            'default_priority': request.form.get('default_priority', 'medium'),
            'default_category': request.form.get('default_category', 'general'),
            'date_format': request.form.get('date_format', 'MM/DD/YYYY'),
            'theme': request.form.get('theme', 'light'),
            'goals_per_page': int(request.form.get('goals_per_page', 20)),
            'auto_archive': 'auto_archive' in request.form,
            'show_animations': 'show_animations' in request.form,
            'confirm_delete': 'confirm_delete' in request.form,
            'email_notifications': 'email_notifications' in request.form,
            'due_date_reminders': 'due_date_reminders' in request.form,
            'weekly_summary': 'weekly_summary' in request.form
        }

        # Update or insert preferences
        mongo.db.user_preferences.update_one(
            {'user_id': current_user.id},
            {'$set': preferences},
            upsert=True
        )

        flash('Preferences updated successfully!', 'success')
        return redirect(url_for('settings'))

    except Exception as e:
        flash('An error occurred while updating preferences.', 'error')
        return redirect(url_for('settings'))


@app.route('/export_data_pdf')
@login_required
def export_data_pdf():
    try:
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from io import BytesIO

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        styles = getSampleStyleSheet()
        story = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#667eea'),
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        story.append(Paragraph(f"Achievify Data Export", title_style))
        story.append(
            Paragraph(f"User: {current_user.username}", styles['Heading2']))
        story.append(Paragraph(
            f"Export Date: {datetime.now().strftime('%B %d, %Y')}", styles['Normal']))
        story.append(Spacer(1, 20))

        # Goals Section
        goals = list(mongo.db.goals.find({'user_id': current_user.id}))
        if goals:
            story.append(Paragraph("Goals Summary", styles['Heading2']))

            # Goals stats
            total_goals = len(goals)
            completed_goals = len(
                [g for g in goals if g.get('completed', False)])
            pending_goals = total_goals - completed_goals

            stats_data = [
                ['Total Goals', str(total_goals)],
                ['Completed', str(completed_goals)],
                ['Pending', str(pending_goals)],
                ['Completion Rate',
                    f"{round((completed_goals/total_goals)*100, 1) if total_goals > 0 else 0}%"]
            ]

            stats_table = Table(stats_data, colWidths=[2*inch, 1*inch])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(stats_table)
            story.append(Spacer(1, 20))

            # Goals list
            story.append(Paragraph("Goals List", styles['Heading3']))
            goals_data = [['Goal', 'Priority',
                           'Category', 'Status', 'Created']]

            for goal in goals:
                goals_data.append([
                    goal.get('text', '')[
                        :50] + ('...' if len(goal.get('text', '')) > 50 else ''),
                    goal.get('priority', 'medium').title(),
                    goal.get('category', 'general').title(),
                    'Completed' if goal.get('completed', False) else 'Pending',
                    goal.get('created_at').strftime(
                        '%m/%d/%Y') if goal.get('created_at') else 'N/A'
                ])

            goals_table = Table(goals_data)
            goals_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#667eea')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(goals_table)
        else:
            story.append(Paragraph("No goals found.", styles['Normal']))

        story.append(Spacer(1, 30))

        # Habits Section
        habits = list(mongo.db.habits.find({'user_id': current_user.id}))
        if habits:
            story.append(Paragraph("Habits Summary", styles['Heading2']))

            habits_data = [['Habit', 'Frequency', 'Target', 'Category']]
            for habit in habits:
                habits_data.append([
                    habit.get('name', '')[
                        :40] + ('...' if len(habit.get('name', '')) > 40 else ''),
                    habit.get('frequency', 'daily').title(),
                    str(habit.get('target_count', 1)),
                    habit.get('category', 'general').title()
                ])

            habits_table = Table(habits_data)
            habits_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#764ba2')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            story.append(habits_table)
        else:
            story.append(Paragraph("No habits found.", styles['Normal']))

        # Build PDF
        doc.build(story)
        buffer.seek(0)

        response = make_response(buffer.getvalue())
        response.headers['Content-Type'] = 'application/pdf'
        response.headers[
            'Content-Disposition'] = f'attachment; filename=achievify_report_{current_user.username}_{datetime.now().strftime("%Y%m%d")}.pdf'

        return response

    except ImportError:
        flash('PDF generation is not available. Please install reportlab.', 'error')
        return redirect(url_for('settings'))
    except Exception as e:
        print(f"PDF Export error: {e}")
        flash('An error occurred while generating PDF.', 'error')
        return redirect(url_for('settings'))


@app.route('/delete_all_goals', methods=['POST'])
@login_required
def delete_all_goals():
    try:
        confirm = request.form.get('confirm', '').lower()
        if confirm != 'delete':
            flash('Please type "delete" to confirm.', 'error')
            return redirect(url_for('settings'))

        # Delete all user's goals
        result = mongo.db.goals.delete_many({'user_id': current_user.id})
        flash(f'Successfully deleted {result.deleted_count} goals.', 'success')
        return redirect(url_for('settings'))

    except Exception as e:
        flash('An error occurred while deleting goals.', 'error')
        return redirect(url_for('settings'))


@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    try:
        confirm = request.form.get('confirm', '').lower()
        if confirm != 'delete':
            flash('Please type "delete" to confirm.', 'error')
            return redirect(url_for('settings'))

        user_id = current_user.id

        # Delete all user data
        mongo.db.goals.delete_many({'user_id': user_id})
        mongo.db.habits.delete_many({'user_id': user_id})
        mongo.db.habit_logs.delete_many({'user_id': user_id})
        mongo.db.bills.delete_many({'user_id': user_id})
        mongo.db.user_preferences.delete_many({'user_id': user_id})
        mongo.db.users.delete_one({'_id': ObjectId(user_id)})

        # Logout user
        logout_user()
        flash('Account deleted successfully.', 'success')
        return redirect(url_for('login'))

    except Exception as e:
        flash('An error occurred while deleting account.', 'error')
        return redirect(url_for('settings'))


@app.route('/analytics')
@login_required
def analytics():
    # Get comprehensive analytics data
    from datetime import datetime, timedelta

    # Goals analytics
    total_goals = mongo.db.goals.count_documents({'user_id': current_user.id})
    completed_goals = mongo.db.goals.count_documents(
        {'user_id': current_user.id, 'completed': True})

    # Goals by priority
    high_priority = mongo.db.goals.count_documents(
        {'user_id': current_user.id, 'priority': 'high'})
    medium_priority = mongo.db.goals.count_documents(
        {'user_id': current_user.id, 'priority': 'medium'})
    low_priority = mongo.db.goals.count_documents(
        {'user_id': current_user.id, 'priority': 'low'})

    # Goals by category
    categories = mongo.db.goals.distinct(
        'category', {'user_id': current_user.id})
    category_data = []
    for category in categories:
        count = mongo.db.goals.count_documents(
            {'user_id': current_user.id, 'category': category})
        category_data.append({'category': category, 'count': count})

    # Weekly progress (last 7 days)
    weekly_data = []
    for i in range(7):
        date = datetime.now() - timedelta(days=i)
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(
            hour=23, minute=59, second=59, microsecond=999999)

        completed_today = mongo.db.goals.count_documents({
            'user_id': current_user.id,
            'completed': True,
            'updated_at': {'$gte': start_of_day, '$lte': end_of_day}
        })

        weekly_data.append({
            'date': date.strftime('%a'),
            'completed': completed_today
        })

    weekly_data.reverse()  # Show oldest to newest

    # Calculate current streak (consecutive days with completed goals)
    current_streak = 0
    for i in range(30):  # Check last 30 days
        date = datetime.now() - timedelta(days=i)
        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = date.replace(
            hour=23, minute=59, second=59, microsecond=999999)

        completed_that_day = mongo.db.goals.count_documents({
            'user_id': current_user.id,
            'completed': True,
            'updated_at': {'$gte': start_of_day, '$lte': end_of_day}
        })

        if completed_that_day > 0:
            current_streak += 1
        else:
            break

    # Calculate user level based on completed goals
    def get_user_level(completed_goals):
        if completed_goals >= 100:
            return "Goal Master"
        elif completed_goals >= 50:
            return "Goal Expert"
        elif completed_goals >= 25:
            return "Goal Achiever"
        elif completed_goals >= 10:
            return "Goal Seeker"
        elif completed_goals >= 5:
            return "Goal Starter"
        else:
            return "Newcomer"

    user_level = get_user_level(completed_goals)

    # Calculate achievements (completed goals milestones)
    achievements_count = 0
    milestones = [1, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150]
    for milestone in milestones:
        if completed_goals >= milestone:
            achievements_count += 1

    # Calculate monthly improvement
    last_month_start = (datetime.now() - timedelta(days=30)
                        ).replace(hour=0, minute=0, second=0, microsecond=0)
    last_month_completed = mongo.db.goals.count_documents({
        'user_id': current_user.id,
        'completed': True,
        'updated_at': {'$gte': last_month_start}
    })

    previous_month_start = (datetime.now() - timedelta(days=60)
                            ).replace(hour=0, minute=0, second=0, microsecond=0)
    previous_month_end = last_month_start
    previous_month_completed = mongo.db.goals.count_documents({
        'user_id': current_user.id,
        'completed': True,
        'updated_at': {'$gte': previous_month_start, '$lt': previous_month_end}
    })

    monthly_improvement = 0
    if previous_month_completed > 0:
        monthly_improvement = round(
            ((last_month_completed - previous_month_completed) / previous_month_completed) * 100, 1)

    # Find most productive time (hour when most goals are completed)
    most_productive_hour = 9  # Default to morning
    hour_counts = {}

    completed_goals_cursor = mongo.db.goals.find({
        'user_id': current_user.id,
        'completed': True,
        'updated_at': {'$exists': True}
    })

    for goal in completed_goals_cursor:
        if 'updated_at' in goal and goal['updated_at']:
            hour = goal['updated_at'].hour
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

    if hour_counts:
        most_productive_hour = max(hour_counts, key=hour_counts.get)

    def get_time_of_day(hour):
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"

    most_productive_time = get_time_of_day(most_productive_hour)

    # HABIT ANALYTICS
    from bson.objectid import ObjectId

    # Get all user habits
    user_habits = Habit.find_by_user_id(current_user.id)
    total_habits = len(user_habits)

    # Habit completion stats
    active_habits = 0
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    habits_completed_today = 0
    habit_categories = {}
    habit_frequency_breakdown = {'Daily': 0, 'Weekly': 0, 'Monthly': 0}

    # Weekly habit progress
    habit_weekly_data = []
    for i in range(7):
        date = datetime.now().replace(hour=0, minute=0, second=0,
                                      microsecond=0) - timedelta(days=i)
        completed_count = 0

        for habit in user_habits:
            habit_object_id = ObjectId(habit.id)
            log = mongo.db.habit_logs.find_one({
                'habit_id': habit_object_id,
                'user_id': current_user.id,
                'date': date
            })
            if log and log.get('completed', False):
                completed_count += 1

        habit_weekly_data.append({
            'date': date.strftime('%a'),
            'completed': completed_count
        })

    habit_weekly_data.reverse()  # Show oldest to newest

    # Calculate habit statistics
    total_habit_logs = 0
    completed_habit_logs = 0
    habit_streaks = []

    for habit in user_habits:
        habit_object_id = ObjectId(habit.id)

        # Count habit in frequency breakdown
        frequency = getattr(habit, 'frequency', 'daily')
        # Normalize frequency values to match our breakdown keys
        if frequency.lower() == 'daily':
            habit_frequency_breakdown['Daily'] += 1
        elif frequency.lower() == 'weekly':
            habit_frequency_breakdown['Weekly'] += 1
        elif frequency.lower() == 'monthly':
            habit_frequency_breakdown['Monthly'] += 1
        else:
            # Default unknown frequencies to daily
            habit_frequency_breakdown['Daily'] += 1

        # Count habit in category breakdown
        category = getattr(habit, 'category', 'general')
        habit_categories[category] = habit_categories.get(category, 0) + 1

        # Check if habit is active (has logs in last 7 days)
        recent_logs = mongo.db.habit_logs.count_documents({
            'habit_id': habit_object_id,
            'user_id': current_user.id,
            'date': {'$gte': datetime.now() - timedelta(days=7)}
        })
        if recent_logs > 0:
            active_habits += 1

        # Check today's completion
        today_log = mongo.db.habit_logs.find_one({
            'habit_id': habit_object_id,
            'user_id': current_user.id,
            'date': today
        })
        if today_log and today_log.get('completed', False):
            habits_completed_today += 1

        # Calculate individual habit streak
        streak = 0
        current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        for i in range(365):  # Check up to 365 days back
            check_date = current_date - timedelta(days=i)
            log = mongo.db.habit_logs.find_one({
                'habit_id': habit_object_id,
                'user_id': current_user.id,
                'date': check_date
            })

            if log and log.get('completed', False):
                streak += 1
            else:
                break

        habit_streaks.append(streak)

        # Count total logs for this habit
        habit_logs_count = mongo.db.habit_logs.count_documents({
            'habit_id': habit_object_id,
            'user_id': current_user.id
        })
        total_habit_logs += habit_logs_count

        # Count completed logs for this habit
        completed_logs_count = mongo.db.habit_logs.count_documents({
            'habit_id': habit_object_id,
            'user_id': current_user.id,
            'completed': True
        })
        completed_habit_logs += completed_logs_count

    # Calculate habit completion rate
    habit_completion_rate = 0
    if total_habit_logs > 0:
        habit_completion_rate = round(
            (completed_habit_logs / total_habit_logs) * 100, 1)

    # Find longest streak
    longest_habit_streak = max(habit_streaks) if habit_streaks else 0

    # Calculate average streak
    average_habit_streak = round(
        sum(habit_streaks) / len(habit_streaks), 1) if habit_streaks else 0

    # Convert habit categories to list format for charts
    habit_category_data = []
    for category, count in habit_categories.items():
        habit_category_data.append({'category': category, 'count': count})

    analytics_data = {
        'goals': {
            'total': total_goals,
            'completed': completed_goals,
            'pending': total_goals - completed_goals,
            'completion_rate': round((completed_goals / total_goals * 100) if total_goals > 0 else 0, 1)
        },
        'priority_breakdown': {
            'high': high_priority,
            'medium': medium_priority,
            'low': low_priority
        },
        'categories': category_data,
        'weekly_progress': weekly_data,
        'achievements': {
            'current_streak': current_streak,
            'user_level': user_level,
            'achievements_count': achievements_count,
            'monthly_improvement': monthly_improvement,
            'most_productive_time': most_productive_time
        },
        'habits': {
            'total': total_habits,
            'active': active_habits,
            'completed_today': habits_completed_today,
            'completion_rate': habit_completion_rate,
            'longest_streak': longest_habit_streak,
            'average_streak': average_habit_streak
        },
        'habit_categories': habit_category_data,
        'habit_frequency_breakdown': habit_frequency_breakdown,
        'habit_weekly_progress': habit_weekly_data
    }

    return render_template('analytics.html', data=analytics_data)


@app.route('/habits')
@login_required
def habits():
    user_habits = Habit.find_by_user_id(current_user.id)

    # Get today's logs for each habit
    today = datetime.now().replace(hour=0, minute=0, second=0,
                                   microsecond=0)  # Use datetime for MongoDB
    habit_stats = []

    for habit in user_habits:
        # Convert habit.id to ObjectId for MongoDB queries
        from bson.objectid import ObjectId
        habit_object_id = ObjectId(habit.id)

        # Get today's log
        today_log = mongo.db.habit_logs.find_one({
            'habit_id': habit_object_id,
            'user_id': current_user.id,
            'date': today
        })

        # Calculate streak
        streak = 0
        current_date = today
        while True:
            log = mongo.db.habit_logs.find_one({
                'habit_id': habit_object_id,
                'user_id': current_user.id,
                'date': current_date
            })
            if log and log['completed_count'] >= habit.target_count:
                streak += 1
                current_date = current_date - timedelta(days=1)
            else:
                break

        # Calculate total completions for this habit
        total_completions = 0
        all_logs = mongo.db.habit_logs.find({
            'habit_id': habit_object_id,
            'user_id': current_user.id
        })
        for log in all_logs:
            total_completions += log.get('completed_count', 0)

        habit_stats.append({
            'habit': habit,
            'completed_today': today_log['completed_count'] if today_log else 0,
            'target_met': (today_log['completed_count'] if today_log else 0) >= habit.target_count,
            'streak': streak,
            'total_completions': total_completions
        })

    return render_template('habits.html', habit_stats=habit_stats)


@app.route('/bills')
@login_required
def bills():
    # Get recent bills
    milk_bills = UtilityBill.find_by_user_and_type(
        current_user.id, 'milk')[:10]
    water_bills = UtilityBill.find_by_user_and_type(
        current_user.id, 'water')[:10]

    # Calculate monthly totals
    from datetime import datetime
    current_month = datetime.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0)

    milk_monthly = mongo.db.utility_bills.aggregate([
        {
            '$match': {
                'user_id': current_user.id,
                'bill_type': 'milk',
                'date': {'$gte': current_month}
            }
        },
        {
            '$group': {
                '_id': None,
                'total_amount': {'$sum': '$amount'},
                'total_consumption': {'$sum': '$consumption'}
            }
        }
    ])

    water_monthly = mongo.db.utility_bills.aggregate([
        {
            '$match': {
                'user_id': current_user.id,
                'bill_type': 'water',
                'date': {'$gte': current_month}
            }
        },
        {
            '$group': {
                '_id': None,
                'total_amount': {'$sum': '$amount'},
                'total_consumption': {'$sum': '$consumption'}
            }
        }
    ])

    milk_stats = list(milk_monthly)
    water_stats = list(water_monthly)

    monthly_data = {
        'milk': {
            'amount': milk_stats[0]['total_amount'] if milk_stats else 0,
            'consumption': milk_stats[0]['total_consumption'] if milk_stats else 0
        },
        'water': {
            'amount': water_stats[0]['total_amount'] if water_stats else 0,
            'consumption': water_stats[0]['total_consumption'] if water_stats else 0
        }
    }

    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')

    return render_template('bills.html',
                           milk_bills=milk_bills,
                           water_bills=water_bills,
                           monthly_data=monthly_data,
                           today=today)


@app.route('/add_habit', methods=['POST'])
@login_required
def add_habit():
    name = request.form.get('name')
    description = request.form.get('description')
    frequency = request.form.get('frequency', 'daily')
    target_count = int(request.form.get('target_count', 1))
    category = request.form.get('category', 'general')

    habit = Habit(
        name=name,
        user_id=current_user.id,
        frequency=frequency,
        target_count=target_count,
        description=description,
        category=category
    )
    habit.save()

    flash('Habit created successfully!', 'success')
    return redirect(url_for('habits'))


@app.route('/log_habit/<habit_id>', methods=['POST'])
@login_required
def log_habit(habit_id):
    try:
        # Find the habit
        habit_data = mongo.db.habits.find_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id})
        if not habit_data:
            return jsonify({'success': False, 'message': 'Habit not found'})

        # Get today's date
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if already logged today
        existing_log = mongo.db.habit_logs.find_one({
            'habit_id': ObjectId(habit_id),
            'user_id': current_user.id,
            'date': today
        })

        if existing_log:
            # Increment count
            mongo.db.habit_logs.update_one(
                {'_id': existing_log['_id']},
                {'$inc': {'completed_count': 1}}
            )
        else:
            # Create new log
            log = HabitLog(
                habit_id=habit_id,
                user_id=current_user.id,
                completed_count=1
            )
            log.save()

        return jsonify({'success': True, 'message': 'Progress logged successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/add_bill', methods=['POST'])
@login_required
def add_bill():
    bill_type = request.form.get('bill_type')
    amount = float(request.form.get('amount', 0))
    consumption = float(request.form.get('consumption', 0))
    unit = request.form.get('unit', 'liters')
    notes = request.form.get('notes')
    bill_date = request.form.get('date')

    # Convert date string to date object
    from datetime import datetime
    if bill_date:
        date_obj = datetime.strptime(bill_date, '%Y-%m-%d').date()
    else:
        date_obj = datetime.now().date()

    bill = UtilityBill(
        bill_type=bill_type,
        user_id=current_user.id,
        amount=amount,
        consumption=consumption,
        unit=unit,
        notes=notes,
        date=date_obj
    )
    bill.save()

    flash(f'{bill_type.title()} bill added successfully!', 'success')
    return redirect(url_for('bills'))


@app.route('/get_habit/<habit_id>')
@login_required
def get_habit(habit_id):
    try:
        from bson.objectid import ObjectId
        habit = mongo.db.habits.find_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id})
        if not habit:
            return jsonify({'success': False, 'message': 'Habit not found'})

        habit_data = {
            'id': str(habit['_id']),
            'name': habit['name'],
            'description': habit.get('description', ''),
            'frequency': habit['frequency'],
            'target_count': habit['target_count'],
            'category': habit['category']
        }

        return jsonify({'success': True, 'habit': habit_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/edit_habit/<habit_id>', methods=['POST'])
@login_required
def edit_habit(habit_id):
    try:
        from bson.objectid import ObjectId
        habit = mongo.db.habits.find_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id})
        if not habit:
            flash('Habit not found', 'error')
            return redirect(url_for('habits'))

        # Get form data
        name = request.form.get('name')
        description = request.form.get('description')
        frequency = request.form.get('frequency', 'daily')
        target_count = int(request.form.get('target_count', 1))
        category = request.form.get('category', 'general')

        # Update the habit
        mongo.db.habits.update_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id},
            {'$set': {
                'name': name,
                'description': description,
                'frequency': frequency,
                'target_count': target_count,
                'category': category
            }}
        )

        flash('Habit updated successfully!', 'success')
        return redirect(url_for('habits'))
    except Exception as e:
        flash(f'Error updating habit: {str(e)}', 'error')
        return redirect(url_for('habits'))


@app.route('/delete_habit/<habit_id>', methods=['DELETE'])
@login_required
def delete_habit(habit_id):
    try:
        from bson.objectid import ObjectId
        habit = mongo.db.habits.find_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id})
        if not habit:
            return jsonify({'success': False, 'message': 'Habit not found'})

        # Delete the habit and its logs
        mongo.db.habits.delete_one(
            {'_id': ObjectId(habit_id), 'user_id': current_user.id})
        mongo.db.habit_logs.delete_many({'habit_id': ObjectId(habit_id)})

        return jsonify({'success': True, 'message': 'Habit deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/get_bill/<bill_id>')
@login_required
def get_bill(bill_id):
    try:
        from bson.objectid import ObjectId
        bill = mongo.db.utility_bills.find_one(
            {'_id': ObjectId(bill_id), 'user_id': current_user.id})
        if not bill:
            return jsonify({'success': False, 'message': 'Bill not found'})

        # Convert date to string format
        bill_data = {
            'id': str(bill['_id']),
            'bill_type': bill['bill_type'],
            'amount': bill['amount'],
            'consumption': bill['consumption'],
            'unit': bill['unit'],
            'date': bill['date'].strftime('%Y-%m-%d') if bill['date'] else '',
            'notes': bill.get('notes', '')
        }

        return jsonify({'success': True, 'bill': bill_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/edit_bill/<bill_id>', methods=['POST'])
@login_required
def edit_bill(bill_id):
    try:
        from bson.objectid import ObjectId
        bill = mongo.db.utility_bills.find_one(
            {'_id': ObjectId(bill_id), 'user_id': current_user.id})
        if not bill:
            flash('Bill not found', 'error')
            return redirect(url_for('bills'))

        # Get form data
        bill_type = request.form.get('bill_type')
        amount = float(request.form.get('amount', 0))
        consumption = float(request.form.get('consumption', 0))
        unit = request.form.get('unit', 'liters')
        notes = request.form.get('notes')
        bill_date = request.form.get('date')

        # Convert date string to datetime object
        from datetime import datetime
        if bill_date:
            date_obj = datetime.strptime(bill_date, '%Y-%m-%d')
        else:
            date_obj = datetime.now()

        # Update the bill
        mongo.db.utility_bills.update_one(
            {'_id': ObjectId(bill_id), 'user_id': current_user.id},
            {'$set': {
                'bill_type': bill_type,
                'amount': amount,
                'consumption': consumption,
                'unit': unit,
                'notes': notes,
                'date': date_obj
            }}
        )

        flash(f'{bill_type.title()} bill updated successfully!', 'success')
        return redirect(url_for('bills'))
    except Exception as e:
        flash(f'Error updating bill: {str(e)}', 'error')
        return redirect(url_for('bills'))


@app.route('/export_bills/<bill_type>')
@login_required
def export_bills(bill_type):
    try:
        from flask import make_response
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from io import BytesIO

        # Get bills of specified type
        bills = list(mongo.db.utility_bills.find({
            'user_id': current_user.id,
            'bill_type': bill_type
        }).sort('date', 1))

        # Create PDF buffer
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

        # Container for the 'Flowable' objects
        elements = []

        # Register fonts that support Unicode including rupee symbol
        try:
            # Try to register Arial Unicode MS if available (supports rupee symbol)
            pdfmetrics.registerFont(TTFont('Arial-Unicode', 'arial.ttf'))
            font_name = 'Arial-Unicode'
        except:
            try:
                # Fallback to DejaVu Sans which also supports rupee symbol
                pdfmetrics.registerFont(
                    TTFont('DejaVu-Sans', 'DejaVuSans.ttf'))
                font_name = 'DejaVu-Sans'
            except:
                # Use default Helvetica and replace rupee symbol with Rs.
                font_name = 'Helvetica'

        # Define styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName=font_name,
            fontSize=18,
            spaceAfter=30,
            alignment=1,  # Center alignment
            textColor=colors.HexColor('#2563eb')
        )

        # Add title
        bill_type_formatted = bill_type.replace('_', ' ').title()
        title = Paragraph(f"{bill_type_formatted} Bills Report", title_style)
        elements.append(title)

        # Add user info and date
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName=font_name
        )
        user_info = Paragraph(
            f"<b>User:</b> {current_user.username}<br/><b>Generated on:</b> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", normal_style)
        elements.append(user_info)
        elements.append(Spacer(1, 20))

        if bills:
            # Use appropriate currency symbol based on font support
            currency_symbol = "₹" if font_name in [
                'Arial-Unicode', 'DejaVu-Sans'] else "Rs."

            # Create table data
            data = [['Date', f'Amount ({currency_symbol})', 'Consumption',
                     'Unit', f'Rate/Unit ({currency_symbol})', 'Notes']]

            total_amount = 0
            total_consumption = 0

            for bill in bills:
                rate_per_unit = bill['amount'] / \
                    bill['consumption'] if bill['consumption'] > 0 else 0
                total_amount += bill['amount']
                total_consumption += bill['consumption']

                data.append([
                    bill['date'].strftime(
                        '%d-%m-%Y') if bill['date'] else 'N/A',
                    f"{currency_symbol}{bill['amount']:.2f}",
                    f"{bill['consumption']:.2f}",
                    bill['unit'],
                    f"{currency_symbol}{rate_per_unit:.2f}",
                    bill.get('notes', '')[
                        :30] + '...' if len(bill.get('notes', '')) > 30 else bill.get('notes', '')
                ])

            # Add summary row
            avg_rate = total_amount / total_consumption if total_consumption > 0 else 0
            data.append(['TOTAL', f"{currency_symbol}{total_amount:.2f}",
                        f"{total_consumption:.2f}", '-', f"{currency_symbol}{avg_rate:.2f}", 'Summary'])

            # Create table
            table = Table(data, colWidths=[
                          1.2*inch, 1*inch, 1*inch, 0.8*inch, 1*inch, 1.5*inch])

            # Add style to table
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0),
                 f'{font_name}-Bold' if font_name == 'Helvetica' else font_name),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
                ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#f3f4f6')),
                ('FONTNAME', (0, -1), (-1, -1),
                 f'{font_name}-Bold' if font_name == 'Helvetica' else font_name),
                ('TEXTCOLOR', (0, -1), (-1, -1), colors.HexColor('#1f2937')),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, 1), (-1, -2), font_name),
                ('FONTSIZE', (0, 1), (-1, -1), 9),
                ('ROWBACKGROUNDS', (0, 1), (-1, -2),
                 [colors.white, colors.HexColor('#f9fafb')])
            ]))

            elements.append(table)

            # Add summary statistics
            elements.append(Spacer(1, 20))
            summary_style = ParagraphStyle(
                'Summary',
                parent=styles['Normal'],
                fontName=font_name,
                fontSize=10,
                leftIndent=20
            )

            summary_text = f"""
            <b>Summary Statistics:</b><br/>
            • Total Bills: {len(bills)}<br/>
            • Total Amount: {currency_symbol}{total_amount:.2f}<br/>
            • Total Consumption: {total_consumption:.2f} {bills[0]['unit'] if bills else 'units'}<br/>
            • Average Rate: {currency_symbol}{avg_rate:.2f} per unit<br/>
            • Report Period: {bills[-1]['date'].strftime('%B %Y') if bills else 'N/A'} to {bills[0]['date'].strftime('%B %Y') if bills else 'N/A'}
            """

            summary = Paragraph(summary_text, summary_style)
            elements.append(summary)

        else:
            no_data = Paragraph(
                "No bills found for this category.", styles['Normal'])
            elements.append(no_data)

        # Build PDF
        doc.build(elements)

        # FileResponse
        buffer.seek(0)
        response = make_response(buffer.getvalue())
        response.headers['Content-Disposition'] = f'attachment; filename={bill_type}_bills_{datetime.now().strftime("%Y%m%d")}.pdf'
        response.headers['Content-Type'] = 'application/pdf'

        return response

    except Exception as e:
        flash(f'Error exporting bills: {str(e)}', 'error')
        return redirect(url_for('bills'))


@app.route('/delete_bill/<bill_id>', methods=['DELETE'])
@login_required
def delete_bill(bill_id):
    try:
        from bson.objectid import ObjectId
        bill = mongo.db.utility_bills.find_one(
            {'_id': ObjectId(bill_id), 'user_id': current_user.id})
        if not bill:
            return jsonify({'success': False, 'message': 'Bill not found'})

        mongo.db.utility_bills.delete_one(
            {'_id': ObjectId(bill_id), 'user_id': current_user.id})
        return jsonify({'success': True, 'message': 'Bill deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/stats')
@login_required
def api_stats():
    total = mongo.db.goals.count_documents({'user_id': current_user.id})
    completed = mongo.db.goals.count_documents(
        {'user_id': current_user.id, 'completed': True})
    pending = total - completed

    return jsonify({
        'total': total,
        'completed': completed,
        'pending': pending
    })

# Initialize Google OAuth after app context


def setup_google_oauth():
    global google_bp
    if GOOGLE_OAUTH_AVAILABLE:
        try:
            if app.config.get('GOOGLE_OAUTH_CLIENT_ID') and app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'):
                google_bp = make_google_blueprint(
                    client_id=app.config.get('GOOGLE_OAUTH_CLIENT_ID'),
                    client_secret=app.config.get('GOOGLE_OAUTH_CLIENT_SECRET'),
                    scope=["openid", "https://www.googleapis.com/auth/userinfo.email",
                           "https://www.googleapis.com/auth/userinfo.profile"],
                    redirect_to="index"  # Redirect to index after successful login
                )
                app.register_blueprint(google_bp, url_prefix="/auth")

                # Use session-based storage instead of database storage to avoid user issues
                # This is simpler and works better for most use cases
                # Tokens will be stored in the session rather than the database

                # Handle OAuth authorization callback
                @oauth_authorized.connect_via(google_bp)
                def google_logged_in(blueprint, token):
                    if not token:
                        flash('Failed to log in with Google.', 'error')
                        return redirect(url_for('login'))

                    try:
                        resp = blueprint.session.get("/oauth2/v2/userinfo")
                        if not resp.ok:
                            flash('Failed to fetch user info from Google.', 'error')
                            return redirect(url_for('login'))

                        google_info = resp.json()
                        google_user_id = str(google_info['id'])

                        # Find or create user
                        user = User.find_by_google_id(google_user_id)
                        if not user:
                            # Check if user exists with same email
                            user = User.find_by_email(google_info['email'])
                            if user:
                                # Link existing account to Google
                                user.google_id = google_user_id
                                user.save()
                            else:
                                # Create new user with unique username
                                username = google_info.get(
                                    'name', google_info['email']).replace(' ', '_').lower()
                                existing_user = User.find_by_username(username)
                                counter = 1
                                original_username = username
                                while existing_user:
                                    username = f"{original_username}_{counter}"
                                    existing_user = User.find_by_username(
                                        username)
                                    counter += 1

                                user = User(
                                    username=username,
                                    email=google_info['email'],
                                    google_id=google_user_id
                                )
                                user.save()
                        login_user(user, remember=True)
                        flash(
                            f'Successfully logged in with Google as {user.username}!', 'success')
                        return redirect(url_for('index'))

                    except Exception as e:
                        print(f"Google OAuth error: {e}")
                        flash('Google login failed. Please try again.', 'error')
                        return redirect(url_for('login'))

                print("Google OAuth configured successfully!")
                return True
            else:
                print("Google OAuth credentials not found in environment variables.")
                return False
        except Exception as e:
            print(f"Warning: Google OAuth setup failed: {e}")
            google_bp = None
            return False
    return False


# Error handlers for better debugging in production
@app.errorhandler(500)
def internal_error(error):
    print(f"Internal Server Error: {error}")
    return f"Internal Server Error: {str(error)}", 500

@app.errorhandler(Exception)
def handle_exception(e):
    print(f"Unhandled Exception: {e}")
    if os.environ.get('FLASK_ENV') == 'production':
        return "An error occurred. Please try again later.", 500
    else:
        return f"Error: {str(e)}", 500


if __name__ == "__main__":
    with app.app_context():
        # MongoDB doesn't need table creation like SQLite
        # Collections are created automatically when first document is inserted
        setup_google_oauth()
    app.run(debug=True)
