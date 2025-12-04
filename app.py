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
            "users": [],          # {id, name}
            "medications": [],    # {id, user_id, name, frequencyPerDay, pills_left, pills_per_dose, slot}
            "alarms": [],         # {id, user_id, med_id, time}
            "pill_logs": [],      # {id, user_id, med_id, taken_at}
            "med_slots": [None, None, None, None, None]  # Maps slot index (0-4) to med_id
        }
        save_state(state)
        return state

    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        state = json.load(f)
        # Ensure med_slots exists for backwards compatibility
        if "med_slots" not in state:
            state["med_slots"] = [None, None, None, None, None]
        return state


def save_state(state):
    """Persist entire app state to JSON file."""
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def get_med_slot(med_id):
    """Get the slot index (0-4) for a given medication ID, or None if not assigned."""
    state = load_state()
    try:
        return state["med_slots"].index(med_id)
    except (ValueError, KeyError):
        return None


def assign_med_slot(med_id):
    """Assign a medication to the first available slot (0-4). Returns slot index or None if full."""
    state = load_state()
    for i in range(5):
        if state["med_slots"][i] is None:
            state["med_slots"][i] = med_id
            save_state(state)
            return i
    return None  # All slots full


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
        # External resistors handle pull; simple input
        GPIO.setup(pin, GPIO.IN)
    for pin in LED_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)
    for pin in BUZZER_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)  # Make sure both buzzers are OFF at boot


# --- Medication/Alarm State ---
med_alarm_active  = [False] * 5
med_alarm_context = [None] * 5  # stores alarm metadata (user_id, med_id, etc)


def start_buzzer():
    if PI_AVAILABLE:
        for pin in BUZZER_PINS:
            GPIO.output(pin, GPIO.HIGH)


def stop_buzzer():
    if PI_AVAILABLE:
        for pin in BUZZER_PINS:
            GPIO.output(pin, GPIO.LOW)


def trigger_alarm(slot_idx, user_id, med_id):
    """Trigger alarm for a specific slot (0-4)."""
    if not (0 <= slot_idx < 5):
        print(f"ERROR: Invalid slot index {slot_idx}")
        return

    print(f"--> TRIGGER: Slot {slot_idx+1}, User {user_id}, Med {med_id}")
    med_alarm_active[slot_idx] = True
    med_alarm_context[slot_idx] = {'user_id': user_id, 'med_id': med_id}

    if PI_AVAILABLE:
        GPIO.output(LED_PINS[slot_idx], GPIO.HIGH)
        # Only turn on buzzer if this is the first active alarm
        if sum(med_alarm_active) == 1:
            start_buzzer()


def clear_alarm(slot_idx):
    """When user presses button: clear alarm, log pill, decrement pills_left."""
    if not med_alarm_active[slot_idx]:
        return

    ctx = med_alarm_context[slot_idx]
    print(f"--> CLEAR: Slot {slot_idx+1}, User {ctx['user_id']}, Med {ctx['med_id']}")

    med_alarm_active[slot_idx] = False
    med_alarm_context[slot_idx] = None

    if PI_AVAILABLE:
        GPIO.output(LED_PINS[slot_idx], GPIO.LOW)
        # Only turn off buzzer if no other alarms are active
        if not any(med_alarm_active):
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
    """Monitor buttons and clear alarms when pressed."""
    print("Pill button listener running for 5 medications...")

    while True:
        if PI_AVAILABLE:
            for i, pin in enumerate(BUTTON_PINS):
                # With external resistors, assume button press drives pin HIGH
                buttonstate = GPIO.input(pin)
                if med_alarm_active[i] and buttonstate == GPIO.HIGH:
                    print(f"Button {i+1} pressed! Clearing alarm for slot {i+1}")
                    clear_alarm(i)
        else:
            # Simulation mode
            try:
                pressed = input("Simulate button press (enter slot 1-5): ").strip()
                if pressed:
                    slot_idx = int(pressed) - 1
                    if 0 <= slot_idx < 5 and med_alarm_active[slot_idx]:
                        clear_alarm(slot_idx)
                    elif 0 <= slot_idx < 5:
                        print(f"No active alarm for slot {slot_idx+1}")
                    else:
                        print("Invalid slot number (must be 1-5)")
            except (ValueError, EOFError):
                time.sleep(0.1)

        time.sleep(0.05)


