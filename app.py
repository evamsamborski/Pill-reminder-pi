# --- Imports ---
from flask import Flask, render_template, request, jsonify
import sqlite3
import datetime
import threading
import time
import sys

# --- Flask & DB Setup ---
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

# --- Set up tables automatically (idempotent/init step) ---
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
            med_id INTEGER,
            time TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(med_id) REFERENCES medications(id)
        )
    ''')
    conn.commit()
    conn.close()
init_db()  # <--- Ensure DB is initialized at app start

# --- Platform Detection & GPIO Setup ---
PI_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    PI_AVAILABLE = True
except ImportError:
    print("RPi.GPIO not available. Button press will be simulated.")

# Assignments for 5 buttons, 5 LEDs, 2 buzzers (BCM pin numbers)
BUTTON_PINS = [17, 27, 22, 10, 9]    # Each button for one medication
LED_PINS = [4, 5, 6, 13, 19]         # Each LED for one medication
BUZZER_PINS = [14, 15]               # Both buzzers for alarm intensity

if PI_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    for pin in BUTTON_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    for pin in LED_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    for pin in BUZZER_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)  # Make sure both buzzers are OFF at boot

# --- Medication/Alarm State ---
med_alarm_active = [False] * 5
med_alarm_context = [None] * 5 # stores alarm metadata (user_id, med_id, etc)

def start_buzzer():
    if PI_AVAILABLE:
        for pin in BUZZER_PINS:
            GPIO.output(pin, GPIO.HIGH)
def stop_buzzer():
    if PI_AVAILABLE:
        for pin in BUZZER_PINS:
            GPIO.output(pin, GPIO.LOW)

def trigger_alarm(idx, user_id, med_id):
    print(f"--> TRIGGER: Med {idx+1}, User {user_id}, Med {med_id}")
    med_alarm_active[idx] = True
    med_alarm_context[idx] = {'user_id': user_id, 'med_id': med_id}
    if PI_AVAILABLE:
        GPIO.output(LED_PINS[idx], GPIO.HIGH)
        start_buzzer()

def clear_alarm(idx):
    ctx = med_alarm_context[idx]
    print(f"--> CLEAR: Med {idx+1}, User {ctx['user_id']}, Med {ctx['med_id']}")
    med_alarm_active[idx] = False
    med_alarm_context[idx] = None
    if PI_AVAILABLE:
        GPIO.output(LED_PINS[idx], GPIO.LOW)
        stop_buzzer()
    # Log pill to DB
    now = datetime.datetime.now().isoformat()
    conn = db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO pill_logs (user_id, med_id, taken_at) VALUES (?, ?, ?)',
        (ctx['user_id'], ctx['med_id'], now)
    )
    # Decrement pills_left for medication (by 1 per alarm event)
    cur.execute('UPDATE medications SET pills_left = pills_left - 1 WHERE id=?', (ctx['med_id'],))
    conn.commit()
    conn.close()

def button_listener():
    print("Pill button listener running for 5 medications...")
    while True:
        if PI_AVAILABLE:
            for i, pin in enumerate(BUTTON_PINS):
                if med_alarm_active[i] and GPIO.input(pin) == GPIO.LOW:
                    print(f"Button {i+1} pressed! Logging pill, turning off LED & buzzers...")
                    clear_alarm(i)
                    time.sleep(1) # Debounce per button
        else:
            pressed = input("Simulate button press (enter index 1-5): ")
            i = int(pressed) - 1
            if med_alarm_active[i]:
                clear_alarm(i)
        time.sleep(0.05)

def alarm_checker():
    while True:
        now = datetime.datetime.now().strftime('%H:%M')
        conn = db_connection()
        cur = conn.cursor()
        # Must use separate alarms for each med/user combo
        alarms = cur.execute('SELECT id, user_id, med_id, time FROM alarms WHERE time=?', (now,)).fetchall()
        for alarm_row in alarms:
            # Map the med_id (1-5) to index (0-4)
            idx = alarm_row['med_id'] - 1
            if 0 <= idx < 5 and not med_alarm_active[idx]:
                trigger_alarm(idx, alarm_row['user_id'], alarm_row['med_id'])
        conn.close()
        time.sleep(30)  # Check every 30 seconds

# --- Flask Routes and App Startup ---
@app.route("/")
def dashboard():
    return render_template("testtt.html")

@app.route("/add_user")
def add_user_page():
    return render_template("add_user.html")

@app.route("/configure_alarm")
def configure_alarm_page():
    return render_template("configure_alarm.html")

@app.route("/add_medication")
def add_medication_page():
    return render_template("add_medication.html")

@app.route("/take_pill")
def take_pill_page():
    return render_template("take_pill.html")

# --- USER API (long-term, robust) ---
@app.route('/users', methods=['POST', 'GET'])
def users():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        name = request.json.get('name')
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

@app.route('/medications', methods=['POST', 'GET'])
def medications():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        userName = request.json.get('userName')
        med_name = request.json.get('name')
        freq = request.json.get('frequencyPerDay')
        pills_left = request.json.get('pills_left', 30)
        pills_per_dose = request.json.get('pills_per_dose', 1)
        user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        user_id = user['id']
        cur.execute(
            'INSERT INTO medications (user_id, name, frequencyPerDay, pills_left, pills_per_dose) VALUES (?, ?, ?, ?, ?)',
            (user_id, med_name, freq, pills_left, pills_per_dose)
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

@app.route('/alarms', methods=['POST', 'GET'])
def alarms():
    conn = db_connection()
    cur = conn.cursor()
    if request.method == 'POST':
        userName = request.json.get('userName')
        med_name = request.json.get('medName')
        time_val = request.json.get('time')
        user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
        med = cur.execute('SELECT id FROM medications WHERE name=? AND user_id=?', (med_name, user['id'])).fetchone()
        if not user or not med:
            conn.close()
            return jsonify({'error': 'User or medication not found'}), 404
        cur.execute('INSERT INTO alarms (user_id, med_id, time) VALUES (?, ?, ?)', (user['id'], med['id'], time_val))
        conn.commit()
        conn.close()
        return jsonify({'status': 'Alarm added'}), 201
    else:
        alarms = cur.execute('SELECT id, user_id, med_id, time FROM alarms').fetchall()
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
        return ('', 204)
    data = request.json
    userName = data.get('userName')
    med_name = data.get('medName')
    conn = db_connection()
    cur = conn.cursor()
    user = cur.execute('SELECT id FROM users WHERE name=?', (userName,)).fetchone()
    med = cur.execute('SELECT id, pills_per_dose FROM medications WHERE name=? AND user_id=?', (med_name, user['id'])).fetchone()
    if not user or not med:
        conn.close()
        return jsonify({'error': 'User or medication not found'}), 404
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

if __name__ == '__main__':
    threading.Thread(target=button_listener, daemon=True).start()
    threading.Thread(target=alarm_checker, daemon=True).start()
    print("Starting Flask app!")
    app.run(host='0.0.0.0', port=5000, debug=True)
