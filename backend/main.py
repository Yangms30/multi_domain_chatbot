import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models.database import init_db, close_db
from services.openrouter import OpenRouterClient
from services.chat_service import ChatService
from routers import chatbots, chat, history, config
from routers import memory as memory_router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_client = OpenRouterClient(api_key)
    app.state.chat_service = ChatService(openrouter_client)
    yield
    # Shutdown
    await openrouter_client.close()
    await close_db()


app = FastAPI(title="DEMO", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(chatbots.router)
app.include_router(chat.router)
app.include_router(history.router)
app.include_router(config.router)
app.include_router(memory_router.router)

# Frontend static files (mount last so API routes take priority)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
