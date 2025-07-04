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
OPENROUTER_API_KEY = os.getenv('OPENROUTER_API_KEY')
NOTION_API_KEY = os.getenv('NOTION_API_KEY')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
AUTHORIZED_CHAT_ID = os.getenv('AUTHORIZED_CHAT_ID')  # Your Telegram chat ID

class BrainDumpProcessor:
    def __init__(self):
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.notion_url = "https://api.notion.com/v1/pages"
        
    def process_with_claude(self, message: str) -> Dict[str, Any]:
        """Send message to Claude for processing and categorization"""
        
        prompt = f"""
        You are helping organize a brain dump message. Please analyze this message and extract:
        1. Main tasks or action items
        2. Ideas or thoughts to remember
        3. Categories/tags that would be useful
        4. Priority level (High/Medium/Low)
        5. Any deadlines or time-sensitive items
        6. What type of content this is (task, idea, project, personal, work, shopping, etc.)
        
        Message: "{message}"
        
        Please respond in this JSON format:
        {{
            "tasks": ["list of specific tasks"],
            "ideas": ["list of ideas or thoughts"],
            "categories": ["list of relevant categories/tags"],
            "priority": "High/Medium/Low",
            "deadline": "any deadline mentioned or null",
            "content_type": "task/idea/project/personal/work/shopping/general",
            "cleaned_summary": "a clean, organized summary of the content"
        }}
        """
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "anthropic/claude-3-sonnet",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1000,
            "temperature": 0.3
        }
        
        try:
            response = requests.post(self.openrouter_url, headers=headers, json=data)
            response.raise_for_status()
            
            result = response.json()
            claude_response = result['choices'][0]['message']['content']
            
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
                    "tasks": [message] if any(word in message.lower() for word in ['need', 'buy', 'do', 'call', 'remember']) else [],
                    "ideas": [],
                    "categories": ["General"],
                    "priority": "Medium",
                    "deadline": None,
                    "content_type": "general",
                    "cleaned_summary": message
                }
                
        except Exception as e:
            logger.error(f"Error processing with Claude: {e}")
            return {
                "tasks": [message],
                "ideas": [],
                "categories": ["General"],
                "priority": "Medium",
                "deadline": None,
                "content_type": "general",
                "cleaned_summary": message
            }
    
    def add_to_notion(self, processed_data: Dict[str, Any], original_message: str) -> bool:
        """Add processed data to Notion database"""
        
        headers = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
        # Create properties for the Notion page
        properties = {
            "Title": {
                "title": [
                    {
                        "text": {
                            "content": processed_data.get('cleaned_summary', original_message)[:100]
                        }
                    }
                ]
            },
            "Original Message": {
                "rich_text": [
                    {
                        "text": {
                            "content": original_message
                        }
                    }
                ]
            },
            "Tasks": {
                "rich_text": [
                    {
                        "text": {
                            "content": "\n".join(processed_data.get('tasks', []))
                        }
                    }
                ]
            },
            "Ideas": {
                "rich_text": [
                    {
                        "text": {
                            "content": "\n".join(processed_data.get('ideas', []))
                        }
                    }
                ]
            },
            "Categories": {
                "multi_select": [
                    {"name": cat} for cat in processed_data.get('categories', [])
                ]
            },
            "Content Type": {
                "select": {
                    "name": processed_data.get('content_type', 'general').title()
                }
            },
            "Priority": {
                "select": {
                    "name": processed_data.get('priority', 'Medium')
                }
            },
            "Created": {
                "date": {
                    "start": datetime.now().isoformat()
                }
            }
        }
        
        # Add deadline if present
        if processed_data.get('deadline'):
            properties["Deadline"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": processed_data['deadline']
                        }
                    }
                ]
            }
        
        data = {
            "parent": {
                "page_id": NOTION_DATABASE_ID  # Using as page ID now, not database ID
            },
            "properties": {
                "title": [
                    {
                        "text": {
                            "content": processed_data.get('cleaned_summary', original_message)[:100]
                        }
                    }
                ]
            },
            "children": [
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "Original Message"
                                }
                            }
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": original_message
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
                                    "content": "Tasks"
                                }
                            }
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "\n".join(processed_data['tasks'])
                                }
                            }
                        ]
                    }
                }
            ])
        
        # Add ideas if present
        if processed_data.get('ideas'):
            data["children"].extend([
                {
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "Ideas"
                                }
                            }
                        ]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": "\n".join(processed_data['ideas'])
                                }
                            }
                        ]
                    }
                }
            ])
        
        # Add metadata
        data["children"].append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": f"Priority: {processed_data.get('priority', 'Medium')} | Type: {processed_data.get('content_type', 'general')} | Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                        }
                    }
                ]
            }
        })
        
        try:
            response = requests.post(self.notion_url, headers=headers, json=data)
            logger.info(f"Notion response status: {response.status_code}")
            logger.info(f"Notion response headers: {response.headers}")
            logger.info(f"Notion response body: {response.text}")
            response.raise_for_status()
            logger.info("Successfully added to Notion")
            return True
            
        except Exception as e:
            logger.error(f"Error adding to Notion: {e}")
            logger.error(f"Request data was: {json.dumps(data, indent=2)}")
            return False

# Initialize processor
processor = BrainDumpProcessor()

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
            content_type = processed_data.get('content_type', 'general')
            send_telegram_message(chat_id, f"✅ Brain dump processed and added to Notion! (Type: {content_type})")
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

@app.route('/', methods=['GET'])
def root():
    """Root endpoint"""
    return jsonify({"message": "Brain Dump Bot is running!", "status": "ok"}), 200

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

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
