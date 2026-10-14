# Project: Campus Swap Seller Onboarding Refactor (Updated)

## Context & Goal
We are redesigning the "Add Item" / Seller Onboarding flow to mimic Airbnb's "Become a Host" experience. The goal is to move from a standard form to a multi-step, progressive disclosure wizard.

## 🛑 CRITICAL TECHNICAL CONSTRAINTS
* **PRESERVE EXISTING LOGIC:** We already have robust logic for:
    * **Image Uploading:** The QR code reader for mobile uploads and the desktop file picker MUST remain intact.
    * **Photo Carousel:** The logic for selecting a "Cover/Main" photo and viewing uploaded images must be preserved.
    * **Location Data:** The logic for "On-Campus (Dropdown)" vs. "Off-Campus (Address Input)" is already built. Do not rewrite the backend logic for this, just wrap the UI.
* **Do NOT overwrite** the `handleImageUpload`, `handleCoverPhotoSelection`, or existing API calls for saving items. We are refactoring the *User Experience*, not the core utility functions.

---

## UI/UX Flow Architecture

The flow should be broken down into a "Wizard" component with a progress bar at the bottom.

### Step 1: "Tell us about your item" (Category Selection)
**UI Layout:**
* A clean grid of large, clickable cards/icons.
* **Header:** "Which of these best describes what you're selling?"
* **Sub-text:** "Don't worry, you can always edit details or upload more items later."

**Categories (Buttons/Cards):**
1.  **Mini Fridge** (Icon: Snowflake/Fridge)
2.  **Microwave** (Icon: Microwave)
3.  **Rug** (Icon: Square/Rug)
4.  **Couch/Sofa** (Icon: Couch)
5.  **Headboard** (Icon: Bed frame)
6.  **Mattress** (Icon: Bed)
7.  **TV / Electronics** (Icon: TV/Monitor)
8.  **Heater / AC Unit** (Icon: Fan/Thermometer)
9.  **Other Furniture** (Icon: Chair/Table)

**Action:** Clicking a category selects it and enables the "Next" button.

### Step 2: "Make it stand out" (Photos & Details)
**UI Layout:**
* **Full-Screen Dropzone:** Refactor the existing upload component to take up the majority of the screen, making it immersive.
* **Header:** "Upload a couple photos of your [Selected Category]."
* **Sub-text:** "Make sure to show any wear or tear!"

**Functionality:**
* Embed the existing **QR Code / Mobile Upload** trigger here visually.
* Embed the existing **Photo Carousel** logic here so they can swipe through what they just uploaded and star the cover photo.

### Step 3: Location & Contact Info
*Goal: Combine logistics so it feels like one "Where do we find you?" step.*

**UI Layout:**
* **Header:** "Where is this item located?"
* **Input Mechanism (Reuse existing logic):**
    * Radio/Toggle: "On-Campus" vs "Off-Campus".
    * **If On-Campus:** Show the existing Dorm Dropdown.
    * **If Off-Campus:** Show the existing Address Input field.
* **Contact Info (New Fields):**
    * **Phone Number:** "So we can text you upon arrival." (Input mask: `(555) 555-5555`)

### Step 4: Payout Setup
*Goal: Secure the payment method before they choose a service tier.*

**UI Layout:**
* **Header:** "How would you like to get paid?"
* **Input:**
    * **Venmo Handle:** (Input field with `@` prefix pre-filled).
* **Note:** "We'll send your earnings here once the item sells."

### Step 5: Service Tier Selection (The Business Logic)
**UI Layout:**
* **Header:** "Choose your pickup service."
* **Comparison Cards:** Display two distinct cards side-by-side (or stacked on mobile).

**Option A: "Valet Pickup" (Premium / Default)**
* **Badge:** "Recommended" or "Guaranteed"
* **Cost:** $15 Service Fee (Upfront).
* **Profit Split:** 50/50 (You keep 50% of sale price).
* **Benefits:**
    * ✅ We drive to you & pick it up.
    * ✅ Guaranteed storage space.
    * ✅ Zero hassle.
* **Action:** Triggers Stripe/Payment Modal immediately.

**Option B: "Self Drop-off" (Free)**
* **Cost:** $0 Upfront.
* **Profit Split:** 33/66 (You keep 33% of sale price).
* **Details:**
    * ⚠️ You must bring item to an on-campus POD.
    * ⚠️ Floor space not guaranteed.
    * ⚠️ Lower profit margin.
* **Note:** "You can always upgrade to Valet Pickup later from your dashboard."

**Logic Update:**
* If user selects **Option A** but cancels payment, default them to **Option B**.
* Save the `service_tier` in the database as `premium` or `standard`.

### Step 6: Review & Publish
* Summary of the item, the selected service tier, and the payout method.
* **Button:** "Publish Listing"

---

## Technical Implementation Notes

### Dashboard "Upgrade" Logic
* If a user selects **Option B (Free)** during onboarding, their item status in the DB is `standard`.
* **Dashboard Requirement:** On the "My Items" dashboard, add an "Upgrade to Valet Pickup" button next to any `standard` item.
* **Upgrade Action:** Clicking this button should re-open the Stripe modal for the $15 fee. Upon success, update the item status to `premium` and the profit split to 50/50.

### Data Saving
* Ensure that Phone Number and Venmo Handle are saved to the `User` profile (if not already present), not just the `Item` record, so they don't have to re-enter it for the next item.