import os
import sys
import requests
from bs4 import BeautifulSoup
from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from datetime import timedelta, datetime
import urllib.parse
import hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bookmarks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit rozmiaru pliku do 16 MB
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=90)
app.config['FAVICON_FOLDER'] = os.path.join(app.static_folder, 'cache', 'favicons')

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
        
        # Sprawdzenie, czy użytkownik już istnieje
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Nazwa użytkownika jest już zajęta', 'error')
            return redirect(url_for('register'))
        
        # Hashowanie hasła
        hashed_password = generate_password_hash(password)
        
        # Utworzenie nowego użytkownika
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Rejestracja zakończona sukcesem', 'success')
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
            flash('Logowanie zakończone sukcesem', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Nieprawidłowe dane logowania', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Zostałeś wylogowany', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Musisz być zalogowany', 'error')
        return redirect(url_for('login'))
    
    user = User.query.get(session['user_id'])
    bookmarks = Bookmark.query.filter_by(user_id=user.id).order_by(Bookmark.created_at.desc()).all()
    return render_template('dashboard.html', user=user, bookmarks=bookmarks)

@app.route('/add_bookmark', methods=['GET', 'POST'])
def add_bookmark():
    if 'user_id' not in session:
        flash('Musisz być zalogowany', 'error')
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
        
        flash('Zakładka dodana pomyślnie', 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('add_bookmark.html')

@app.route('/delete_bookmark/<int:bookmark_id>', methods=['POST'])
def delete_bookmark(bookmark_id):
    if 'user_id' not in session:
        flash('Musisz być zalogowany', 'error')
        return redirect(url_for('login'))
    
    bookmark = Bookmark.query.get_or_404(bookmark_id)
    
    if bookmark.user_id != session['user_id']:
        flash('Nie masz uprawnień', 'error')
        return redirect(url_for('dashboard'))
    
    db.session.delete(bookmark)
    db.session.commit()
    
    flash('Zakładka usunięta', 'success')
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
    """Pobiera i zapisuje favicon strony"""
    try:
        # Generowanie unikalnej nazwy pliku dla faviconu
        url_hash = hashlib.md5(url.encode()).hexdigest()
        favicon_filename = f"{url_hash}_{bookmark_id}.png"
        favicon_path = os.path.join(app.config['FAVICON_FOLDER'], favicon_filename)
        
        # Jeśli favicon już istnieje, zwróć jego nazwę
        if os.path.exists(favicon_path):
            return favicon_filename
        
        # Próba pobrania favicon z meta tagów
        try:
            response = requests.get(url, timeout=5)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Szukanie favicon w różnych meta tagach
            favicon_url = None
            for link in soup.find_all('link'):
                rel = link.get('rel', [])
                if isinstance(rel, list) and any(r in ['icon', 'shortcut icon'] for r in rel):
                    favicon_url = link.get('href')
                    break
            
            if not favicon_url:
                # Jeśli nie znaleziono w meta, próba domyślnej ścieżki
                parsed_url = urllib.parse.urlparse(url)
                favicon_url = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"
            
            # Upewnienie się, że URL jest absolutny
            if favicon_url.startswith('/'):
                parsed_url = urllib.parse.urlparse(url)
                favicon_url = f"{parsed_url.scheme}://{parsed_url.netloc}{favicon_url}"
            
            # Pobieranie favicon
            favicon_response = requests.get(favicon_url, timeout=5)
            if favicon_response.status_code == 200:
                # Zapisanie favicon
                with open(favicon_path, 'wb') as f:
                    f.write(favicon_response.content)
                return favicon_filename
        except Exception as e:
            print(f"Błąd pobierania favicon: {e}")
        
        return None
    except Exception as e:
        print(f"Błąd ogólny favicon: {e}")
        return None

@app.route('/import_bookmarks', methods=['GET', 'POST'])
def import_bookmarks():
    if 'user_id' not in session:
        flash('Musisz być zalogowany', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Obsługa importu zakładek z pliku HTML Firefox
        if 'bookmarks_file' not in request.files:
            flash('Nie wybrano pliku', 'error')
            return redirect(request.url)
        
        file = request.files['bookmarks_file']
        
        if file.filename == '':
            flash('Nie wybrano pliku', 'error')
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
                        description='Zaimportowana zakładka',
                        user_id=session['user_id'],
                        created_at=datetime.fromtimestamp(int(added)) if added else datetime.utcnow() 
                    )
                    
                    db.session.add(new_bookmark)
                    imported_count += 1
                except Exception as e:
                    # Logowanie błędów bez przerywania importu
                    print(f"Błąd importu zakładki: {e}")
            
            db.session.commit()
            
            flash(f'Zaimportowano {imported_count} zakładek', 'success')
            return redirect(url_for('dashboard'))
    
    return render_template('import_bookmarks.html')

@app.route('/get_page_title', methods=['POST'])
def fetch_page_title():
    """Endpoint do automatycznego pobierania tytułu strony"""
    if 'user_id' not in session:
        return {'error': 'Nie jesteś zalogowany'}, 403
    
    url = request.form.get('url')
    if not url:
        return {'error': 'Nie podano URL'}, 400
    
    try:
        title = get_page_title(url)
        return {'title': title}
    except Exception as e:
        return {'error': str(e)}, 500

@app.route('/open/<int:bookmark_id>')
def open_bookmark(bookmark_id):
    """Przekierowanie na stronę i pobranie favicon"""
    if 'user_id' not in session:
        flash('Musisz być zalogowany', 'error')
        return redirect(url_for('login'))
    
    bookmark = Bookmark.query.get_or_404(bookmark_id)
    
    # Sprawdzenie czy zakładka należy do zalogowanego użytkownika
    if bookmark.user_id != session['user_id']:
        flash('Nie masz uprawnień', 'error')
        return redirect(url_for('dashboard'))
    
    # Pobieranie favicon, jeśli jeszcze nie istnieje
    if not bookmark.favicon_path:
        favicon_filename = fetch_and_save_favicon(bookmark.url, bookmark.id)
        if favicon_filename:
            bookmark.favicon_path = favicon_filename
            db.session.commit()
    
    # Przekierowanie na stronę
    return redirect(bookmark.url)

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