from fastapi import APIRouter, HTTPException
from models.schemas import ChatbotInfo
from services.domain_manager import get_all_chatbots, get_chatbot

router = APIRouter()


@router.get("/api/chatbots", response_model=list[ChatbotInfo])
async def list_chatbots(category: str = "all"):
    return get_all_chatbots(category)


@router.get("/api/chatbots/{domain}", response_model=ChatbotInfo)
async def get_chatbot_info(domain: str):
    bot = get_chatbot(domain)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Domain not found: {domain}")
    return bot
