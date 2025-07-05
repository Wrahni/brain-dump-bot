import os
from flask import Flask, request, jsonify
import requests
from notion_client import Client
import json
from datetime import datetime

app = Flask(__name__)

# Initialize Notion client
notion = Client(auth=os.environ.get("NOTION_API_KEY"))

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

# Try to import anthropic
try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
    anthropic_client = None
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("Anthropic module not available, using basic categorization")

def analyze_with_claude(text):
    """Use Claude to analyze and categorize the message"""
    if not ANTHROPIC_AVAILABLE:
        return basic_categorization(text)
    
    try:
        global anthropic_client
        if anthropic_client is None:
            anthropic_client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
        
        # Create the message with Claude
        message = anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
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
            return basic_categorization(text)
            
    except Exception as e:
        print(f"Claude API error: {e}")
        return basic_categorization(text)

def basic_categorization(text):
    """Fallback categorization without AI"""
    text_lower = text.lower()
    items = []
    
    # Try to split by common separators
    parts = []
    if " and " in text_lower:
        parts = text.split(" and ")
    elif ", " in text:
        parts = text.split(", ")
    else:
        parts = [text]
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        part_lower = part.lower()
        
        # Categorize based on keywords
        if any(word in part_lower for word in ["buy", "shopping", "store", "groceries", "get", "pick up"]):
            category = "shopping"
        elif any(word in part_lower for word in ["project", "work", "deadline", "meeting", "report", "presentation"]):
            category = "projects"
        elif any(word in part_lower for word in ["call", "mom", "dad", "family", "self", "personal", "gym", "doctor", "exercise"]):
            category = "personal"
        elif any(word in part_lower for word in ["todo", "task", "do", "finish", "complete", "pay", "send", "email"]):
            category = "todo"
        else:
            category = "brain_dump"
        
        items.append({
            "text": part,
            "category": category
        })
    
    # If no items were split, just use the whole text
    if not items:
        items.append({
            "text": text,
            "category": "brain_dump"
        })
    
    return {"items": items}

def add_to_notion(text, category):
    """Add item to the appropriate Notion page"""
    page_id = NOTION_PAGES.get(category, NOTION_PAGES["brain_dump"])
    
    try:
        # First, let's try with just the Name property
        properties = {
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": text
                        }
                    }
                ]
            }
        }
        
        # Try to create the page
        notion.pages.create(
            parent={"database_id": page_id},
            properties=properties
        )
        return True
        
    except Exception as e:
        print(f"Notion error: {e}")
        # If it fails, try with a simpler structure
        try:
            # Some Notion databases might use "Title" instead of "Name"
            properties = {
                "Title": {
                    "title": [
                        {
                            "text": {
                                "content": text
                            }
                        }
                    ]
                }
            }
            notion.pages.create(
                parent={"database_id": page_id},
                properties=properties
            )
            return True
        except:
            # Last resort - try without any properties (some databases auto-create title)
            try:
                notion.pages.create(
                    parent={"database_id": page_id},
                    properties={}
                )
                return True
            except Exception as e2:
                print(f"Final Notion error: {e2}")
                return False

def send_telegram_message(chat_id, text):
    """Send a message back to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, json=data)
    if not response.ok:
        print(f"Telegram error: {response.text}")

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming Telegram messages"""
    try:
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
                # Analyze message (will use Claude if available, otherwise basic)
                if ANTHROPIC_AVAILABLE:
                    analysis = analyze_with_claude(text)
                else:
                    analysis = basic_categorization(text)
                
                # Process each item
                success_count = 0
                responses = []
                
                for item in analysis['items']:
                    if add_to_notion(item['text'], item['category']):
                        success_count += 1
                        category_name = item['category'].replace('_', ' ').title()
                        emoji = {
                            "todo": "📝",
                            "shopping": "🛒",
                            "projects": "💼",
                            "personal": "👤",
                            "brain_dump": "🧠"
                        }.get(item['category'], "📌")
                        responses.append(f"{emoji} {category_name}: {item['text']}")
                    else:
                        responses.append(f"❌ Failed: {item['text']}")
                
                # Send response
                response_text = "\n".join(responses)
                if success_count == len(analysis['items']):
                    response_text += "\n\n✅ All items added successfully!"
                elif success_count > 0:
                    response_text += f"\n\n⚠️ Added {success_count}/{len(analysis['items'])} items"
                
                # Add mode indicator
                if not ANTHROPIC_AVAILABLE:
                    response_text += "\n\n_📊 Using basic categorization_"
                
                send_telegram_message(chat_id, response_text)
    except Exception as e:
        print(f"Webhook error: {e}")
    
    return jsonify({"status": "ok"})

@app.route('/')
def home():
    mode = "with Claude AI 🤖" if ANTHROPIC_AVAILABLE else "in basic mode 📊"
    return f"Brain Dump Bot is running {mode}!"

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "anthropic_available": ANTHROPIC_AVAILABLE,
        "notion_configured": bool(os.environ.get("NOTION_API_KEY")),
        "telegram_configured": bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
