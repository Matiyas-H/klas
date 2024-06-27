from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
import os
from dotenv import load_dotenv
from requests.packages.urllib3.util.retry import Retry
import logging
from cachetools import TTLCache, cached
from time import time
import threading
import json
import base64
import urllib.parse


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

logger.info("Starting application")
SERVER_SECRET = os.getenv('SERVER_SECRET')
TEXTBACK_API_URL = os.getenv('TEXTBACK_API_URL')
TEXTBACK_API_TOKEN = os.getenv('TEXTBACK_API_TOKEN')
TEXTBACK_API_SECRET = os.getenv('TEXTBACK_API_SECRET')
TRACKDRIVE_PUBLIC_KEY = os.getenv('TRACKDRIVE_PUBLIC_KEY')
TRACKDRIVE_PRIVATE_KEY = os.getenv('TRACKDRIVE_PRIVATE_KEY')

logger.info("Loaded environment variables")

session = requests.Session()
retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1
)

adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=100)
session.mount('http://', adapter)
session.mount('https://', adapter)
cache = TTLCache(maxsize=1000, ttl=86400)

logger.info("Configured session and cache")

@app.route('/handle_incoming_call', methods=['POST'])
def handle_incoming_call():
    logger.info("Received request at /handle_incoming_call")
    data = request.json
    logger.info(f"Incoming Request Data: {json.dumps(data, indent=2)}")
    logger.info(f"Headers: {dict(request.headers)}")

    received_secret = request.headers.get('X-Vapi-Secret')
    logger.info(f"Received Secret: {'*' * len(received_secret) if received_secret else 'None'}")

    if received_secret != SERVER_SECRET:
        logger.warning("Secret mismatch. Access denied.")
        abort(403) 

    message_type = data.get('message', {}).get('type')
    logger.info(f"Message Type: {message_type}")

    call_data = data.get('message', {}).get('call', {})
    td_uuid = call_data.get('td_uuid')
    category = call_data.get('category')
    subdomain = call_data.get('subdomain')

    logger.info(f"Captured call data - TD_UUID: {td_uuid}, Category: {category}, Subdomain: {subdomain}")

    if message_type == 'assistant-request':
        logger.info("Handling assistant-request")
        response = {
            "assistant": {
                "firstMessage": "Hello, this is Jessica Miller from the Hardship Debt Relief program. how are you today?",
                "model": {
                    "provider": "openai",
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an experienced lead qualifier for a hardship debt relief program. Your primary goal is to qualify callers for the program efficiently and empathetically. Follow these instructions strictly:"
                        }
                    ],
                    "functions": [
                        {
                            "name": "extractCallerInfo",
                            "description": "Extracts the caller's information for personalization.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "td_uuid": {"type": "string", "description": "Unique Call ID from TrackDrive"},
                                    "category": {"type": "string", "description": "Type of call (inbound, outbound, or scheduled_callback)"},
                                    "subdomain": {"type": "string", "description": "Subdomain for TrackDrive API calls"},
                                    "from": {"type": "string", "description": "Caller's phone number"}
                                },
                                "required": ["td_uuid", "category", "subdomain", "from"]
                            }
                        },
                        {
                            "name": "sendFinancialDetails",
                            "description": "Sends collected financial details to the server.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "debtAmount": {"type": "number", "description": "Total amount of debt."},
                                    "debtType": {"type": "string", "description": "Type of debt (e.g., credit card, student loan)."},
                                    "monthlyIncome": {"type": "number", "description": "Monthly income of the caller."},
                                    "hasCheckingAccount": {"type": "boolean", "description": "Whether the caller has a checking account."},
                                    "employmentStatus": {"type": "string", "description": "Current employment status."},
                                    "subdomain": {"type": "string", "description": "Subdomain for TrackDrive API calls"}
                                },
                                "required": ["debtAmount", "debtType", "monthlyIncome", "hasCheckingAccount", "employmentStatus", "subdomain"]
                            }
                        },
                        {
                            "name": "sendKeypress",
                            "description": "Sends a keypress to TrackDrive.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "td_uuid": {"type": "string", "description": "Unique Call ID from TrackDrive"},
                                    "keypress": {"type": "string", "description": "Keypress to send (e.g., '*', '#', '6', '7', '8', '9', '0')"},
                                    "subdomain": {"type": "string", "description": "Subdomain for TrackDrive API calls"}
                                },
                                "required": ["td_uuid", "keypress", "subdomain"]
                            }
                        }
                    ]
                }
            }
        }
        logger.info("Sending assistant-request response")
        return jsonify(response), 200

    elif message_type == 'function-call':
        logger.info("Handling function-call")
        function_call = data.get('message', {}).get('functionCall', {})
        function_name = function_call.get('name')
        parameters = function_call.get('parameters')
        logger.info(f"Function Name: {function_name}")
        logger.info(f"Parameters: {json.dumps(parameters, indent=2)}")

        if function_name == 'extractCallerInfo':
            return handle_extract_caller_info(data, td_uuid, category, subdomain)
        elif function_name == 'sendFinancialDetails':
            return handle_send_financial_details(parameters, td_uuid, subdomain)
        elif function_name == 'sendKeypress':
            financial_data = parameters.get('financial_data', {})  
            return send_trackdrive_keypress(parameters, td_uuid, subdomain, financial_data)
        else:
            logger.warning(f"Unknown function name: {function_name}")
            return jsonify({"error": f"Unknown function: {function_name}"}), 400

    else:
        logger.warning(f"Invalid request type: {message_type}")
        return jsonify({"error": "Invalid request"}), 400

