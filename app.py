# --- Imports ---
from flask import Flask, render_template, request, jsonify
import datetime
import threading
import time
import sys
import json
import os

# --- Flask & "DB" Setup (JSON file) ---
app = Flask(__name__)

STATE_PATH = 'state.json'

def load_state():
    """Load entire app state from JSON file, or create a default one."""
    if not os.path.exists(STATE_PATH):
        state = {
            "next_ids": {
                "user": 1,
                "med": 1,
                "alarm": 1,
                "pill_log": 1
            },
            "users": [],         # {id, name}
            "medications": [],   # {id, user_id, name, frequencyPerDay, pills_left, pills_per_dose}
            "alarms": [],        # {id, user_id, med_id, time}
            "pill_logs": []      # {id, user_id, med_id, taken_at}
        }
        save_state(state)
        return state
    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_state(state):
    """Persist entire app state to JSON file."""
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)

# --- CORS: Manual Header if flask_cors not installed ---
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    return response

# --- Platform Detection & GPIO Setup ---
PI_AVAILABLE = False
try:
    import RPi.GPIO as GPIO
    PI_AVAILABLE = True
except ImportError:
    print("RPi.GPIO not available. Button press will be simulated.")

# Assignments for 5 buttons, 5 LEDs, 2 buzzers (BCM pin numbers)
BUTTON_PINS = [16, 27, 22, 10, 9]    # Each button for one medication
LED_PINS    = [12, 5, 6, 13, 19]     # Each LED for one medication
BUZZER_PINS = [14, 15]               # Both buzzers for alarm intensity

if PI_AVAILABLE:
    GPIO.setmode(GPIO.BCM)
    for pin in BUTTON_PINS:
        # External pull-down on breadboard: use PUD_DOWN and detect HIGH on press
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    for pin in LED_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    for pin in BUZZER_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)  # Make sure both buzzers are OFF at boot

# --- Medication/Alarm State ---
med_alarm_active  = [False] * 5
med_alarm_context = [None] * 5  # stores alarm metadata (user_id, med_id, etc)
last_alarm_cleared = False      # debug flag for UI

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
    """When user presses button: clear alarm, log pill, decrement pills_left."""
    global last_alarm_cleared
    ctx = med_alarm_context[idx]
    print(f"--> CLEAR: Med {idx+1}, User {ctx['user_id']}, Med {ctx['med_id']}")
    med_alarm_active[idx]  = False
    med_alarm_context[idx] = None
    last_alarm_cleared     = True
    if PI_AVAILABLE:
        GPIO.output(LED_PINS[idx], GPIO.LOW)
        stop_buzzer()

    # --- Log pill & decrement pills_left in JSON "DB" ---
    state = load_state()
    now = datetime.datetime.now().isoformat()

    # Find medication and decrement
    med = next((m for m in state["medications"] if m["id"] == ctx["med_id"]), None)
    if med:
        med["pills_left"] = max(0, med.get("pills_left", 0) - 1)

    # Add pill_log entry
    pill_log_id = state["next_ids"]["pill_log"]
    state["next_ids"]["pill_log"] += 1
    state["pill_logs"].append({
        "id": pill_log_id,
        "user_id": ctx["user_id"],
        "med_id": ctx["med_id"],
        "taken_at": now
    })

    save_state(state)

def button_listener():
    print("Pill button listener running for 5 medications...")
    while True:
        if PI_AVAILABLE:
            for i, pin in enumerate(BUTTON_PINS):
                # With external pull-down, button press drives pin HIGH
                if med_alarm_active[i] and GPIO.input(pin) == GPIO.HIGH:
                    print(f"Button {i+1} pressed! Logging pill, turning off LED & buzzers...")
                    clear_alarm(i)
                    time.sleep(1)  # Debounce per button

        else:
            pressed = input("Simulate button press (enter index 1-5): ")
            try:
                i = int(pressed) - 1
                if 0 <= i < 5 and med_alarm_active[i]:
                    clear_alarm(i)
            except ValueError:
                print("Invalid input.")
        time.sleep(0.05)

def alarm_checker():
    """Background thread: checks alarms and triggers them when time matches."""
    while True:
        now_hm = datetime.datetime.now().strftime('%H:%M')
        state = load_state()
        # Must use separate alarms for each med/user combo
        for alarm_row in state["alarms"]:
            if alarm_row["time"] == now_hm:
                idx = alarm_row["med_id"] - 1  # Map med_id (1-5) to index (0-4)
                if 0 <= idx < 5 and not med_alarm_active[idx]:
                    trigger_alarm(idx, alarm_row["user_id"], alarm_row["med_id"])
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
    state = load_state()
    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name')
        print(f"Adding user: {name}")
        # Check if user exists
        existing = next((u for u in state["users"] if u["name"] == name), None)
        if existing:
            return jsonify({'id': existing["id"], 'name': existing["name"]})
        # Create new user
        user_id = state["next_ids"]["user"]
        state["next_ids"]["user"] += 1
        user = {"id": user_id, "name": name}
        state["users"].append(user)
        save_state(state)
        return jsonify({'id': user_id, 'name': name})
    else:
        return jsonify(state["users"])

