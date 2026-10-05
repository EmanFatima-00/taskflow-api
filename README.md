# TaskFlow API

A task manager built with a FastAPI REST API and a React frontend, all in one `main.py` file. The frontend uses the API to retrieve, create, update and delete tasks.

## Features

- Full CRUD API (GET, POST, PUT, PATCH, DELETE)
- Validation, HTTP status codes and structured JSON responses
- SQLite storage
- Search, filters, sorting and pagination
- React dashboard with dark mode
- Swagger docs at `/docs`

## Tech Stack

Python, FastAPI, SQLite, React, Tailwind CSS

## Run Locally

```
pip install -r requirements.txt
uvicorn main:app --reload
```

- App: http://localhost:8000
- API docs: http://localhost:8000/docs

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/tasks` | List tasks |
| GET | `/api/tasks/{id}` | Get one task |
| POST | `/api/tasks` | Create a task |
| PUT | `/api/tasks/{id}` | Replace a task |
| PATCH | `/api/tasks/{id}` | Update part of a task |
| DELETE | `/api/tasks/{id}` | Delete a task |

## Author

Eman
