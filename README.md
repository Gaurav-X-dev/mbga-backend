# MBGA Monorepo

This workspace contains two applications:

- `backend/` = FastAPI + MariaDB APIs
- `frontend/` = React + TypeScript Admin Web Panel

## Local Development

Terminal 1:

```powershell
cd backend
venv\Scripts\activate
uvicorn app.main:app --host 127.0.0.1 --port 8005 --reload
```

Terminal 2:

```powershell
cd frontend
npm run dev
```

The web panel expects the API at `http://127.0.0.1:8005/api/v1` (`frontend/.env`) and runs at
`http://127.0.0.1:5173`. See `frontend/README.md` for authentication, routes, tests and the
API gap list (`frontend/docs/API_INTEGRATION.md`).

Backend commands should be run from `backend/`. Frontend commands should be run from `frontend/`.
