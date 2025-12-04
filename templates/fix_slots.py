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
        print(f" Error: {STATE_FILE} not found!")
        print(f"   Current directory: {os.getcwd()}")
        return
    
    # Load state
    print(f"Loading {STATE_FILE}...")
    with open(STATE_FILE, 'r') as f:
        state = json.load(f)
    
    # Show current medications
    print("\n Current medications:")
    if not state.get("medications"):
        print("   (none)")
    else:
        for med in state["medications"]:
            print(f"   ID: {med['id']}, Name: {med['name']}, User ID: {med['user_id']}")
    
    # Show current slots
    print(f"\n Current med_slots: {state.get('med_slots', [])}")
    
    # Initialize med_slots if missing
    if "med_slots" not in state:
        state["med_slots"] = [None, None, None, None, None]
        print("   ✓ Created med_slots array")
    
    # Auto-assign medications to slots based on their ID
    # Med ID 1 → Slot 0, Med ID 2 → Slot 1, etc.
    assigned = []
    already_assigned = []
    conflicts = []
    
    for med in state["medications"]:
        med_id = med["id"]
        
        # Calculate target slot: med_id 1 → slot 0, med_id 2 → slot 1, etc.
        if 1 <= med_id <= 5:
            target_slot = med_id - 1  # Convert to 0-indexed
        else:
            print(f"  Warning: Med ID {med_id} ({med['name']}) is out of range (must be 1-5)")
            continue
        
        # Check if already assigned to correct slot
        if state["med_slots"][target_slot] == med_id:
            already_assigned.append((med_id, med["name"], target_slot + 1))
            continue
        
        # Check if target slot is occupied by another med
        if state["med_slots"][target_slot] is not None:
            conflicts.append((med_id, med["name"], target_slot + 1, state["med_slots"][target_slot]))
            print(f"  Warning: Slot {target_slot + 1} already occupied by Med {state['med_slots']['target_slot']}")
            continue
        
        # Assign to target slot
        state["med_slots"][target_slot] = med_id
        med["slot"] = target_slot + 1  # Add slot field to medication
        assigned.append((med_id, med["name"], target_slot + 1))
    
    # Save state
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)
    
    # Report results
    print(f"\n Updated med_slots: {state['med_slots']}")
    
    if already_assigned:
        print("\n Already assigned:")
        for med_id, name, slot in already_assigned:
            print(f"   - Med {med_id}: {name} → Slot {slot} (Button {slot}, LED {slot})")
    
    if assigned:
        print("\n Newly assigned:")
        for med_id, name, slot in assigned:
            print(f"   - Med {med_id}: {name} → Slot {slot} (Button {slot}, LED {slot})")
    
    if conflicts:
        print("\n  Conflicts (slot already occupied):")
        for med_id, name, slot, occupying_med_id in conflicts:
            print(f"   - Med {med_id}: {name} wanted Slot {slot}, but occupied by Med {occupying_med_id}")
    
    if not assigned and not already_assigned:
        print("\n  No medications found to assign")
    
    print("\n✓ Done! Restart your Flask app for changes to take effect.")
    print("\nSlot Mapping:")
    print("   Med ID 1 → Slot 0 → Button 1 (GPIO 16), LED 1 (GPIO 12)")
    print("   Med ID 2 → Slot 1 → Button 2 (GPIO 27), LED 2 (GPIO 5)")
    print("   Med ID 3 → Slot 2 → Button 3 (GPIO 22), LED 3 (GPIO 6)")
    print("   Med ID 4 → Slot 3 → Button 4 (GPIO 10), LED 4 (GPIO 13)")
    print("   Med ID 5 → Slot 4 → Button 5 (GPIO 9),  LED 5 (GPIO 19)")

if __name__ == "__main__":
    fix_slots()


