import os
import anthropic
from flask import Flask, request, jsonify
import requests
from notion_client import Client
import json
from datetime import datetime

app = Flask(__name__)

# Initialize clients
notion = Client(auth=os.environ.get("NOTION_API_KEY"))
anthropic_client = anthropic.Anthropic(
    api_key=os.environ.get("ANTHROPIC_API_KEY")
)

# Environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
AUTHORIZED_CHAT_ID = int(os.environ.get("AUTHORIZED_CHAT_ID"))

# Notion page IDs
NOTION_PAGES = {
    "todo": os.environ.get("NOTION_TODO_PAGE"),
    "shopping": os.environ.get("NOTION_SHOPPING_PAGE"),
    "projects": os.environ.get("NOTION_PROJECTS_PAGE"),
    "brain_dump": os.environ.get("NOTION_BRAIN_DUMP_PAGE"),
    "personal": os.environ.get("NOTION_PERSONAL_PAGE")
}

def analyze_with_claude(text):
    """Use Claude to analyze and categorize the message"""
    try:
        # Create the message with Claude
        message = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",  # Using Haiku for cost-effectiveness
            max_tokens=1000,
            temperature=0.3,
            system="""You are a smart task categorizer. Analyze the user's message and:
            1. Break it down into individual tasks/items
            2. Categorize each item into one of these categories:
               - todo: General tasks, to-do items
               - shopping: Items to buy, shopping lists
               - projects: Project-related tasks, work items
               - personal: Personal development, self-improvement, calls to family/friends
               - brain_dump: Ideas, thoughts, notes, anything that doesn't fit other categories
            
            Return a JSON object with this structure:
            {
                "items": [
                    {
                        "text": "the task or item",
                        "category": "category_name"
                    }
                ]
            }
            
            Be concise but preserve the essential information.""",
            messages=[
                {
                    "role": "user",
                    "content": text
                }
            ]
        )
        
        # Parse Claude's response
        response_text = message.content[0].text
        try:
            # Try to extract JSON from the response
            # Claude might wrap it in markdown code blocks
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            elif "```" in response_text:
                json_start = response_text.find("```") + 3
                json_end = response_text.find("```", json_start)
                response_text = response_text[json_start:json_end].strip()
            
            return json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, return a fallback
            return {
                "items": [{
                    "text": text,
                    "category": "brain_dump"
                }]
            }
            
    except Exception as e:
        print(f"Claude API error: {e}")
        # Fallback to basic categorization
        return basic_categorization(text)

def basic_categorization(text):
    """Fallback categorization without AI"""
    text_lower = text.lower()
    
    # Simple keyword-based categorization
    if any(word in text_lower for word in ["buy", "shopping", "store", "groceries"]):
        category = "shopping"
    elif any(word in text_lower for word in ["project", "work", "deadline", "meeting"]):
        category = "projects"
    elif any(word in text_lower for word in ["call", "mom", "dad", "family", "self", "personal"]):
        category = "personal"
    elif any(word in text_lower for word in ["todo", "task", "do", "finish", "complete"]):
        category = "todo"
    else:
        category = "brain_dump"
    
    return {
        "items": [{
            "text": text,
            "category": category
        }]
    }

def add_to_notion(text, category):
    """Add item to the appropriate Notion page"""
    page_id = NOTION_PAGES.get(category, NOTION_PAGES["brain_dump"])
    
    try:
        notion.pages.create(
            parent={"database_id": page_id},
            properties={
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": text
                            }
                        }
                    ]
                },
                "Status": {
                    "select": {
                        "name": "Not started"
                    }
                },
                "Created": {
                    "date": {
                        "start": datetime.now().isoformat()
                    }
                }
            }
        )
        return True
    except Exception as e:
        print(f"Notion error: {e}")
        return False

def send_telegram_message(chat_id, text):
    """Send a message back to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram messages"""
    data = request.json
    
    # Extract message details
    if 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')
        
        # Check authorization
        if chat_id != AUTHORIZED_CHAT_ID:
            send_telegram_message(chat_id, "⛔ Unauthorized. This bot is private.")
            return jsonify({"status": "unauthorized"})
        
        if text:
            # Analyze with Claude
            analysis = analyze_with_claude(text)
            
            # Process each item
            success_count = 0
            responses = []
            
            for item in analysis['items']:
                if add_to_notion(item['text'], item['category']):
                    success_count += 1
                    category_name = item['category'].replace('_', ' ').title()
                    responses.append(f"✅ Added to {category_name}: {item['text']}")
                else:
                    responses.append(f"❌ Failed to add: {item['text']}")
            
            # Send response
            response_text = "\n".join(responses)
            if success_count == len(analysis['items']):
                response_text += "\n\n🎉 All items processed successfully!"
            
            send_telegram_message(chat_id, response_text)
    
    return jsonify({"status": "ok"})

@app.route('/')
def home():
    return "Brain Dump Bot is running! 🧠"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