@app.route('/medications', methods=['POST', 'GET'])
def medications():
    state = load_state()
    if request.method == 'POST':
        data = request.json or {}
        userName = data.get('userName')
        med_name = data.get('name')
        freq = data.get('frequencyPerDay')
        pills_left = data.get('pills_left', 30)
        pills_per_dose = data.get('pills_per_dose', 1)

        user = next((u for u in state["users"] if u["name"] == userName), None)
        if not user:
            return jsonify({'error': 'User not found'}), 404

        med_id = state["next_ids"]["med"]
        state["next_ids"]["med"] += 1
        med = {
            "id": med_id,
            "user_id": user["id"],
            "name": med_name,
            "frequencyPerDay": freq,
            "pills_left": pills_left,
            "pills_per_dose": pills_per_dose
        }
        state["medications"].append(med)
        save_state(state)
        return jsonify({'status': 'Medication added'})
    else:
        userName = request.args.get('userName')
        if not userName:
            return jsonify([])
        user = next((u for u in state["users"] if u["name"] == userName), None)
        if not user:
            return jsonify([])
        meds = [m for m in state["medications"] if m["user_id"] == user["id"]]
        return jsonify(meds)

@app.route('/pill_logs', methods=['GET'])
def pill_logs():
    userName = request.args.get('userName')
    state = load_state()
    user = next((u for u in state["users"] if u["name"] == userName), None)
    if not user:
        return jsonify([])
    # Join pill_logs with medications in Python
    logs = []
    for pl in state["pill_logs"]:
        if pl["user_id"] == user["id"]:
            med = next((m for m in state["medications"] if m["id"] == pl["med_id"]), None)
            logs.append({
                "taken_at": pl["taken_at"],
                "name": med["name"] if med else "Unknown"
            })
    # Sort newest first
    logs.sort(key=lambda x: x["taken_at"], reverse=True)
    return jsonify(logs)

@app.route('/alarms', methods=['POST', 'GET'])
def alarms():
    state = load_state()
    if request.method == 'POST':
        data = request.json or {}
        userName = data.get('userName')
        med_name = data.get('medName')
        time_val = data.get('time')

        if not userName or not med_name or not time_val:
            return jsonify({'error': 'Missing userName, medName, or time'}), 400

        user = next((u for u in state["users"] if u["name"] == userName), None)
        if not user:
            return jsonify({'error': 'User or medication not found'}), 404

        med = next(
            (m for m in state["medications"] if m["name"] == med_name and m["user_id"] == user["id"]),
            None
        )
        if not med:
            return jsonify({'error': 'User or medication not found'}), 404

        alarm_id = state["next_ids"]["alarm"]
        state["next_ids"]["alarm"] += 1
        alarm = {
            "id": alarm_id,
            "user_id": user["id"],
            "med_id": med["id"],
            "time": time_val
        }
        state["alarms"].append(alarm)
        save_state(state)
        return jsonify({'status': 'Alarm added'}), 201
    else:
        return jsonify(state["alarms"])

@app.route('/alarms/<int:alarm_id>', methods=['DELETE'])
def delete_alarm(alarm_id):
    state = load_state()
    before = len(state["alarms"])
    state["alarms"] = [a for a in state["alarms"] if a["id"] != alarm_id]
    after = len(state["alarms"])
    save_state(state)
    return jsonify({'status': 'Alarm deleted', 'removed': before - after})

@app.route('/take_pill', methods=['POST', 'OPTIONS'])
def take_pill():
    if request.method == 'OPTIONS':
        return ('', 204)

    data = request.json or {}
    userName = data.get('userName')
    med_name = data.get('medName')

    state = load_state()
    user = next((u for u in state["users"] if u["name"] == userName), None)
    if not user:
        return jsonify({'error': 'User or medication not found'}), 404
    med = next(
        (m for m in state["medications"] if m["name"] == med_name and m["user_id"] == user["id"]),
        None
    )
    if not med:
        return jsonify({'error': 'User or medication not found'}), 404

    pills_per_dose = med.get("pills_per_dose", 1)
    now = datetime.datetime.now().isoformat()

    # Log pill
    pill_log_id = state["next_ids"]["pill_log"]
    state["next_ids"]["pill_log"] += 1
    state["pill_logs"].append({
        "id": pill_log_id,
        "user_id": user["id"],
        "med_id": med["id"],
        "taken_at": now
    })
    # Decrement pills_left
    med["pills_left"] = max(0, med.get("pills_left", 0) - pills_per_dose)

    save_state(state)
    return jsonify({'status': 'Pill logged', 'taken_at': now})

# --- Debug: hardware alarm status for UI ---
@app.route('/alarm_status', methods=['GET'])
def alarm_status():
    global last_alarm_cleared
    status = {'just_cleared': last_alarm_cleared}
    last_alarm_cleared = False
    return jsonify(status)

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

def cleanup_gpio():
    if PI_AVAILABLE:
        print("Cleaning up GPIO...")
        GPIO.cleanup()

if __name__ == '__main__':
    # Ensure state.json exists with base structure
    _ = load_state()

    threading.Thread(target=button_listener, daemon=True).start()
    threading.Thread(target=alarm_checker, daemon=True).start()
    print("Starting Flask app!")
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    finally:
        cleanup_gpio()

