# MBGA Monorepo

This workspace contains two applications:

- `backend/` = FastAPI + MariaDB APIs
- `frontend/` = React + TypeScript Admin Web Panel

## Local Development

Terminal 1:

```powershell
cd backend
uvicorn app.main:app --reload
```

Terminal 2:

```powershell
cd frontend
npm run dev
```

Backend commands should be run from `backend/`. Frontend commands should be run from `frontend/`.