def handle_extract_caller_info(data, td_uuid, category, subdomain):
    logger.info(f"Handling extractCallerInfo - TD_UUID: {td_uuid}, Category: {category}, Subdomain: {subdomain}")
    call_object = data.get('message', {}).get('call', {})
    from_number = call_object.get('customer', {}).get('number')
    call_sid = call_object.get('phoneCallProviderId')

    logger.info(f"Received call from {from_number} with CallSid {call_sid}")

    if not from_number:
        logger.warning("No valid phone number provided")
        return jsonify({"error": "No valid phone number provided"}), 400

    caller_info = get_contact_info(from_number)
    logger.info(f"Processed caller info: {json.dumps(caller_info, indent=2)}")

    if caller_info:
        first_name = caller_info.get('firstName', '')
        last_name = caller_info.get('lastName', '')
        state = caller_info.get('state', '')
        
        if first_name or last_name:
            personalized_message = f"Hi {first_name} {last_name}"
            if state:
                personalized_message += f" from {state}"
            personalized_message += ", how can I assist you today?"
        else:
            personalized_message = "Hello, how can I assist you today?"

        response = {
            "result": {
                "personalized_message": personalized_message,
                "caller_info": caller_info,
                "td_uuid": td_uuid,
                "category": category,
                "subdomain": subdomain
            }
        }
        logger.info(f"Returning personalized response: {json.dumps(response, indent=2)}")
        return jsonify(response), 200
    else:
        logger.warning(f"No caller info found for: {from_number}")
        response = {
            "result": {
                "message": f"Unable to personalize greeting for: {from_number}",
                "caller": from_number,
                "td_uuid": td_uuid,
                "category": category,
                "subdomain": subdomain
            }
        }
        return jsonify(response), 200
  

def handle_send_financial_details(parameters, td_uuid, subdomain):
    logger.info(f"Handling sendFinancialDetails - TD_UUID: {td_uuid}, Subdomain: {subdomain}")
    financial_data = {
        "debtAmount": parameters.get('debtAmount'),
        "debtType": parameters.get('debtType'),
        "monthlyIncome": parameters.get('monthlyIncome'),
        "hasCheckingAccount": parameters.get('hasCheckingAccount'),
        "employmentStatus": parameters.get('employmentStatus')
    }

    logger.info(f"Received financial data: {json.dumps(financial_data, indent=2)}")

    # Immediately send keypress and financial data
    success = send_trackdrive_keypress(td_uuid, '*', subdomain, financial_data)
    
    if success:
        logger.info(f"Keypress '*' and financial data sent successfully for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "success", 
            "message": "Financial data received and keypress sent",
            "data_sent": True
        }), 200
    else:
        logger.warning(f"Failed to send keypress '*' and financial data for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "error", 
            "message": "Failed to send keypress and financial data",
            "data_sent": False
        }), 500


