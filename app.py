from flask import Flask, render_template, redirect, url_for, request, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from functools import wraps
import re
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'mentorship_secret_key_2024')
# Use /data/ persistent disk on Render, fall back to local for development
db_path = '/data/mentorship.db' if os.path.isdir('/data') else os.path.join(os.path.dirname(__file__), 'mentorship.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ─────────────────────────── MODELS ────────────────────────────

class User(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    role       = db.Column(db.String(20), nullable=False)   # student | mentor | admin
    bio        = db.Column(db.Text, default='')
    skills     = db.Column(db.String(300), default='')
    interests  = db.Column(db.String(300), default='')
    field      = db.Column(db.String(100), default='')
    city       = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active  = db.Column(db.Boolean, default=True)

class Match(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mentor_id  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status     = db.Column(db.String(20), default='pending')  # pending|accepted|rejected
    score      = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student    = db.relationship('User', foreign_keys=[student_id])
    mentor     = db.relationship('User', foreign_keys=[mentor_id])

class MentorSession(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    match_id   = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=False)
    title      = db.Column(db.String(200), nullable=False)
    date       = db.Column(db.String(50), nullable=False)
    time       = db.Column(db.String(50), nullable=False)
    notes      = db.Column(db.Text, default='')
    status     = db.Column(db.String(20), default='scheduled')  # scheduled|completed|cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    match      = db.relationship('Match', backref='sessions')

class Message(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    sender_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content     = db.Column(db.Text, nullable=False)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    is_read     = db.Column(db.Boolean, default=False)
    sender      = db.relationship('User', foreign_keys=[sender_id])
    receiver    = db.relationship('User', foreign_keys=[receiver_id])

class Feedback(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    session_id   = db.Column(db.Integer, db.ForeignKey('mentor_session.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating       = db.Column(db.Integer, nullable=False)
    comment      = db.Column(db.Text, default='')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    session      = db.relationship('MentorSession', backref='feedbacks')
    from_user    = db.relationship('User', foreign_keys=[from_user_id])
    to_user      = db.relationship('User', foreign_keys=[to_user_id])

class Progress(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    goal       = db.Column(db.String(300), nullable=False)
    status     = db.Column(db.String(20), default='in_progress')  # in_progress|completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    student    = db.relationship('User', foreign_keys=[student_id])

# ─────────────────────────── HELPERS ───────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login first.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def current_user():
    if 'user_id' in session:
        return db.session.get(User, session['user_id'])
    return None

STOP_WORDS = {
    'a','an','the','and','or','but','in','on','at','to','for','of','with',
    'by','from','is','are','was','were','be','been','have','has','had',
    'do','does','did','will','would','could','should','may','might','can',
    'i','me','my','we','our','you','your','he','him','his','she','her',
    'it','its','they','them','their','this','that','these','those',
    'not','no','very','just','also','all','any','some','more','most',
    'own','same','than','too','so','as','up','out','about','into',
    'over','after','then','here','there','when','where','such','each',
    'get','use','work','make','like','know','take','see','come','want',
    'new','good','great','help','need','way','time','year','well','even'
}

def tokenize(text):
    if not text:
        return set()
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return {w for w in words if w not in STOP_WORDS}

def tag_set(comma_str):
    return {t.strip().lower() for t in comma_str.split(',') if t.strip()}

def partial_overlap(set_a, set_b):
    count = 0
    for a in set_a:
        for b in set_b:
            if a != b and (a in b or b in a):
                count += 1
    return count

def mentor_has_profile(mentor):
    return bool(mentor.skills or mentor.bio or mentor.field or mentor.interests)

def student_has_profile(student):
    return bool(student.skills or student.interests or student.field or student.bio)

def compute_match_score(student, mentor):
    if not mentor_has_profile(mentor) and not student_has_profile(student):
        return 0
    score = 0
    s_interests = tag_set(student.interests)
    s_skills    = tag_set(student.skills)
    m_skills    = tag_set(mentor.skills)
    m_interests = tag_set(mentor.interests)
    # Student interests vs mentor skills (core match)
    score += min(len(s_interests & m_skills) * 25, 50)
    # Partial: 'python' inside 'python developer'
    score += min(partial_overlap(s_interests, m_skills) * 10, 20)
    # Shared skills
    score += min(len(s_skills & m_skills) * 8, 16)
    # Shared interests
    score += min(len(s_interests & m_interests) * 6, 12)
    # Field similarity
    if student.field and mentor.field:
        sf, mf = student.field.lower().strip(), mentor.field.lower().strip()
        if sf == mf:
            score += 30
        elif sf in mf or mf in sf:
            score += 15
        else:
            score += min(len(tokenize(sf) & tokenize(mf)) * 8, 16)
    # City
    if student.city and mentor.city:
        if student.city.lower().strip() == mentor.city.lower().strip():
            score += 10
    # Bio + all-text keyword overlap
    s_tokens = (tokenize(student.bio) | tokenize(student.interests)
                | tokenize(student.skills) | tokenize(student.field))
    m_tokens = (tokenize(mentor.bio) | tokenize(mentor.skills)
                | tokenize(mentor.interests) | tokenize(mentor.field))
    score += min(len(s_tokens & m_tokens) * 5, 20)
    # Skill overlap floor: if >= 50% of student's interests match mentor's skills → min score 50
    if s_interests:
        skill_overlap_ratio = len(s_interests & m_skills) / len(s_interests)
        if skill_overlap_ratio >= 0.5:
            score = max(score, 50)
    return min(round(score, 1), 100)

# ─────────────────────────── ROUTES ────────────────────────────

@app.route('/')
def index():
    user = current_user()
    total_mentors  = User.query.filter_by(role='mentor').count()
    total_students = User.query.filter_by(role='student').count()
    total_matches  = Match.query.filter_by(status='accepted').count()
    return render_template('index.html', user=user,
                           total_mentors=total_mentors,
                           total_students=total_students,
                           total_matches=total_matches)

# ── AUTH ──

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        role     = request.form['role']
        if not name or not email or not password or role not in ('student', 'mentor'):
            flash('All fields are required.', 'danger')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        user = User(name=name, email=email,
                    password=generate_password_hash(password), role=role)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']
        user     = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password) and user.is_active:
            session['user_id'] = user.id
            session['role']    = user.role
            session['name']    = user.name
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for(
                'admin_dashboard'   if user.role == 'admin'  else
                'mentor_dashboard'  if user.role == 'mentor' else
                'student_dashboard'
            ))
        flash('Invalid credentials or account deactivated.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ── STUDENT ──

@app.route('/student/dashboard')
@role_required('student')
def student_dashboard():
    user         = current_user()
    my_matches   = Match.query.filter_by(student_id=user.id).all()
    my_sessions  = []
    for m in my_matches:
        if m.status == 'accepted':
            my_sessions.extend(m.sessions)
    goals  = Progress.query.filter_by(student_id=user.id).all()
    unread = Message.query.filter_by(receiver_id=user.id, is_read=False).count()
    return render_template('dashboard_student.html', user=user,
                           matches=my_matches, sessions=my_sessions[:5],
                           goals=goals, unread=unread)

@app.route('/student/find-mentors')
@role_required('student')
def find_mentors():
    user = current_user()
    all_mentors = User.query.filter_by(role='mentor', is_active=True).all()
    # Only show mentors who filled at least one profile field
    mentors_with_profile = [m for m in all_mentors if mentor_has_profile(m)]
    already_req = {m.mentor_id for m in Match.query.filter_by(student_id=user.id).all()}
    mentor_scores = [
        (mentor, compute_match_score(user, mentor), mentor.id in already_req)
        for mentor in mentors_with_profile
    ]
    # Hide mentors with score below 50
    low_score_count = sum(1 for _, s, _ in mentor_scores if s < 50)
    mentor_scores = [(m, s, r) for m, s, r in mentor_scores if s >= 50]
    mentor_scores.sort(key=lambda x: (-x[1], x[0].name))
    return render_template('matches.html', user=user,
                           mentor_scores=mentor_scores,
                           profile_complete=student_has_profile(user),
                           hidden_count=len(all_mentors) - len(mentors_with_profile),
                           low_score_count=low_score_count)

@app.route('/student/request-match/<int:mentor_id>', methods=['POST'])
@role_required('student')
def request_match(mentor_id):
    user = current_user()
    if Match.query.filter_by(student_id=user.id, mentor_id=mentor_id).first():
        flash('Already requested this mentor.', 'warning')
        return redirect(url_for('find_mentors'))
    mentor = db.session.get(User, mentor_id)
    if not mentor:
        flash('Mentor not found.', 'danger')
        return redirect(url_for('find_mentors'))
    score = compute_match_score(user, mentor)
    db.session.add(Match(student_id=user.id, mentor_id=mentor_id, score=score))
    db.session.commit()
    flash(f'Match request sent to {mentor.name}!', 'success')
    return redirect(url_for('find_mentors'))

@app.route('/match/stop/<int:match_id>', methods=['POST'])
@role_required('student')
def stop_match(match_id):
    user  = current_user()
    match = db.session.get(Match, match_id)
    if not match or match.student_id != user.id or match.status != 'accepted':
        flash('Invalid action.', 'danger')
        return redirect(url_for('student_dashboard'))
    match.status = 'stopped'
    db.session.commit()
    flash(f'You have stopped working with {match.mentor.name}.', 'info')
    return redirect(url_for('student_dashboard'))

# ── MENTOR ──

@app.route('/mentor/dashboard')
@role_required('mentor')
def mentor_dashboard():
    user     = current_user()
    pending  = Match.query.filter_by(mentor_id=user.id, status='pending').all()
    accepted = Match.query.filter_by(mentor_id=user.id, status='accepted').all()
    stopped  = Match.query.filter_by(mentor_id=user.id, status='stopped').all()
    upcoming = []
    for m in accepted:
        upcoming.extend(s for s in m.sessions if s.status == 'scheduled')
    unread = Message.query.filter_by(receiver_id=user.id, is_read=False).count()
    return render_template('dashboard_mentor.html', user=user,
                           pending=pending, accepted=accepted,
                           stopped=stopped,
                           upcoming=upcoming[:5], unread=unread)

@app.route('/mentor/respond/<int:match_id>/<string:action>')
@role_required('mentor')
def respond_match(match_id, action):
    match = db.session.get(Match, match_id)
    user  = current_user()
    if not match or match.mentor_id != user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('mentor_dashboard'))
    if action == 'accept':
        match.status = 'accepted'
        flash(f'You accepted {match.student.name}!', 'success')
    elif action == 'reject':
        match.status = 'rejected'
        flash(f'You declined {match.student.name}.', 'info')
    db.session.commit()
    return redirect(url_for('mentor_dashboard'))

# ── SESSIONS ──

@app.route('/sessions')
@login_required
def sessions_list():
    user = current_user()
    if user.role == 'student':
        matches = Match.query.filter_by(student_id=user.id, status='accepted').all()
    else:
        matches = Match.query.filter_by(mentor_id=user.id, status='accepted').all()
    session_pairs = []
    for m in matches:
        for s in m.sessions:
            session_pairs.append((s, m))
    session_pairs.sort(key=lambda x: x[0].created_at, reverse=True)
    return render_template('sessions.html', user=user, session_pairs=session_pairs)

@app.route('/sessions/schedule/<int:match_id>', methods=['GET', 'POST'])
@login_required
def schedule_session(match_id):
    match = db.session.get(Match, match_id)
    user  = current_user()
    if request.method == 'POST':
        title = request.form['title'].strip()
        date  = request.form['date']
        time  = request.form['time']
        notes = request.form.get('notes', '')
        if not title or not date or not time:
            flash('Title, date and time are required.', 'danger')
            return redirect(request.url)
        db.session.add(MentorSession(match_id=match_id, title=title,
                                     date=date, time=time, notes=notes))
        db.session.commit()
        flash('Session scheduled!', 'success')
        return redirect(url_for('sessions_list'))
    return render_template('schedule_session.html', user=user, match=match)

@app.route('/sessions/complete/<int:session_id>')
@login_required
def complete_session(session_id):
    s = db.session.get(MentorSession, session_id)
    if s:
        s.status = 'completed'
        db.session.commit()
        flash('Session marked as completed.', 'success')
    return redirect(url_for('sessions_list'))

# ── MESSAGES ──

@app.route('/messages')
@login_required
def messages():
    user = current_user()
    sent_ids     = [r[0] for r in db.session.query(Message.receiver_id).filter_by(sender_id=user.id).distinct()]
    received_ids = [r[0] for r in db.session.query(Message.sender_id).filter_by(receiver_id=user.id).distinct()]
    contact_ids  = set(sent_ids + received_ids)
    contacts     = User.query.filter(User.id.in_(contact_ids)).all() if contact_ids else []
    return render_template('messages.html', user=user, contacts=contacts, selected=None, chat=[])

@app.route('/messages/<int:other_id>', methods=['GET', 'POST'])
@login_required
def chat(other_id):
    user  = current_user()
    other = db.session.get(User, other_id)
    if not other:
        flash('User not found.', 'danger')
        return redirect(url_for('messages'))
    if request.method == 'POST':
        content = request.form['content'].strip()
        if content:
            db.session.add(Message(sender_id=user.id, receiver_id=other_id, content=content))
            db.session.commit()
        return redirect(url_for('chat', other_id=other_id))
    Message.query.filter_by(sender_id=other_id, receiver_id=user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    chat_msgs = Message.query.filter(
        ((Message.sender_id == user.id) & (Message.receiver_id == other_id)) |
        ((Message.sender_id == other_id) & (Message.receiver_id == user.id))
    ).order_by(Message.created_at).all()
    sent_ids     = [r[0] for r in db.session.query(Message.receiver_id).filter_by(sender_id=user.id).distinct()]
    received_ids = [r[0] for r in db.session.query(Message.sender_id).filter_by(receiver_id=user.id).distinct()]
    contact_ids  = set(sent_ids + received_ids)
    contacts     = User.query.filter(User.id.in_(contact_ids)).all() if contact_ids else []
    return render_template('messages.html', user=user, contacts=contacts,
                           selected=other, chat=chat_msgs)

# ── PROFILE ──

@app.route('/profile')
@login_required
def profile():
    user     = current_user()
    feedbacks = Feedback.query.filter_by(to_user_id=user.id).all()
    avg_rating = round(sum(f.rating for f in feedbacks) / len(feedbacks), 1) if feedbacks else 0
    return render_template('profile.html', user=user, feedbacks=feedbacks, avg_rating=avg_rating)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user = current_user()
    if request.method == 'POST':
        user.name      = request.form['name'].strip()
        user.bio       = request.form.get('bio', '').strip()
        user.skills    = request.form.get('skills', '').strip()
        user.interests = request.form.get('interests', '').strip()
        user.field     = request.form.get('field', '').strip()
        user.city      = request.form.get('city', '').strip()
        db.session.commit()
        session['name'] = user.name
        flash('Profile updated!', 'success')
        return redirect(url_for('profile'))
    return render_template('edit_profile.html', user=user)

# ── FEEDBACK ──

@app.route('/feedback/<int:session_id>', methods=['GET', 'POST'])
@login_required
def give_feedback(session_id):
    user  = current_user()
    sess  = db.session.get(MentorSession, session_id)
    if not sess:
        flash('Session not found.', 'danger')
        return redirect(url_for('sessions_list'))
    match = sess.match
    to_id = match.mentor_id if user.id == match.student_id else match.student_id
    if Feedback.query.filter_by(session_id=session_id, from_user_id=user.id).first():
        flash('You already gave feedback for this session.', 'warning')
        return redirect(url_for('sessions_list'))
    if request.method == 'POST':
        rating  = int(request.form['rating'])
        comment = request.form.get('comment', '').strip()
        db.session.add(Feedback(session_id=session_id, from_user_id=user.id,
                                to_user_id=to_id, rating=rating, comment=comment))
        db.session.commit()
        flash('Feedback submitted!', 'success')
        return redirect(url_for('sessions_list'))
    to_user = db.session.get(User, to_id)
    return render_template('feedback.html', user=user, sess=sess, to_user=to_user)

# ── PROGRESS ──

@app.route('/progress')
@role_required('student')
def progress():
    user = current_user()
    goals = Progress.query.filter_by(student_id=user.id).all()
    completed_sessions = sum(
        MentorSession.query.filter_by(match_id=m.id, status='completed').count()
        for m in Match.query.filter_by(student_id=user.id, status='accepted').all()
    )
    total_mentors = Match.query.filter_by(student_id=user.id, status='accepted').count()
    return render_template('progress.html', user=user, goals=goals,
                           completed_sessions=completed_sessions,
                           total_mentors=total_mentors)

@app.route('/progress/add', methods=['POST'])
@role_required('student')
def add_goal():
    user      = current_user()
    goal_text = request.form['goal'].strip()
    if goal_text:
        db.session.add(Progress(student_id=user.id, goal=goal_text))
        db.session.commit()
        flash('Goal added!', 'success')
    return redirect(url_for('progress'))

@app.route('/progress/complete/<int:goal_id>')
@role_required('student')
def complete_goal(goal_id):
    goal = db.session.get(Progress, goal_id)
    if goal and goal.student_id == session['user_id']:
        goal.status = 'completed'
        db.session.commit()
        flash('Goal completed!', 'success')
    return redirect(url_for('progress'))

@app.route('/progress/delete/<int:goal_id>', methods=['POST'])
@role_required('student')
def delete_goal(goal_id):
    goal = db.session.get(Progress, goal_id)
    if goal and goal.student_id == session['user_id']:
        db.session.delete(goal)
        db.session.commit()
        flash('Goal deleted.', 'info')
    return redirect(url_for('progress'))

# ── ADMIN ──

@app.route('/admin/dashboard')
@role_required('admin')
def admin_dashboard():
    return render_template('dashboard_admin.html',
                           user=current_user(),
                           total_students=User.query.filter_by(role='student').count(),
                           total_mentors=User.query.filter_by(role='mentor').count(),
                           total_matches=Match.query.count(),
                           total_sessions=MentorSession.query.count(),
                           recent_users=User.query.order_by(User.created_at.desc()).limit(10).all())

@app.route('/admin/users')
@role_required('admin')
def admin_users():
    role_filter = request.args.get('role', '')
    users = (User.query.filter_by(role=role_filter) if role_filter else User.query)\
            .order_by(User.created_at.desc()).all()
    return render_template('admin_users.html', user=current_user(),
                           users=users, role_filter=role_filter)

@app.route('/admin/toggle-user/<int:user_id>')
@role_required('admin')
def toggle_user(user_id):
    u = db.session.get(User, user_id)
    if u:
        u.is_active = not u.is_active
        db.session.commit()
        flash(f'{u.name} has been {"activated" if u.is_active else "deactivated"}.', 'info')
    return redirect(url_for('admin_users'))

@app.route('/admin/matches')
@role_required('admin')
def admin_matches():
    matches = Match.query.order_by(Match.created_at.desc()).all()
    return render_template('admin_matches.html', user=current_user(), matches=matches)

@app.route('/admin/view-user/<int:user_id>')
@role_required('admin')
def admin_view_user(user_id):
    u         = db.session.get(User, user_id)
    feedbacks = Feedback.query.filter_by(to_user_id=user_id).all()
    avg       = round(sum(f.rating for f in feedbacks) / len(feedbacks), 1) if feedbacks else 0
    matches   = (Match.query.filter_by(student_id=user_id) if u.role == 'student'
                 else Match.query.filter_by(mentor_id=user_id)).all()
    goals     = Progress.query.filter_by(student_id=user_id).all() if u.role == 'student' else []
    return render_template('admin_view_user.html', user=current_user(),
                           viewed=u, feedbacks=feedbacks, avg=avg,
                           matches=matches, goals=goals)

# ─────────────────────────── INIT ──────────────────────────────

def seed_admin():
    if not User.query.filter_by(role='admin').first():
        db.session.add(User(name='Admin',
                            email='admin@mentorship.com',
                            password=generate_password_hash('admin123'),
                            role='admin'))
        db.session.commit()
        print('Admin created: admin@mentorship.com / admin123')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_admin()
    app.run(debug=True)
