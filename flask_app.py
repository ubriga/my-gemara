from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import os
import requests
from datetime import datetime

app = Flask(__name__)
CORS(app)

# הגדרת בסיס הנתונים
db_path = os.path.join(os.path.dirname(__file__), 'gemara.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- הגדרות reCAPTCHA ---
RECAPTCHA_SECRET_KEY = "6LdspWUsAAAAAMM6QVENPS4VFUrsYUnjMh_4Ke4h"

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

class LastPosition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, unique=True)
    track_id = db.Column(db.String(50))
    section_id = db.Column(db.String(50))
    book_id = db.Column(db.String(100))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Dedication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20))  # 'neshama' or 'refua'
    content = db.Column(db.Text)
    font = db.Column(db.String(50), default='Heebo')
    font_size = db.Column(db.Integer, default=16)
    bold = db.Column(db.Boolean, default=False)
    italic = db.Column(db.Boolean, default=False)
    underline = db.Column(db.Boolean, default=False)
    color = db.Column(db.String(20), default='#000000')
    align = db.Column(db.String(10), default='right')
    end_date = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

# --- אתחול בסיס נתונים ---
with app.app_context():
    db.create_all()
    # בדיקה אם האדמין קיים
    admin = User.query.filter_by(username='admin').first()
    if admin:
        admin.password = 'Briga2026'
    else:
        admin = User(username='admin', password='Briga2026', role='admin')
        db.session.add(admin)

    db.session.commit()
    
    # בדיקה והסרת הקדשות שפג תוקפן
    now = datetime.utcnow()
    expired = Dedication.query.filter(Dedication.end_date <= now, Dedication.is_active == True).all()
    for ded in expired:
        ded.is_active = False
        ded.ended_at = now
    db.session.commit()

# --- נתיבים (API) ---

@app.route('/')
def hello():
    return "Gemara Server is Online (with LastPosition feature)"

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    
    # אימות reCAPTCHA
    recaptcha_token = data.get('recaptcha_token')
    if recaptcha_token:
        verify_url = 'https://www.google.com/recaptcha/api/siteverify'
        payload = {
            'secret': RECAPTCHA_SECRET_KEY,
            'response': recaptcha_token
        }
        try:
            r = requests.post(verify_url, data=payload)
            result = r.json()
            
            if not result.get('success', False) or result.get('score', 0) < 0.5:
                 return jsonify({'ok': False, 'error': 'Bot detected (reCAPTCHA failed)'}), 403
        except Exception as e:
            print(f"Recaptcha Error: {e}")
            return jsonify({'ok': False, 'error': 'Recaptcha verification error'}), 500

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

# --- API למיקום אחרון ---

@app.route('/api/last_position', methods=['GET'])
def get_last_position():
    """קבלת המיקום האחרון של משתמש"""
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'ok': False, 'error': 'Missing user_id'}), 400
    
    pos = LastPosition.query.filter_by(user_id=user_id).first()
    if pos:
        return jsonify({
            'ok': True,
            'position': {
                'track_id': pos.track_id,
                'section_id': pos.section_id,
                'book_id': pos.book_id
            }
        })
    else:
        return jsonify({'ok': False, 'error': 'No saved position'}), 404

@app.route('/api/last_position', methods=['POST'])
def save_last_position():
    """שמירת המיקום האחרון של משתמש"""
    data = request.json
    user_id = data.get('user_id')
    track_id = data.get('track_id')
    section_id = data.get('section_id')
    book_id = data.get('book_id')
    
    if not all([user_id, track_id, section_id, book_id]):
        return jsonify({'ok': False, 'error': 'Missing required fields'}), 400
    
    pos = LastPosition.query.filter_by(user_id=user_id).first()
    
    if pos:
        pos.track_id = track_id
        pos.section_id = section_id
        pos.book_id = book_id
        pos.updated_at = datetime.utcnow()
    else:
        pos = LastPosition(
            user_id=user_id,
            track_id=track_id,
            section_id=section_id,
            book_id=book_id
        )
        db.session.add(pos)
    
    db.session.commit()
    return jsonify({'ok': True})

# --- API להקדשות ---

@app.route('/api/dedications', methods=['GET'])
def get_dedications():
    """קבלת כל ההקדשות הפעילות"""
    now = datetime.utcnow()
    
    # עדכון סטטוס הקדשות שפג תוקפן
    expired = Dedication.query.filter(Dedication.end_date <= now, Dedication.is_active == True).all()
    for ded in expired:
        ded.is_active = False
        ded.ended_at = now
    db.session.commit()
    
    # החזרת הקדשות פעילות בלבד
    active = Dedication.query.filter_by(is_active=True).all()
    return jsonify([{
        'id': d.id,
        'type': d.type,
        'content': d.content,
        'font': d.font,
        'font_size': d.font_size,
        'bold': d.bold,
        'italic': d.italic,
        'underline': d.underline,
        'color': d.color,
        'align': d.align,
        'end_date': d.end_date.isoformat() if d.end_date else None,
        'created_at': d.created_at.isoformat() if d.created_at else None
    } for d in active])

@app.route('/api/dedications/all', methods=['GET'])
def get_all_dedications():
    """קבלת כל ההקדשות כולל לא פעילות (לאדמין)"""
    all_deds = Dedication.query.order_by(Dedication.created_at.desc()).all()
    return jsonify([{
        'id': d.id,
        'type': d.type,
        'content': d.content,
        'font': d.font,
        'font_size': d.font_size,
        'bold': d.bold,
        'italic': d.italic,
        'underline': d.underline,
        'color': d.color,
        'align': d.align,
        'end_date': d.end_date.isoformat() if d.end_date else None,
        'created_at': d.created_at.isoformat() if d.created_at else None,
        'ended_at': d.ended_at.isoformat() if d.ended_at else None,
        'is_active': d.is_active
    } for d in all_deds])

@app.route('/api/dedications', methods=['POST'])
def create_dedication():
    """יצירת הקדשה חדשה (אדמין בלבד)"""
    data = request.json
    
    try:
        end_date = datetime.fromisoformat(data.get('end_date'))
    except:
        return jsonify({'ok': False, 'error': 'תאריך לא תקין'}), 400
    
    new_ded = Dedication(
        type=data.get('type'),
        content=data.get('content'),
        font=data.get('font', 'Heebo'),
        font_size=data.get('font_size', 16),
        bold=data.get('bold', False),
        italic=data.get('italic', False),
        underline=data.get('underline', False),
        color=data.get('color', '#000000'),
        align=data.get('align', 'right'),
        end_date=end_date
    )
    
    db.session.add(new_ded)
    db.session.commit()
    
    return jsonify({'ok': True, 'id': new_ded.id})

@app.route('/api/dedications/<int:ded_id>', methods=['DELETE'])
def delete_dedication(ded_id):
    """מחיקת הקדשה (אדמין בלבד)"""
    ded = Dedication.query.get(ded_id)
    if not ded:
        return jsonify({'ok': False, 'error': 'הקדשה לא נמצאה'}), 404
    
    db.session.delete(ded)
    db.session.commit()
    
    return jsonify({'ok': True})

if __name__ == '__main__':
    app.run(debug=True)
