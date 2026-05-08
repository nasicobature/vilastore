# EduPortal

EduPortal is a school management portal with a Django backend and a React/Vite frontend prototype.

## Backend

```powershell
cd portal
python manage.py migrate
python manage.py runserver
```

## Frontend

```powershell
cd portal/academia-hub-main
npm ci
npm run dev
```

## Current Status

- Django system checks pass locally.
- Database migrations are present and in sync.
- React frontend source is present, but dependencies must be installed before building.
- Production settings still need environment-based `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, and secure cookie/HTTPS settings before deployment.
