# Uni-Vote: Class Representative Voting System

A Flask-based voting system for class representative elections.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`

## Local admin login

- USN: `ADMIN`
- Password: `admin123`

You can override both in production using environment variables:

- `ADMIN_USN`
- `ADMIN_PASSWORD`

## Production Deployment (Render + Supabase)

To ensure data is **never lost** during redeployments, this project uses an external PostgreSQL database (Supabase).

### Steps

1. **Database Setup**: Create a project on Supabase. Copy the **Connection String** (URI) from Project Settings > Database.
2. **GitHub**: Push your code to a GitHub repository.
3. **Host the App**: On Render, create a new **Web Service** and connect your repo.
4. **Environment Variables**: In the Render dashboard, add the following:
   - `DATABASE_URL`: Your Supabase connection string.
   - `SECRET_KEY`: A random long string for session security.
   - `ADMIN_PASSWORD`: Your custom admin password.
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`: For email features.
5. **Deploy**: Every time you push code to GitHub, Render will update the app. Your data remains safe in Supabase.

## Student flow

1. Register at `/register`
   - Uses an Alphanumeric Captcha for verification.
2. Login at `/login`.
3. Optionally enroll as candidate at `/candidate_register`.
4. Vote at `/vote` after admin enables voting.

## Admin tools

- View registered students and candidates at `/admin`
- Start or stop voting
- Delete students or candidates
- Reset any student's password from the admin panel

## Files

- `app.py`: Flask backend
- `requirements.txt`: Python dependencies
- `Procfile`: Production start command
- `render.yaml`: Render deployment config
- `templates/`: HTML templates
- `static/`: CSS, JS, and images
