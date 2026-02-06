Campus Swap: Production-Ready Roadmap

Current State Summary

You have a solid Flask app with: user auth (including guest-to-account conversion), Stripe payments for seller activation and item purchases, admin panel for inventory management, and a clear seller flow (address -> upload items -> payout info -> pay $15 -> items go live). The codebase is generally well-structured.

Several issues need fixing before and after deployment, plus enhancements for robustness and UX.



Phase 1: Critical Fixes (Do First)

1.1 Photo Serving Bug (Production-Breaking)

Problem: All templates use url_for('static', filename='uploads/' + item.photo_url), which serves from static/uploads/. On Render with a persistent disk, photos are saved to /var/data/ and served by the /uploads/<filename> route. Templates never use that route, so all product photos will 404 on Render.

Fix: Update all 7 templates to use url_for('uploaded_file', filename=item.photo_url) (or photo.photo_url) instead of url_for('static', filename='uploads/' + ...).

Files: templates/admin.html, templates/dashboard.html, templates/inventory.html, templates/product.html, templates/edit_item.html, templates/item_success.html

Add null checks where item.photo_url or photo.photo_url might be empty to avoid template errors.

1.2 Login Button Typo

Problem: In templates/login.html line 22: bh\tn-primary — the button has no valid CSS class; the login button won't be styled.

Fix: Change to btn btn-primary.

1.3 Persistent Disk Configuration on Render

Current setup in app.py: Uses /var/data when it exists, else static/uploads locally. This is correct.

Action items:





In Render Dashboard: add a Persistent Disk to your web service with mount path /var/data and a reasonable size (e.g., 1GB).



Ensure your Render plan supports disks (paid tier required).



The app already creates the folder with os.makedirs(..., exist_ok=True).

1.4 Database Migrations

Problem: migrations/versions/ is empty — no migration scripts exist. Your schema lives only in models.py.

Fix:





Ensure migrations/env.py imports the app and models so Alembic can see the schema. Add at the top of env.py after imports: from app import app and from models import * (or explicitly import all models) so that db.metadata includes all tables.



Run flask db migrate -m "Initial schema" to create the initial migration.



On Render, add a build command: flask db upgrade (or run it as a release command) so migrations run before the app starts.



Use Render's PostgreSQL service and set DATABASE_URL in environment variables (you already handle the postgres:// -> postgresql:// conversion in app.py).



Phase 2: Security Hardening

2.1 Stripe Payment Verification (Critical)

Problem: app.py routes item_sold_success and payment_success trust the session_id from the URL. A user could guess or tamper with IDs and mark items as sold or activate accounts without paying.

Fix: Add a Stripe webhook that handles checkout.session.completed. Use the webhook as the source of truth for:





Marking inventory items as sold (using client_reference_id)



Setting has_paid = True for seller activation

Keep the success pages for UX (show confirmation, redirect), but do not change database state there. Optionally, verify the session with stripe.checkout.Session.retrieve() and check payment_status == 'paid' before updating state if you keep any logic on the success page.

2.2 CSRF Protection

Problem: Forms use POST without CSRF tokens. This leaves the app vulnerable to cross-site request forgery.

Fix: Add Flask-WTF and FlaskForm with CSRF protection. Add {{ form.csrf_token }} to all forms, or use CSRFProtect from flask_wtf.csrf for a site-wide approach.

2.3 Admin Access Control

Problem: Admin is restricted to current_user.id == 1. This is brittle (e.g., if user 1 is deleted) and not scalable for multiple employees.

Fix: Add an is_admin (or role) column to the User model. Use a migration to set is_admin=True for the appropriate user(s). Replace the admin check with current_user.is_authenticated and current_user.is_admin.

2.4 Database Security





Use parameterized queries only (SQLAlchemy ORM does this; avoid raw SQL).



Ensure SECRET_KEY is set via environment variable on Render (never commit it).



Use HTTPS (Render provides this by default).



Restrict database access: use Render's managed Postgres with internal networking if available, and do not expose DB credentials.



Phase 3: Email Capture and Notifications

3.1 Email Storage

Current state: Waitlist signups and new users are stored in the User table with email, referral_source, and date_joined. You have the data; you need a way to email it.

3.2 Email Service Options





Resend, SendGrid, Mailgun, or Postmark: All offer APIs and free tiers. Pick one and add it to requirements.txt.



Store API key in EMAIL_API_KEY (or similar) environment variable.

