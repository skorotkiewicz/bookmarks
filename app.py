import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import timedelta, datetime
import urllib.parse
import hashlib
from functools import wraps
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bookmarks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Maximum file size 16 MB
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=90)
app.config['FAVICON_FOLDER'] = os.path.join(app.static_folder, 'cache', 'favicons')
app.config['LANGUAGES'] = ['en', 'pl', "de"]
app.config['DEFAULT_LANGUAGE'] = 'en'

# Load language files
def load_language(lang_code):
    try:
        with open(os.path.join('lang', f'{lang_code}.json'), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback to default language if requested language file is not found
        if lang_code != app.config['DEFAULT_LANGUAGE']:
            return load_language(app.config['DEFAULT_LANGUAGE'])
        return {}

# Add a function to get text based on translation key
def get_text(key, default=None, **kwargs):
    lang = session.get('lang', app.config['DEFAULT_LANGUAGE'])
    translations = load_language(lang)
    
    # Split dot notation key into parts (e.g., "login.title" -> ["login", "title"])
    parts = key.split('.')
    value = translations
    
    # Traverse the nested dictionaries
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return default or key
    
    # Format string with provided kwargs if any
    if isinstance(value, str) and kwargs:
        try:
            return value.format(**kwargs)
        except KeyError:
            return value
    
    return value

# Set up language before each request
@app.before_request
def before_request():
    g.get_text = get_text
    
    # Set language from query parameter or from session
    if request.args.get('lang') and request.args.get('lang') in app.config['LANGUAGES']:
        session['lang'] = request.args.get('lang')
    elif 'lang' not in session:
        session['lang'] = app.config['DEFAULT_LANGUAGE']
    
    g.languages = app.config['LANGUAGES']
    g.current_lang = session.get('lang', app.config['DEFAULT_LANGUAGE'])

# Add translate function to templates
@app.context_processor
def inject_template_scope():
    return dict(t=get_text)

# Route to change language
@app.route('/change_language/<lang>')
def change_language(lang):
    if lang in app.config['LANGUAGES']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    bookmarks = db.relationship('Bookmark', backref='user', lazy=True, order_by='Bookmark.created_at.desc()')
    # bookmarks = db.relationship('Bookmark', backref='user', lazy=True, order_by='Bookmark.id.desc()')

class Bookmark(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    favicon_path = db.Column(db.String(255))
    
    def get_favicon_url(self):
        if self.favicon_path and os.path.exists(os.path.join(app.config['FAVICON_FOLDER'], self.favicon_path)):
            return url_for('static', filename=f'cache/favicons/{self.favicon_path}')
        return url_for('static', filename='blank.png')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        # Check if user already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash(get_text('register.username_taken'), 'error')
            return redirect(url_for('register'))
        
        # Hash password
        hashed_password = generate_password_hash(password)
        
        # Create new user
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash(get_text('register.success'), 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session.permanent = bool(remember)
            session['user_id'] = user.id
            flash(get_text('login.success'), 'success')
            return redirect(url_for('dashboard'))
        else:
            flash(get_text('login.invalid'), 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash(get_text('navigation.logout'), 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    bookmarks = Bookmark.query.filter_by(user_id=user.id).order_by(Bookmark.created_at.desc()).all()
    return render_template('dashboard.html', user=user, bookmarks=bookmarks)

@app.route('/add_bookmark', methods=['GET', 'POST'])
def add_bookmark():
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form['title']
        url = request.form['url']
        description = request.form['description']
        
        new_bookmark = Bookmark(
            title=title, 
            url=url, 
            description=description, 
            user_id=session['user_id'],
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_bookmark)
        db.session.commit()
        
        # Fetch favicon immediately after adding
        favicon_filename = fetch_and_save_favicon(url, new_bookmark.id)
        if favicon_filename:
            new_bookmark.favicon_path = favicon_filename
            db.session.commit()
        
        flash(get_text('add_bookmark.success'), 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('add_bookmark.html')

@app.route('/delete_bookmark/<int:bookmark_id>', methods=['POST'])
def delete_bookmark(bookmark_id):
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    bookmark = Bookmark.query.get_or_404(bookmark_id)
    
    if bookmark.user_id != session['user_id']:
        flash(get_text('errors.no_permission'), 'error')
        return redirect(url_for('dashboard'))
    
    # Delete favicon file if it exists
    if bookmark.favicon_path:
        favicon_path = os.path.join(app.config['FAVICON_FOLDER'], bookmark.favicon_path)
        if os.path.exists(favicon_path):
            try:
                os.remove(favicon_path)
            except Exception as e:
                print(f"Error removing favicon: {e}")
    
    db.session.delete(bookmark)
    db.session.commit()
    
    # If it's an AJAX request, return JSON instead of redirection
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return {'success': True, 'message': get_text('bookmarks.delete_success')}
    
    # For traditional request - redirect
    flash(get_text('bookmarks.delete_success'), 'success')
    return redirect(url_for('dashboard'))

def get_page_title(url):
    """Pobierz tytuł strony z podanego URL"""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup.title.string if soup.title else url
    except Exception:
        return url

def fetch_and_save_favicon(url, bookmark_id):
    """Pobiera i zapisuje favicon strony używając Google Favicon API"""
    try:
        # Generowanie unikalnej nazwy pliku dla faviconu
        url_hash = hashlib.md5(url.encode()).hexdigest()
        favicon_filename = f"{url_hash}_{bookmark_id}.png"
        favicon_path = os.path.join(app.config['FAVICON_FOLDER'], favicon_filename)
        
        # Jeśli favicon już istnieje, zwróć jego nazwę
        if os.path.exists(favicon_path):
            return favicon_filename
        
        # Pobieranie domeny ze strony
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        
        # Użycie Google Favicon API
        favicon_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=32"
        
        # Pobieranie favicon
        favicon_response = requests.get(favicon_url, timeout=5)
        if favicon_response.status_code == 200:
            # Zapisz plik
            with open(favicon_path, 'wb') as f:
                f.write(favicon_response.content)
            return favicon_filename
        
        return None
    except Exception as e:
        print(f"Error favicon: {e}")
        return None

@app.route('/import_bookmarks', methods=['GET', 'POST'])
def import_bookmarks():
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Handle import from Firefox HTML file
        if 'bookmarks_file' not in request.files:
            flash(get_text('import_bookmarks.no_file'), 'error')
            return redirect(request.url)
        
        file = request.files['bookmarks_file']
        
        if file.filename == '':
            flash(get_text('import_bookmarks.no_file'), 'error')
            return redirect(request.url)
        
        if file:
            # Parsowanie pliku zakładek
            soup = BeautifulSoup(file.read(), 'html.parser')
            
            # Znajdź wszystkie linki
            links = soup.find_all('a')
            
            imported_count = 0
            for link in links:
                try:
                    url = link.get('href')
                    added = link.get('add_date')
                    title = link.string or get_page_title(url)
                    
                    # Pomijaj puste lub niepoprawne linki
                    if not url or not url.startswith(('http://', 'https://')):
                        continue
                    
                    # Dodaj zakładkę
                    new_bookmark = Bookmark(
                        title=title, 
                        url=url, 
                        description=get_text('bookmarks.imported_description'),
                        user_id=session['user_id'],
                        created_at=datetime.fromtimestamp(int(added)) if added else datetime.utcnow() 
                    )
                    
                    db.session.add(new_bookmark)
                    imported_count += 1
                except Exception as e:
                    # Logowanie błędów bez przerywania importu
                    print(f"Error import bookmark: {e}")
            
            db.session.commit()
            
            flash(get_text('import_bookmarks.bookmark_count', count=imported_count), 'success')
            return redirect(url_for('dashboard'))
    
    return render_template('import_bookmarks.html')

@app.route('/export_bookmarks')
def export_bookmarks():
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    user = db.session.get(User, session['user_id'])
    bookmarks = Bookmark.query.filter_by(user_id=user.id).all()
    
    # Create Firefox bookmarks HTML file structure
    html = f'''<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="{int(time.time())}" LAST_MODIFIED="{int(time.time())}">Exported from {get_text('app_name')}</H3>
    <DL><p>
'''
    
    # Add each bookmark
    for bookmark in bookmarks:
        # Convert datetime to unix timestamp for ADD_DATE
        add_date = int(bookmark.created_at.timestamp()) if bookmark.created_at else int(time.time())
        html += f'        <DT><A HREF="{bookmark.url}" ADD_DATE="{add_date}">{bookmark.title}</A>\n'
    
    # Close HTML structure
    html += '''    </DL><p>
</DL><p>
'''
    
    # Create response with HTML content
    response = make_response(html)
    response.headers['Content-Type'] = 'text/html'
    response.headers['Content-Disposition'] = 'attachment; filename=bookmarks.html'
    
    return response

@app.route('/get_page_title', methods=['POST'])
def fetch_page_title():
    """Endpoint for automatically fetching page title"""
    if 'user_id' not in session:
        return {'error': get_text('errors.not_logged_in')}, 403
    
    url = request.form.get('url')
    if not url:
        return {'error': get_text('errors.no_url')}, 400
    
    try:
        title = get_page_title(url)
        return {'title': title}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/open/<int:bookmark_id>')
def open_bookmark(bookmark_id):
    """Redirect to page and fetch favicon"""
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    bookmark = Bookmark.query.get_or_404(bookmark_id)
    
    # Check if bookmark belongs to logged in user
    if bookmark.user_id != session['user_id']:
        flash(get_text('errors.no_permission'), 'error')
        return redirect(url_for('dashboard'))
    
    # Pobieranie favicon, jeśli jeszcze nie istnieje
    if not bookmark.favicon_path:
        favicon_filename = fetch_and_save_favicon(bookmark.url, bookmark.id)
        if favicon_filename:
            bookmark.favicon_path = favicon_filename
            db.session.commit()
    
    # Przekierowanie na stronę
    return redirect(bookmark.url)

@app.route('/tools')
def tools():
    """Tools page for bookmark management"""
    if 'user_id' not in session:
        flash(get_text('errors.must_login'), 'error')
        return redirect(url_for('login'))
    
    return render_template('tools.html')

@app.route('/find_duplicates')
def find_duplicates():
    """Find duplicate bookmarks by URL"""
    if 'user_id' not in session:
        return {'error': get_text('errors.not_logged_in')}, 403
    
    # Get user's bookmarks
    bookmarks = Bookmark.query.filter_by(user_id=session['user_id']).all()
    
    # Group bookmarks by URL
    url_groups = {}
    for bookmark in bookmarks:
        normalized_url = bookmark.url.strip().lower()
        if normalized_url not in url_groups:
            url_groups[normalized_url] = []
        url_groups[normalized_url].append(bookmark)
    
    # Find groups with duplicates (more than 1 bookmark with same URL)
    duplicate_groups = []
    for url, group in url_groups.items():
        if len(group) > 1:
            # Convert bookmark objects to dictionaries for JSON serialization
            bookmarks_data = []
            for bookmark in group:
                bookmarks_data.append({
                    'id': bookmark.id,
                    'title': bookmark.title,
                    'url': bookmark.url,
                    'created_at': bookmark.created_at.isoformat() if bookmark.created_at else None,
                    'favicon_url': bookmark.get_favicon_url()
                })
            duplicate_groups.append(bookmarks_data)
    
    return {'duplicates': duplicate_groups}

@app.route('/remove_duplicates', methods=['POST'])
def remove_duplicates():
    """Remove duplicate bookmarks, keeping selected ones"""
    if 'user_id' not in session:
        return {'error': get_text('errors.not_logged_in')}, 403
    
    # Get IDs of bookmarks to keep
    data = request.get_json()
    keep_ids = data.get('keep_ids', [])
    
    if not keep_ids:
        return {'error': get_text('tools.no_bookmarks_selected')}, 400
    
    # Get all user's bookmarks
    bookmarks = Bookmark.query.filter_by(user_id=session['user_id']).all()
    
    # Group bookmarks by URL
    url_groups = {}
    for bookmark in bookmarks:
        normalized_url = bookmark.url.strip().lower()
        if normalized_url not in url_groups:
            url_groups[normalized_url] = []
        url_groups[normalized_url].append(bookmark)
    
    # Count bookmarks to delete
    bookmarks_to_delete = []
    
    # For each URL group with duplicates
    for url, group in url_groups.items():
        if len(group) > 1:
            # Find bookmarks in this group that should be deleted (not in keep_ids)
            for bookmark in group:
                if bookmark.id not in keep_ids:
                    bookmarks_to_delete.append(bookmark)
    
    # Delete the bookmarks
    delete_count = 0
    for bookmark in bookmarks_to_delete:
        # Delete favicon file if it exists
        if bookmark.favicon_path:
            favicon_path = os.path.join(app.config['FAVICON_FOLDER'], bookmark.favicon_path)
            if os.path.exists(favicon_path):
                try:
                    os.remove(favicon_path)
                except Exception as e:
                    print(f"Error removing favicon: {e}")
        
        db.session.delete(bookmark)
        delete_count += 1
    
    db.session.commit()
    
    return {'success': True, 'deleted_count': delete_count}

@app.route('/fetch_all_favicons')
def fetch_all_favicons():
    """Fetch favicons for all bookmarks that don't have one yet"""
    if 'user_id' not in session:
        return {'error': get_text('errors.not_logged_in')}, 403
    
    # Get all user's bookmarks that don't have a favicon
    bookmarks = Bookmark.query.filter_by(user_id=session['user_id']).filter(
        (Bookmark.favicon_path.is_(None)) | 
        (Bookmark.favicon_path == '')
    ).all()
    
    if not bookmarks:
        return {'success': False, 'message': get_text('tools.no_favicons_to_fetch')}
    
    fetched_count = 0
    for bookmark in bookmarks:
        favicon_filename = fetch_and_save_favicon(bookmark.url, bookmark.id)
        if favicon_filename:
            bookmark.favicon_path = favicon_filename
            # Zapisz zmiany od razu po pobraniu każdego favicon
            db.session.commit()
            fetched_count += 1
    
    return {
        'success': True, 
        'message': get_text('tools.favicons_fetched_success'), 
        'count': fetched_count
    }

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == 'dev':
        # dev
        with app.app_context():
            db.create_all()
            app.run(debug=True)
    else:
        # prod
        from waitress import serve
        with app.app_context():
            db.create_all()
        serve(app, host="0.0.0.0", port=5000)