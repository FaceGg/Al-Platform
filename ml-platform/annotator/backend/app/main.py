from fastapi import FastAPI
from app.api.auth import router as auth_router
from app.api.tasks import router as tasks_router
from app.api.comments import router as comments_router

app = FastAPI(title="Annotator Portal")
app.include_router(auth_router)
app.include_router(tasks_router)
app.include_router(comments_router)