3.3 Implementation Tasks





Waitlist welcome: Send a welcome email when someone joins the waitlist (index form submits, new user created).



Account creation: Send a confirmation/welcome email when a user registers or sets a password.



Item sold notification: When an item is marked sold (via admin or webhook), email the seller with payout details (40% of sale price, Venmo/Zelle handle).



Optional: Periodic digest for waitlist (e.g., "We're live! Here's how to get started") — can be manual at first.



Phase 4: Admin Flow and Store Operations

4.1 Web vs. App

Recommendation: A responsive web admin is sufficient for most operations. Employees can use /admin on a tablet or phone in the browser. A native app adds maintenance and deployment overhead; consider it only if you hit clear limitations (e.g., barcode scanning, offline mode).

4.2 Admin Improvements





Item tagging: You mentioned items are tagged with name and email. The InventoryItem has seller_id (links to User). Ensure the admin table displays seller name and email clearly (it already does in templates/admin.html).



Payout tracking: Add a sold_at timestamp and payout_sent boolean (or payout_status) to record when a seller has been paid their 40%. This helps staff avoid double-payouts.



Quick actions: Consider a "Mark sold + email seller" button that combines both actions.



Admin nav link: Add a link to /admin in the header for logged-in admins only (e.g., "Admin" next to Dashboard when current_user.is_admin).



Phase 5: UI/UX Polish

5.1 Page Audit







Page



Notes





index.html



Strong hero and value props; typo "Campus SWap" in step 2





dashboard.html



Clear 3-step flow; ensure mobile layout is good





inventory.html



Category grid and cards look solid





product.html



Gallery, lightbox, buy button; check empty states





admin.html



Dense but functional; could use loading states for bulk saves





login/register



Simple; fix login button class





about.html



Minimal; could match card styling for consistency





add_item.html



Good UX with file drop zone





edit_item.html



Cancel goes to /admin for everyone; should go to dashboard for non-admins

5.2 Quick Fixes





Fix "Campus SWap" → "Campus Swap" in templates/index.html.



In templates/edit_item.html, make the Cancel button conditional: go to /admin if admin, else /dashboard.



Add an About link to the footer if desired.



Ensure all pages have consistent heading hierarchy and responsive breakpoints.



Phase 6: Deployment and Environment

6.1 Render Checklist





Create PostgreSQL database; add DATABASE_URL to web service



Add Persistent Disk with mount path /var/data



Set SECRET_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET (after webhook setup)



Add build command: pip install -r requirements.txt



Add release command: flask db upgrade



Start command: gunicorn app:app (or wsgi:app if you add a wsgi.py)

6.2 Optional: S3 for Photos

For scale, consider storing photos in S3 (or similar) instead of a disk. This simplifies backups and works better across multiple instances. Can be a later phase.



Recommended Order





Phase 1 (critical fixes) — unblocks deployment and ensures photos work



Phase 2 (security) — especially Stripe webhook and CSRF



Phase 4.2 (payout tracking) — small schema change, high operational value



Phase 3 (email) — improves user trust and reduces support



Phase 5 (polish) — incremental improvements



Architecture Overview

flowchart TB
    subgraph users [User Flow]
        Visitor[Visitor] --> |Join Waitlist| Index[index.html]
        Visitor --> |Browse| Inventory[inventory.html]
        Visitor --> |Buy| Stripe[Stripe Checkout]
        User[Logged-in User] --> Dashboard[dashboard.html]
        User --> AddItem[add_item.html]
    end
    
    subgraph admin [Admin Flow]
        Admin[Admin User] --> AdminPanel[admin.html]
        AdminPanel --> |Mark Sold| DB[(PostgreSQL)]
        AdminPanel --> |Update Prices| DB
        AdminPanel --> |Bulk Edit| DB
    end
    
    subgraph backend [Backend]
        App[app.py Flask]
        DB
        Disk[/var/data or static/uploads]
        Webhook[Stripe Webhook]
    end
    
    Index --> App
    Inventory --> App
    Dashboard --> App
    AdminPanel --> App
    App --> DB
    App --> Disk
    Stripe --> Webhook --> App



Questions to Decide





Email provider: Do you have a preference (Resend, SendGrid, Mailgun)?



Admin roles: Will you have multiple employees who need admin access, or just one?



Payout automation: Are payouts always manual (employee sends Venmo/Zelle), or do you want to explore Stripe Connect for automated payouts?