def alarm_checker():
    """Background thread: checks alarms and triggers them when time matches."""
    print("Alarm checker thread started...")
    while True:
        now_hm = datetime.datetime.now().strftime('%H:%M')
        state = load_state()

        for alarm_row in state["alarms"]:
            if alarm_row["time"] == now_hm:
                med_id = alarm_row["med_id"]
                slot_idx = get_med_slot(med_id)

                if slot_idx is None:
                    print(f"WARNING: Medication {med_id} not assigned to any slot!")
                    continue

                # Only trigger if alarm not already active for this slot
                if not med_alarm_active[slot_idx]:
                    trigger_alarm(slot_idx, alarm_row["user_id"], med_id)

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

        # Assign to first available slot
        slot_idx = assign_med_slot(med_id)
        if slot_idx is None:
            return jsonify({'error': 'All medication slots (1-5) are full. Please remove a medication first.'}), 400

        med = {
            "id": med_id,
            "user_id": user["id"],
            "name": med_name,
            "frequencyPerDay": freq,
            "pills_left": pills_left,
            "pills_per_dose": pills_per_dose,
            "slot": slot_idx + 1  # Store as 1-5 for display
        }
        state["medications"].append(med)
        save_state(state)
        return jsonify({'status': 'Medication added', 'slot': slot_idx + 1})
    else:
        userName = request.args.get('userName')
        if not userName:
            return jsonify([])
        user = next((u for u in state["users"] if u["name"] == userName), None)
        if not user:
            return jsonify([])
        meds = [m for m in state["medications"] if m["user_id"] == user["id"]]
        return jsonify(meds)


@app.route('/medications/<int:med_id>', methods=['DELETE'])
def delete_medication(med_id):
    """Delete a medication and free up its slot."""
    state = load_state()

    # Find and remove medication
    med = next((m for m in state["medications"] if m["id"] == med_id), None)
    if not med:
        return jsonify({'error': 'Medication not found'}), 404

    state["medications"] = [m for m in state["medications"] if m["id"] != med_id]

    # Remove associated alarms
    state["alarms"] = [a for a in state["alarms"] if a["med_id"] != med_id]

    # Free up the slot
    slot_idx = get_med_slot(med_id)
    if slot_idx is not None:
        state["med_slots"][slot_idx] = None
        # Clear any active alarm for this slot
        if med_alarm_active[slot_idx]:
            med_alarm_active[slot_idx] = False
            med_alarm_context[slot_idx] = None
            if PI_AVAILABLE:
                GPIO.output(LED_PINS[slot_idx], GPIO.LOW)
                if not any(med_alarm_active):
                    stop_buzzer()

    save_state(state)
    return jsonify({'status': 'Medication deleted', 'freed_slot': slot_idx + 1 if slot_idx is not None else None})


@app.route('/slots', methods=['GET'])
def get_slots():
    """Get current slot assignments."""
    state = load_state()
    slots_info = []
    for i, med_id in enumerate(state["med_slots"]):
        if med_id is None:
            slots_info.append({"slot": i + 1, "status": "empty", "medication": None})
        else:
            med = next((m for m in state["medications"] if m["id"] == med_id), None)
            slots_info.append({
                "slot": i + 1,
                "status": "occupied",
                "medication": {
                    "id": med_id,
                    "name": med["name"] if med else "Unknown",
                    "user_id": med["user_id"] if med else None
                }
            })
    return jsonify(slots_info)


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
