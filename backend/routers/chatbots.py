from fastapi import APIRouter
from models.schemas import ChatbotInfo
from services.domain_manager import get_all_chatbots, get_chatbot

router = APIRouter()


@router.get("/api/chatbots", response_model=list[ChatbotInfo])
async def list_chatbots(category: str = "all"):
    return get_all_chatbots(category)


@router.get("/api/chatbots/{domain}", response_model=ChatbotInfo)
async def get_chatbot_info(domain: str):
    return get_chatbot(domain)
