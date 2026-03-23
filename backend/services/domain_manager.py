DOMAIN_CHATBOTS = {
    "healthcare": {
        "domain": "healthcare",
        "name": "Health Coach",
        "description": "AI health coach providing personalized consultations, symptom analysis, and exercise/diet recommendations.",
        "icon": "health_and_safety",
        "color": "#10b981",
        "rating": 4.8,
        "uses": "3.2k",
        "supports_image": False,
        "system_prompt": (
            "You are a professional AI health coach.\n\n"
            "Role:\n"
            "- Provide friendly and professional consultations about the user's health, symptoms, and lifestyle\n"
            "- Offer symptom analysis and general health advice\n"
            "- Recommend customized exercise routines and diets\n"
            "- Give specific, actionable advice for improving health habits\n\n"
            "Guidelines:\n"
            "- Do not make medical diagnoses. Always recommend visiting a doctor for serious symptoms\n"
            "- Keep responses specific and actionable"
        ),
    },
    "movie": {
        "domain": "movie",
        "name": "Movie Expert",
        "description": "AI movie expert providing recommendations, image-based movie identification, and detailed movie information.",
        "icon": "movie",
        "color": "#8b5cf6",
        "rating": 4.7,
        "uses": "2.8k",
        "supports_image": True,
        "system_prompt": (
            "You are an AI movie expert.\n\n"
            "Role:\n"
            "- Recommend movies based on user preferences (genre, mood, actors, etc.)\n"
            "- Provide detailed movie information (plot, cast, director, ratings, release date, etc.)\n"
            "- Identify movies from images sent by the user\n"
            "- Engage in movie-related conversations (reviews, comparisons, trivia, etc.)\n\n"
            "Guidelines:\n"
            "- Warn before giving spoilers\n"
            "- Suggest 3-5 movies with reasons when recommending"
        ),
    },
}


def get_all_chatbots(category: str = "all") -> list[dict]:
    if category == "all":
        return [
            {k: v for k, v in bot.items() if k != "system_prompt"}
            for bot in DOMAIN_CHATBOTS.values()
        ]
    if category in DOMAIN_CHATBOTS:
        bot = DOMAIN_CHATBOTS[category]
        return [{k: v for k, v in bot.items() if k != "system_prompt"}]
    return []


def get_chatbot(domain: str) -> dict | None:
    if domain not in DOMAIN_CHATBOTS:
        return None
    bot = DOMAIN_CHATBOTS[domain]
    return {k: v for k, v in bot.items() if k != "system_prompt"}


def get_system_prompt(domain: str) -> str:
    if domain not in DOMAIN_CHATBOTS:
        return ""
    return DOMAIN_CHATBOTS[domain]["system_prompt"]
