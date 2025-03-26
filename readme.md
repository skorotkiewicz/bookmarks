```sh
python3 -m venv venv
source venv/bin/activate
```

```sh
pip install -r requirements.txt
pip install --upgrade flask-sqlalchemy sqlalchemy

pip install waitress
```

```sh
# run in dev mode
python app.py dev

# run in prod mode
python app.py

deactivate
```

i18n  
to add new translation: add in lang/xx.json then in app.py add:  
app.config['LANGUAGES'] = ['en', 'pl', "de", "xx"]
