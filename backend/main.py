import logging
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting application...")
    for var in ["SUPABASE_URL", "SUPABASE_KEY", "OPENROUTER_API_KEY"]:
        if not os.getenv(var):
            logger.warning("Required env var %s is not set", var)
    await init_db()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_client = OpenRouterClient(api_key)
    app.state.chat_service = ChatService(openrouter_client)
    logger.info("Application started successfully")
    yield
    # Shutdown
    logger.info("Shutting down...")
    await openrouter_client.close()
    await close_db()


app = FastAPI(title="DEMO", lifespan=lifespan)

# CORS: use ALLOWED_ORIGINS env var in production
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


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
