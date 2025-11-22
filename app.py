# --- Imports ---
from flask import Flask, request, jsonify
import sqlite3
import datetime
import threading
import time
import sys

# --- Flask & DB Setup (example only) ---
app = Flask(__name__)

# --- CORS: Manual Header if flask_cors not installed ---
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    return response

DB_PATH = 'pilllog.db'

def db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

# --- Set up tables automatically ---
def init_db():
    conn = db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS medications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        frequencyPerDay INTEGER,
        pills_left INTEGER DEFAULT 30,
        pills_per_dose INTEGER DEFAULT 1,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS pill_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            med_id INTEGER,
            taken_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(med_id) REFERENCES medications(id)
        )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS alarms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        time TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
''')

    conn.commit()
    conn.close()

init_db()

# --- Platform Detection & GPIO Setup ---
PI_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    PI_AVAILABLE = True
except ImportError:
    print("RPi.GPIO not available. Button press will be simulated.")

BUTTON_PIN = 17  # Set your pin number here

if PI_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# --- Helper/Logic Functions ---

def get_due_medication():
    now = datetime.datetime.now()
    now_str = now.strftime('%H:%M')
    conn = db_connection()
    cur = conn.cursor()
    # Find the user's medication scheduled for now
    med = cur.execute(
        '''SELECT m.id, m.name, m.user_id
           FROM medications m
           JOIN alarms a ON m.user_id = a.user_id
           WHERE a.time = ?
           LIMIT 1
        ''', (now_str,)
    ).fetchone()
    conn.close()
    return med


def log_pill_backend():
    med = get_due_medication()
    if not med:
        print("No due medication scheduled for this time.")
        return
    med_id = med['id']
    user_id = med['user_id']
    med_name = med['name']
    conn = db_connection()
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat()
    # Get quantity to decrement
    pills_per_dose = cur.execute('SELECT pills_per_dose FROM medications WHERE id=?', (med_id,)).fetchone()['pills_per_dose']
    # Log pill
    cur.execute(
        'INSERT INTO pill_logs (user_id, med_id, taken_at) VALUES (?, ?, ?)', 
        (user_id, med_id, now)
    )
    # DECREMENT by actual pills_per_dose!
    cur.execute('UPDATE medications SET pills_left = pills_left - ? WHERE id=?', (pills_per_dose, med_id))
    conn.commit()
    conn.close()
    print(f"Pill for {med_name} logged and count decremented by {pills_per_dose} at {now}")

def button_listener():
    print("Pill button listener running...")
    while True:
        if PI_AVAILABLE:
            if GPIO.input(BUTTON_PIN) == GPIO.LOW:
                print("Button pressed! Logging pill...")
                log_pill_backend()
                time.sleep(1)  # Debounce: wait a second to avoid multiple triggers
        else:
            input("Simulate button press: press ENTER to log pill (Ctrl+C to exit)...")
            print("Simulated button pressed. Logging pill...")
            log_pill_backend()
        time.sleep(0.1)

def alarm_checker():
    while True:
        now = datetime.datetime.now().strftime('%H:%M')
        conn = db_connection()
        cur = conn.cursor()
        # Check for all alarms matching the current time
        alarms = cur.execute('SELECT id, time FROM alarms WHERE time=?', (now,)).fetchall()
        if alarms:
            for alarm_row in alarms:
                print(f"ALARM! It's now {now}. (Simulated trigger for alarm ID {alarm_row['id']})")
                # You can add any Pi-specific/LED/buzzer code here
        conn.close()
        time.sleep(60)  # Check every 60 seconds

# --- Flask Routes and App Startup ---

# --- Users endpoints ---
@app.route('/users', methods=['POST', 'GET'])
def users():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
        #printing for testing:
        print(f"Adding user: {name}")
        cur.execute('INSERT OR IGNORE INTO users (name) VALUES (?)', (name,))
        conn.commit()
        user = cur.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        conn.close()
        return jsonify({'id': user['id'], 'name': user['name']})
    else:
        users = cur.execute('SELECT id, name FROM users').fetchall()
        conn.close()
        return jsonify([dict(u) for u in users])

# --- Medications endpoints ---
@app.route('/medications', methods=['POST', 'GET'])
def medications():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        userName = request.json.get('userName')
        med_name = request.json.get('name')
        freq = request.json.get('frequencyPerDay')
        pills_left = request.json.get('pills_left', 30)
        pills_per_dose = request.json.get('pills_per_dose', 1)  # <-- Get value from frontend
        user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        user_id = user['id']
        cur.execute(
            'INSERT INTO medications (user_id, name, frequencyPerDay, pills_left, pills_per_dose) VALUES (?, ?, ?, ?, ?)',
            (user_id, med_name, freq, pills_left, pills_per_dose)  # <-- Pass it here
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'Medication added'})
    else:
        userName = request.args.get('userName')
        if not userName:
            conn.close()
            return jsonify([])
        user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
        if not user:
            conn.close()
            return jsonify([])
        meds = cur.execute(
            'SELECT name, frequencyPerDay, pills_left, pills_per_dose FROM medications WHERE user_id=?',
            (user['id'],)
        ).fetchall()
        conn.close()
        return jsonify([dict(m) for m in meds])

# --- Pill logs by user ---
@app.route('/pill_logs', methods=['GET'])
def pill_logs():
    userName = request.args.get('userName')
    conn = db_connection()
    cur = conn.cursor()
    user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
    if not user:
        conn.close()
        return jsonify([])
    logs = cur.execute(
        '''SELECT pl.taken_at, m.name 
           FROM pill_logs pl 
           JOIN medications m ON pl.med_id = m.id 
           WHERE pl.user_id=? 
           ORDER BY pl.taken_at DESC''',
        (user['id'],)
    ).fetchall()
    conn.close()
    return jsonify([dict(row) for row in logs])

# --- Alarms endpoints ---
@app.route('/alarms', methods=['POST', 'GET'])
def alarms():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        userName = request.json.get('userName')
        time_val = request.json.get('time')
        user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        cur.execute('INSERT INTO alarms (user_id, time) VALUES (?, ?)', (user['id'], time_val))
        conn.commit()
        conn.close()
        return jsonify({'status': 'Alarm added'}), 201
    else:
        alarms = cur.execute('SELECT id, user_id, time FROM alarms').fetchall()
        conn.close()
        return jsonify([dict(a) for a in alarms])

@app.route('/alarms/<int:alarm_id>', methods=['DELETE'])
def delete_alarm(alarm_id):
    conn = db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM alarms WHERE id=?', (alarm_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'Alarm deleted'})

@app.route('/take_pill', methods=['POST', 'OPTIONS'])
def take_pill():
    if request.method == 'OPTIONS':
        # Handle CORS preflight
        return ('', 204)
    # --- Your existing POST logic ---
    data = request.json
    userName = data.get('userName')
    med_name = data.get('medName')
    conn = db_connection()
    cur = conn.cursor()
    user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found'}), 404
    med = cur.execute('SELECT id, pills_per_dose FROM medications WHERE name=? AND user_id=?', (med_name, user['id'])).fetchone()
    if not med:
        conn.close()
        return jsonify({'error': 'Medication not found'}), 404
    pills_per_dose = med['pills_per_dose'] if 'pills_per_dose' in med.keys() else 1
    now = datetime.datetime.now().isoformat()
    cur.execute(
        'INSERT INTO pill_logs (user_id, med_id, taken_at) VALUES (?, ?, ?)', 
        (user['id'], med['id'], now)
    )
    cur.execute('UPDATE medications SET pills_left = pills_left - ? WHERE id=?', (pills_per_dose, med['id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'Pill logged', 'taken_at': now})

# --- LED/Alarm endpoints (dummy: replace print with GPIO logic later) ---
@app.route('/led/on', methods=['GET'])
def led_on():
    print('LED ON')
    return jsonify({'status': 'LED on'})

@app.route('/led/off', methods=['GET'])
def led_off():
    print('LED OFF')
    return jsonify({'status': 'LED off'})

@app.route('/led/blink', methods=['GET'])
def led_blink():
    print('LED BLINK')
    return jsonify({'status': 'LED blinked'})

@app.route('/alarming/on', methods=['GET'])
def alarming_on():
    print('ALARM ON')
    return jsonify({'status': 'Alarm triggered'})


# --- Start background threads & Flask app ---
if __name__ == '__main__':
    # --- Start Button Listening Thread ---
    threading.Thread(target=button_listener, daemon=True).start()
    threading.Thread(target=alarm_checker, daemon=True).start()
    print("Starting Flask app!")
    app.run(host='0.0.0.0', port=5000, debug=True)
