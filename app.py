import os
import json
import requests
import logging
from datetime import datetime
from typing import Dict, Any, List
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration from environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
AUTHORIZED_CHAT_ID = os.getenv('AUTHORIZED_CHAT_ID')

# Page IDs for smart routing
NOTION_PAGES = {
    'tasks': os.getenv('NOTION_TODO_PAGE'),
    'shopping': os.getenv('NOTION_SHOPPING_PAGE'),
    'projects': os.getenv('NOTION_PROJECTS_PAGE'),
    'ideas': os.getenv('NOTION_BRAIN_DUMP_PAGE'),
    'personal': os.getenv('NOTION_PERSONAL_PAGE'),
    'general': os.getenv('NOTION_BRAIN_DUMP_PAGE')  # Fallback
}

class BrainDumpProcessor:
    def __init__(self):
        self.anthropic_url = "https://api.anthropic.com/v1/messages"
        self.notion_url = "https://api.notion.com/v1/pages"
        
    def process_with_claude(self, message: str) -> Dict[str, Any]:
        """Send message to Claude for processing and categorization"""
        
        prompt = f"""
        You are helping organize a brain dump message. Analyze this message and determine which category it belongs in:

        Available categories:
        - tasks: Action items, todos, things to do, reminders
        - shopping: Things to buy, purchases, supplies, grocery items
        - projects: Work projects, ongoing initiatives, big goals
        - ideas: Creative thoughts, concepts, inspiration, random ideas
        - personal: Family, relationships, personal life, self-improvement
        - general: Everything else that doesn't fit above

        Message: "{message}"
        
        Please respond in this JSON format:
        {{
            "category": "tasks/shopping/projects/ideas/personal/general",
            "title": "Short descriptive title for the entry",
            "tasks": ["specific action items if any"],
            "ideas": ["thoughts or concepts if any"],
            "priority": "High/Medium/Low",
            "deadline": "any deadline mentioned or null",
            "cleaned_summary": "a clean, organized summary"
        }}
        """
        
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": "claude-3-sonnet-20240229",
            "max_tokens": 1000,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        try:
            response = requests.post(self.anthropic_url, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            claude_response = result['content'][0]['text']
            
            # Try to extract JSON from Claude's response
            try:
                # Look for JSON in the response
                start = claude_response.find('{')
                end = claude_response.rfind('}') + 1
                json_str = claude_response[start:end]
                return json.loads(json_str)
            except:
                # Fallback if JSON parsing fails
                return {
                    "category": "general",
                    "title": message[:50],
                    "tasks": [message] if any(word in message.lower() for word in ['need', 'buy', 'do', 'call', 'remember']) else [],
                    "ideas": [],
                    "priority": "Medium",
                    "deadline": None,
                    "cleaned_summary": message
                }
                
        except Exception as e:
            logger.error(f"Error processing with Claude: {e}")
            return {
                "category": "general",
                "title": message[:50],
                "tasks": [message],
                "ideas": [],
                "priority": "Medium",
                "deadline": None,
                "cleaned_summary": message
            }
    
    def add_to_notion(self, processed_data: Dict[str, Any], original_message: str) -> bool:
        """Add processed data to appropriate Notion page"""
        
        # Determine which page to use
        category = processed_data.get('category', 'general')
        page_id = NOTION_PAGES.get(category)
        
        if not page_id:
            # Fallback to general page
            page_id = NOTION_PAGES.get('general')
            if not page_id:
                logger.error("No pages configured!")
                return False
        
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        data = {
            "parent": {
                "page_id": page_id
            },
            "properties": {
                "title": [
                    {
                        "text": {
                            "content": processed_data.get('title', original_message[:100])
                        }
                    }
                ]
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": processed_data.get('cleaned_summary', original_message)
                                }
                            }
                        ]
                    }
                }
            ]
        }
        
        # Add tasks if present
        if processed_data.get('tasks'):
            data["children"].extend([
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "Tasks:"
                                }
                            }
                        ]
                    }
                }
            ])
            for task in processed_data['tasks']:
                data["children"].append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": task
                                }
                            }
                        ],
                        "checked": False
                    }
                })
        
        # Add priority and metadata
        metadata = f"Priority: {processed_data.get('priority', 'Medium')} | Added: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        if processed_data.get('deadline'):
            metadata += f" | Deadline: {processed_data['deadline']}"
            
        data["children"].append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": metadata
                        }
                    }
                ]
            }
        })
        
        try:
            response = requests.post(self.notion_url, headers=headers, json=data)
            logger.info(f"Notion response status: {response.status_code}")
            logger.info(f"Notion response body: {response.text}")
            logger.info(f"Request data sent: {json.dumps(data, indent=2)}")
            response.raise_for_status()
            logger.info(f"Successfully added to Notion page: {category}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding to Notion: {e}")
            logger.error(f"Full request data: {json.dumps(data, indent=2)}")
            return False

# Initialize processor
processor = BrainDumpProcessor()

@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({"message": "Brain Dump Bot is running!", "status": "ok"}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Handle incoming Telegram messages"""
    try:
        data = request.get_json()
        
        # Check if it's a message update
        if 'message' not in data:
            return jsonify({"status": "ignored"}), 200
            
        message = data['message']
        chat_id = str(message['chat']['id'])
        
        # Check if message is from authorized user
        if AUTHORIZED_CHAT_ID and chat_id != AUTHORIZED_CHAT_ID:
            logger.warning(f"Unauthorized message from chat_id: {chat_id}")
            return jsonify({"status": "unauthorized"}), 200
        
        # Get message text
        text = message.get('text', '')
        
        if not text:
            return jsonify({"status": "no_text"}), 200
        
        # Skip commands
        if text.startswith('/'):
            return jsonify({"status": "command_ignored"}), 200
        
        logger.info(f"Processing message: {text[:50]}...")
        
        # Process with Claude
        processed_data = processor.process_with_claude(text)
        
        # Add to Notion
        success = processor.add_to_notion(processed_data, text)
        
        if success:
            # Send confirmation back to Telegram
            category = processed_data.get('category', 'general')
            send_telegram_message(chat_id, f"✅ Added to {category.title()} page!")
            return jsonify({"status": "success"}), 200
        else:
            send_telegram_message(chat_id, "❌ Failed to add to Notion. Check logs.")
            return jsonify({"status": "notion_error"}), 500
            
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

def send_telegram_message(chat_id: str, text: str):
    """Send message back to Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text
    }
    
    try:
        requests.post(url, json=data)
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")

@app.route('/test', methods=['POST'])
def test_endpoint():
    """Test endpoint for manual testing"""
    data = request.get_json()
    message = data.get('message', 'Test message')
    
    processed_data = processor.process_with_claude(message)
    success = processor.add_to_notion(processed_data, message)
    
    return jsonify({
        "processed_data": processed_data,
        "notion_success": success
    }), 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
