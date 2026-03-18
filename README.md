# Campus Swap

A full-stack student marketplace for move-out consignment. Students 
drop off furniture and goods at move-out, we sell it during move-in, 
and they get a cut. Less waste, cheaper furniture for incoming 
students.

Live at [usecampusswap.com](https://usecampusswap.com)  
Currently operating at UNC Chapel Hill. Closing a $100k seed round.

[Portfolio writeup](https://portfolio-seven-mu-24.vercel.app/projects/campus-swap)

## Stack

| Layer | Tech |
|---|---|
| Backend | Flask 3.1.2 / Python 3.13 |
| Templating | Jinja2 |
| Database | PostgreSQL + Flask-Migrate |
| Auth | Google OAuth 2.0 |
| Storage | CDN (carousel/product images) |
| Frontend | Custom CSS with CSS variables, DM Serif Display |
| Testing | pytest |

## Features

- Seller onboarding flow with item submission and photo upload
- Admin dashboard for inventory management and item approval
- Shop front with category filtering and search
- Interactive room value calculator — hover items to see estimated 
  earnings before signing up
- Google OAuth login
- Email notifications
- Role system: buyer, seller, admin, super admin

## Running locally
```bash
git clone https://github.com/henryruss/campus-swap-live
cd campus-swap-live
pip install -r requirements.txt
cp .env.example .env  # fill in your env vars
flask db upgrade
python seed_db.py     # optional: seed with test data
flask run
```

See `GOOGLE_OAUTH_SETUP.md` for auth configuration.

## Testing
```bash
./run_tests.sh
# or
pytest
```

See `HOW_TO_RUN_TESTS.md` for full testing guide.