def qualify_lead(financial_data):
    logger.info("Qualifying lead")
    is_qualified = (
        financial_data['debtAmount'] >= 10000 and
        financial_data['monthlyIncome'] >= 1500 and
        financial_data['hasCheckingAccount'] == True
    )
    logger.info(f"Lead qualification result: {is_qualified}")
    return is_qualified

def handle_send_keypress(parameters, td_uuid, subdomain, financial_data=None):
    logger.info(f"Handling sendKeypress - TD_UUID: {td_uuid}, Subdomain: {subdomain}")
    keypress = parameters.get('keypress')
    logger.info(f"TD_UUID: {td_uuid}, Keypress: {keypress}")

    if not td_uuid or not subdomain:
        logger.error("Missing required parameters: td_uuid or subdomain")
        return jsonify({"status": "error", "message": "Missing required parameters"}), 400

    success = send_trackdrive_keypress(td_uuid, keypress, subdomain, financial_data)
    if success:
        logger.info(f"Keypress {keypress} and financial data sent successfully for call {td_uuid}")
        return jsonify({"status": "success", "message": f"Keypress {keypress} and financial data sent for call {td_uuid}"}), 200
    else:
        logger.error(f"Failed to send keypress {keypress} and financial data for call {td_uuid}")
        return jsonify({"status": "error", "message": "Failed to send keypress and financial data"}), 500



@cached(cache)
def get_contact_info(phone_number):
    logger.info(f"Getting contact info for phone number: {phone_number}")
    
    base_url = "https://api.textback.ai/api/v2/contact/findPhone"
    
    # Ensure the phone number is in the correct format (with '+' sign)
    formatted_phone = phone_number if phone_number.startswith('+') else f'+{phone_number}'
    
    # URL encode the phone number
    encoded_phone = urllib.parse.quote(formatted_phone)
    
    url = f"{base_url}?phone={encoded_phone}"
    
    headers = {
        'accept': 'application/json',
        'token': TEXTBACK_API_TOKEN,
        'secret': TEXTBACK_API_SECRET
    }
    
    logger.info(f"Making API request to URL: {url}")
    logger.info(f"Headers: {headers}")
    
    try:
        response = session.get(url, headers=headers, timeout=(5, 10))
        logger.info(f"API Response Status Code: {response.status_code}")
        logger.info(f"API Response Content: {response.text}")
        
        response.raise_for_status()
        contact_info = response.json()
        logger.info(f"Retrieved contact info: {json.dumps(contact_info, indent=2)}")
        return contact_info
    except requests.RequestException as e:
        logger.error(f"Failed to get contact info: {str(e)}")
        return None

import base64

def send_trackdrive_keypress(td_uuid, keypress, subdomain, financial_data=None):
    logger.info(f"Attempting to send TrackDrive keypress and data. TD_UUID: {td_uuid}, Keypress: {keypress}, Subdomain: {subdomain}")
    url = f"https://{subdomain}.trackdrive.com/api/v1/calls/send_key_press"
    
    # Combine and encode the public and private keys
    auth_string = f"{TRACKDRIVE_PUBLIC_KEY}:{TRACKDRIVE_PRIVATE_KEY}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {encoded_auth}"
    }
    
    payload = {
        "id": td_uuid,
        "digits": keypress
    }
    if financial_data:
        payload["data"] = financial_data

    try:
        logger.info(f"Sending POST request to TrackDrive API. URL: {url}, Payload: {json.dumps(payload)}")
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"TrackDrive API response: Status Code {response.status_code}, Content: {response.text}")
        logger.info(f"Keypress and data sent successfully for TD_UUID: {td_uuid}")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send keypress and data: {str(e)}")
        return False

if __name__ == '__main__':
    logger.info("Starting cache refresh thread")
    # cache_refresh_thread = threading.Thread(target=refresh_cache, daemon=True)
    # cache_refresh_thread.start()
    logger.info("Starting Flask application")
    app.run(debug=True, port=5000)

if __name__ == '__main__':
    logger.info("Starting cache refresh thread")
    # cache_refresh_thread = threading.Thread(target=refresh_cache, daemon=True)
    # cache_refresh_thread.start()
    logger.info("Starting Flask application")
    app.run(debug=True, port=5000)