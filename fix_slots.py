#!/usr/bin/env python3
"""
Fix medication slot assignments in state.json
Run this in the same directory as your state.json file
"""
import json
import os

STATE_FILE = 'state.json'

def fix_slots():
    if not os.path.exists(STATE_FILE):
        print(f"Error: {STATE_FILE} not found!")
        print(f"   Current directory: {os.getcwd()}")
        return
    
    # Load state
    print(f"Loading {STATE_FILE}...")
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
    
    # Show current medications
    print("\nCurrent medications:")
    if not state.get("medications"):
        print("   (none)")
    else:
        for med in state["medications"]:
            print(f"   ID: {med['id']}, Name: {med['name']}, User ID: {med['user_id']}")
    
    # Show current slots
    print(f"\nCurrent med_slots: {state.get('med_slots', [])}")
    
    # Initialize med_slots if missing
    if "med_slots" not in state:
        state["med_slots"] = [None, None, None, None, None]
        print("   Created med_slots array")
    
    # Option to clear and reassign all (safer for fixing issues)
    print("\nClearing all slots and reassigning from scratch...")
    state["med_slots"] = [None, None, None, None, None]
    
    # Auto-assign medications to slots based on their ID
    # Med ID 1 → Slot 0, Med ID 2 → Slot 1, etc.
    assigned = []
    out_of_range = []
    
    for med in state["medications"]:
        med_id = med["id"]
        
        # Calculate target slot: med_id 1 → slot 0, med_id 2 → slot 1, etc.
        if 1 <= med_id <= 5:
            target_slot = med_id - 1  # Convert to 0-indexed
            
            # Assign to target slot
            state["med_slots"][target_slot] = med_id
            med["slot"] = target_slot + 1  # Add slot field to medication
            assigned.append((med_id, med["name"], target_slot + 1))
            print(f"   Assigned Med {med_id} ({med['name']}) to Slot {target_slot + 1}")
        else:
            out_of_range.append((med_id, med["name"]))
            print(f"   Warning: Med ID {med_id} ({med['name']}) is out of range (must be 1-5)")
    
    # Save state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    # Report results
    print(f"\nUpdated med_slots: {state['med_slots']}")
    
    if assigned:
        print("\nAssigned medications:")
        for med_id, name, slot in assigned:
            print(f"   - Med {med_id}: {name} -> Slot {slot} (Button {slot}, LED {slot})")
    
    if out_of_range:
        print("\nWarning: Medications with IDs out of range (1-5):")
        for med_id, name in out_of_range:
            print(f"   - Med {med_id}: {name}")
    
    if not assigned:
        print("\nWarning: No medications found to assign")
    
    print("\nDone! Restart your Flask app for changes to take effect.")
    print("\nSlot Mapping:")
    for i in range(5):
        med_id = state["med_slots"][i]
        if med_id:
            med = next((m for m in state["medications"] if m["id"] == med_id), None)
            med_name = med["name"] if med else "Unknown"
            print(f"   Slot {i} (Button {i+1}, LED {i+1}) -> Med {med_id}: {med_name}")
        else:
            print(f"   Slot {i} (Button {i+1}, LED {i+1}) -> Empty")
    
    print("\nGPIO Mapping:")
    print("   Slot 0 -> Button 1 (GPIO 21) + LED 1 (GPIO 26)")
    print("   Slot 1 -> Button 2 (GPIO 16) + LED 2 (GPIO 19)")
    print("   Slot 2 -> Button 3 (GPIO 1)  + LED 3 (GPIO 13)")
    print("   Slot 3 -> Button 4 (GPIO 7)  + LED 4 (GPIO 6)")
    print("   Slot 4 -> Button 5 (GPIO 8)  + LED 5 (GPIO 5)")

if __name__ == "__main__":
    fix_slots()