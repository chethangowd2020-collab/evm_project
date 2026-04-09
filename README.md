# Class Representative Voting System (Smart EVM)

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

## Public deployment on Render

This project includes `render.yaml`, so you can deploy it and get a public link that keeps working even after you close VS Code.

### Steps

1. Upload this project to GitHub.
2. Create an account on Render.
3. In Render, choose `New +` -> `Blueprint`.
4. Connect your GitHub repository.
5. Render will detect `render.yaml` and create the web service.
6. Set `ADMIN_PASSWORD` in Render to a strong password before production use.
7. Add `DATABASE_PATH=/var/data/database.db` in Render environment variables.
8. Deploy and open the generated `https://...onrender.com` URL.

### Important note about data

The deployment is configured with a persistent disk mounted at `/var/data`. Pointing `DATABASE_PATH` there keeps your SQLite database across restarts and redeploys.

## Student flow

1. Register at `/register`
2. Login at `/login`
3. Optionally enroll as candidate at `/candidate_register`
4. Vote at `/vote` after admin enables voting

## Files

- `app.py`: Flask backend
- `requirements.txt`: Python dependencies
- `Procfile`: Production start command
- `render.yaml`: Render deployment config
- `templates/`: HTML templates
- `static/`: CSS, JS, and images
