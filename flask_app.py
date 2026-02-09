from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import os
import requests  # Added for reCAPTCHA verification

app = Flask(__name__)
CORS(app)

# הגדרת בסיס הנתונים
db_path = os.path.join(os.path.dirname(__file__), 'gemara.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- הגדרות reCAPTCHA ---
# עליך להדביק כאן את ה-Secret Key שקיבלת מגוגל במקום הטקסט הקיים
RECAPTCHA_SECRET_KEY = "PASTE_YOUR_SECRET_KEY_HERE"

# --- מודלים ---

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(100))
    role = db.Column(db.String(20))

class Progress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    key = db.Column(db.String(100))
    is_done = db.Column(db.Boolean, default=False)

# --- עדכון סיסמת אדמין ---
with app.app_context():
    db.create_all()
    # בדיקה אם האדמין קיים
    admin = User.query.filter_by(username='admin').first()
    if admin:
        # אם קיים - עדכן לו את הסיסמה
        admin.password = 'Briga2026'
    else:
        # אם לא קיים - צור חדש עם הסיסמה החדשה
        admin = User(username='admin', password='Briga2026', role='admin')
        db.session.add(admin)

    db.session.commit()

# --- נתיבים (API) ---

@app.route('/')
def hello():
    return "Gemara Server is Online (Password Updated)"

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    
    # 1. אימות reCAPTCHA
    recaptcha_token = data.get('recaptcha_token')
    if recaptcha_token:  # אם נשלח טוקן (מהגרסה החדשה של האתר)
        verify_url = 'https://www.google.com/recaptcha/api/siteverify'
        payload = {
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_token
        }
        try:
            r = requests.post(verify_url, data=payload)
            result = r.json()
            
            # בדיקה אם האימות הצליח ואם הציון גבוה מספיק (0.0 עד 1.0)
            if not result.get('success', False) or result.get('score', 0) < 0.5:
                 return jsonify({'ok': False, 'error': 'Bot detected (reCAPTCHA failed)'}), 403
        except Exception as e:
            # במקרה של שגיאת תקשורת עם גוגל, נרשום לוג אבל אולי נאפשר כניסה או נחסום לשיקולך
            print(f"Recaptcha Error: {e}")
            return jsonify({'ok': False, 'error': 'Recaptcha verification error'}), 500

    # 2. המשך תהליך הלוגין הרגיל
    username = data.get('username')
    password = data.get('password')

    user = User.query.filter_by(username=username, password=password).first()

    if user:
        return jsonify({
            'ok': True,
            'user': {'id': user.id, 'name': user.username, 'role': user.role}
        })
    else:
        return jsonify({'ok': False, 'error': 'שם משתמש או סיסמה שגויים'}), 401

@app.route('/api/users', methods=['GET', 'POST'])
def manage_users():
    if request.method == 'GET':
        users = User.query.all()
        return jsonify([{'id': u.id, 'username': u.username, 'role': u.role} for u in users])

    if request.method == 'POST':
        data = request.json
        if User.query.filter_by(username=data.get('username')).first():
             return jsonify({'ok': False, 'error': 'משתמש קיים'}), 400

        new_user = User(
            username=data.get('username'),
            password=data.get('password'),
            role=data.get('role', 'student')
        )
        db.session.add(new_user)
        db.session.commit()
        return jsonify({'ok': True})

@app.route('/api/get_progress', methods=['GET'])
def get_progress():
    user_id = request.args.get('user_id')
    results = Progress.query.filter_by(user_id=user_id, is_done=True).all()
    return jsonify([p.key for p in results])

@app.route('/api/toggle_page', methods=['POST'])
def toggle_page():
    data = request.json
    user_id = data.get('user_id')
    key = data.get('key')
    force_state = data.get('force_state')

    prog = Progress.query.filter_by(user_id=user_id, key=key).first()

    if prog:
        if force_state is not None:
            prog.is_done = force_state
        else:
            prog.is_done = not prog.is_done
    else:
        initial_state = force_state if force_state is not None else True
        prog = Progress(user_id=user_id, key=key, is_done=initial_state)
        db.session.add(prog)

    db.session.commit()
    return jsonify({'status': 'success', 'is_done': prog.is_done})
