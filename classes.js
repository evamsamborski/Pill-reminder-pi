// ------- Medication Class -------
export class Medication {
  constructor(name, frequencyPerDay, taken = false, refillDate = new Date()) {
    this.name = name;
    this.frequencyPerDay = frequencyPerDay;
    this.taken = taken;
    this.refillDate = refillDate instanceof Date ? refillDate : new Date(refillDate);
  }

  markAsTaken() {
    this.taken = true;
  }

  resetTakenStatus() {
    this.taken = false;
  }
}


// ------- Person Class -------
export class Person {
  constructor(name) {
    this.name = name;
    this.medications = [];
  }

  addMedication(med) {
    if (this.medications.length >= 5) {
      console.warn(`${this.name} already has 5 medications.`);
      return;
    }
    this.medications.push(med);
  }

  listMedications() {
    console.log(`Medications for ${this.name}:`);
    this.medications.forEach((m, i) => {
      console.log(
        `${i + 1}. ${m.name} | ${m.frequencyPerDay}/day | Taken: ${m.taken} | Refill: ${m.refillDate.toDateString()}`
      );
    });
  }
}


// UserManager Class (integrated with API)
export class UserManager {
  constructor(apiBaseUrl) {
    this.apiBaseUrl = apiBaseUrl;
    this.people = [];
  }

  // API Communication

  async addPerson(person) {
    if (this.people.length >= 5) {
      console.warn("Cannot add more than 5 people.");
      return;
    }

    this.people.push(person);
    await this.savePersonToServer(person);
  }

  async savePersonToServer(person) {
    try {
      const res = await fetch(`${this.apiBaseUrl}/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: person.name,
          medications: person.medications.map(m => ({
            name: m.name,
            frequencyPerDay: m.frequencyPerDay,
            taken: m.taken,
            refillDate: m.refillDate.toISOString()
          }))
        })
      });

      if (!res.ok) {
        throw new Error(`Error saving person: ${res.status}`);
      }

      const data = await res.json();
      console.log(`Saved ${person.name} (User ID: ${data.userId ?? "N/A"})`);
    } catch (err) {
      console.error("Failed to save user:", err.message);
    }
  }

  async loadAllPeople() {
    try {
      const res = await fetch(`${this.apiBaseUrl}/users`);
      if (!res.ok) throw new Error(`Error loading data: ${res.status}`);

      const data = await res.json();
      this.people = data.map(p => {
        const person = new Person(p.name);
        p.medications.forEach(m => {
          person.addMedication(
            new Medication(m.name, m.frequencyPerDay, m.taken, new Date(m.refillDate))
          );
        });
        return person;
      });

      console.log("Users loaded from API:", this.people);
    } catch (err) {
      console.error("Failed to load users:", err.message);
    }
  }

  async clearAllDataOnServer() {
    try {
      await fetch(`${this.apiBaseUrl}/users`, { method: "DELETE" });
      this.people = [];
      console.log("All user data cleared on server");
    } catch (err) {
      console.error("Failed to clear data:", err.message);
    }
  }

  // ---- Helpers ----

  listAll() {
    this.people.forEach(p => p.listMedications());
  }
}