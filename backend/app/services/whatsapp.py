import httpx
from app.config import settings

def send_whatsapp_message(to_number: str, text: str):
    url = f"https://graph.facebook.com/v19.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text}
    }
    
    response = httpx.post(url, headers=headers, json=data)
    response.raise_for_status()
    return response.json()
