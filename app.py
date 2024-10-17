from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
import os
from dotenv import load_dotenv
from urllib3.util.retry import Retry 
import logging
from cachetools import TTLCache, cached
from time import time
import threading
import json
import base64



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
OMNIA_VOICE_API_KEY = os.getenv('OMNIA_VOICE_API_KEY')
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

caller_info_storage = {}

def fetch_omnia_voice_data(phone_number):
    url = "https://api.omnia-voice.com/api/incoming"
    headers = {
        "X-API-Key": OMNIA_VOICE_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "caller_phone_number": phone_number,
        "caller_first_name": "",
        "caller_last_name": ""
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch data from Omnia Voice API: {str(e)}")
        return None


def store_caller_info(td_uuid, phone_number, info):
    key = f"{td_uuid}_{phone_number}"
    caller_info_storage[key] = info
    logger.info(f"Stored caller info for TD_UUID: {td_uuid}, Phone: {phone_number}")

def get_stored_caller_info(td_uuid, phone_number):
    key = f"{td_uuid}_{phone_number}"
    info = caller_info_storage.get(key, {})
    if not info:
        logger.warning(f"No stored caller info found for TD_UUID: {td_uuid}, Phone: {phone_number}")
    return info

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
    td_uuid = call_data.get('id')
    category = call_data.get('category')
    subdomain = call_data.get('subdomain')

    logger.info(f"Captured call data - TD_UUID: {td_uuid}, Category: {category}, Subdomain: {subdomain}")

    if message_type == 'assistant-request':
        logger.info("Handling assistant-request")
        response = {
            "assistant": {
                "firstMessage": "Hello, thank you for calling to Hardship Debt Relief program, and who do I have the pleasure of speaking with? ",
                "model": {
                    "provider": "openai",
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an experienced lead qualifier for a hardship debt relief program. Your primary goal is to qualify callers for the program efficiently and empathetically, YOU MUST START FROM THE MANDATORY INTRODUCTION WE HAVE PROVIDED, IT'S VERY VERY IMPORTANT. Follow these instructions strictly, Call sendFinancialDetails function with collected data, and when the user agreed to transfer. Remember: Do not make any function calls until the very end of the qualification process, and only use sendFinancialDetails when transferring a qualified caller who has agreed to speak with a specialist."
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
                                    "caller_id": {"type": "string", "description": "Caller's phone number from TrackDrive"},
                                    "from": {"type": "string", "description": "Caller's phone number from Twilio"},
                                    "callSid": {"type": "string", "description": "Caller's sid from Twilio"},
                                    "category": {"type": "string", "description": "Type of call (inbound, outbound, or scheduled_callback)"},
                                    "schedule_id": {"type": "string", "description": "ID for scheduled callbacks"}
                                },
                                "required": ["td_uuid", "category"]
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
                                    "employmentStatus": {"type": "string", "description": "Current employment status."}
                                },
                                "required": ["debtAmount", "debtType", "monthlyIncome", "hasCheckingAccount", "employmentStatus"]
                            }
                        },
                        {
                            "name": "sendKeypress",
                            "description": "Sends a keypress to TrackDrive.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "td_uuid": {"type": "string", "description": "Unique Call ID from TrackDrive"},
                                    "keypress": {"type": "string", "description": "Keypress to send (e.g., '*', '#', '6', '7', '8', '9', '0')"}
                                },
                                "required": ["td_uuid", "keypress"]
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
            return handle_send_financial_details(parameters, td_uuid, subdomain, data)
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

    caller_info = get_or_fetch_caller_info(td_uuid, from_number)
    logger.info(f"Processed caller info: {json.dumps(caller_info, indent=2)}")

    # Prepare response
    if caller_info:
        first_name = caller_info.get('firstName', '')
        last_name = caller_info.get('lastName', '')
        state = caller_info.get('state', '')
        
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

def get_or_fetch_caller_info(td_uuid, from_number):
    caller_info = get_stored_caller_info(td_uuid, from_number)
    if not caller_info:
        logger.info(f"No stored caller info found for {from_number}. Fetching from API.")
        caller_info = get_contact_info(from_number)
        if not caller_info:
            logger.info(f"No contact info found. Fetching from Omnia Voice API.")
            caller_info = fetch_omnia_voice_data(from_number)
        
        if caller_info:
            store_caller_info(td_uuid, from_number, caller_info)
        else:
            logger.warning(f"Failed to fetch caller info for {from_number}")
    
    return caller_info

def handle_send_financial_details(parameters, td_uuid, subdomain, data):
    logger.info(f"Handling sendFinancialDetails - TD_UUID: {td_uuid}, Subdomain: {subdomain}")
    financial_data = {
        "debtAmount": parameters.get('debtAmount'),
        "debtType": parameters.get('debtType'),
        "monthlyIncome": parameters.get('monthlyIncome'),
        "hasCheckingAccount": parameters.get('hasCheckingAccount'),
        "alreadyEnrolledAnyOtherProgram": parameters.get('alreadyEnrolledAnyOtherProgram')
    }

    logger.info(f"Received financial data: {json.dumps(financial_data, indent=2)}")

    call_object = data.get('message', {}).get('call', {})
    from_number = call_object.get('customer', {}).get('number')

    if not td_uuid or not from_number:
        logger.error("Missing TD_UUID or phone number. Cannot send financial details.")
        return jsonify({
            "status": "error", 
            "message": "Missing TD_UUID or phone number. Cannot send financial details.",
            "data_sent": False
        }), 400

    caller_info = get_or_fetch_caller_info(td_uuid, from_number)
    
    combined_data = {
        **(caller_info or {}),
        "financial_data": financial_data,
        "td_uuid": td_uuid,
        "phone_number": from_number
    }

    logger.info(f"Attempting to send keypress and financial data for TD_UUID: {td_uuid}, Phone: {from_number}")
    success = send_trackdrive_keypress(td_uuid, '*', subdomain, combined_data)
    if success:
        logger.info(f"Keypress '*' and financial data sent successfully for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "success", 
            "message": "Keypress and financial data sent",
            "data_sent": True
        }), 200
    else:
        logger.warning(f"Failed to send keypress '*' and financial data for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "error", 
            "message": "Failed to send keypress and financial data",
            "data_sent": False
        }), 500



# In the handle_incoming_call function,
def qualify_lead(financial_data):
    logger.info("Qualifying lead")
    is_qualified = (
        financial_data['debtAmount'] >= 10000 and
        financial_data['monthlyIncome'] >= 2000 and
        financial_data['hasCheckingAccount'] == True
    )
    logger.info(f"Lead qualification result: {is_qualified}")
    return is_qualified

def handle_send_keypress(parameters, td_uuid, subdomain, financial_data=None):
    logger.info(f"Handling sendKeypress - TD_UUID: {td_uuid}, Subdomain: {subdomain}")
    keypress = parameters.get('keypress')
    logger.info(f"TD_UUID: {td_uuid}, Keypress: {keypress}")

    if not td_uuid:
        logger.error("Missing TD_UUID. Cannot send keypress.")
        return jsonify({
            "status": "error", 
            "message": "Missing TD_UUID. Cannot send keypress.",
            "data_sent": False
        }), 400

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

import urllib.parse

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

def send_trackdrive_keypress(td_uuid, keypress, subdomain="global-telecom-investors", combined_data=None):
    logger.info(f"Attempting to send TrackDrive keypress and data. TD_UUID: {td_uuid}, Keypress: {keypress}, Subdomain: {subdomain}")
    
    url = f"https://{subdomain}.trackdrive.com/api/v1/calls/send_key_press"
    
    auth_string = f"{TRACKDRIVE_PUBLIC_KEY}:{TRACKDRIVE_PRIVATE_KEY}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {encoded_auth}"
    }

    if not td_uuid:
        logger.error("Missing TD_UUID. Cannot send keypress to TrackDrive.")
        return False
    
    payload = {
        "id": td_uuid,
        "digits": keypress,
    }
    
    if combined_data:
        payload["data"] = combined_data

    try:
        logger.info(f"Sending POST request to TrackDrive API. URL: {url}, Payload: {json.dumps(payload)}")
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"TrackDrive API response: Status Code {response.status_code}, Content: {response.text}")
        logger.info(f"Keypress and data sent successfully for TD_UUID: {td_uuid}")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send keypress and data for TD_UUID: {td_uuid}. Error: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response content: {e.response.content}")
        return False
    



if __name__ == '__main__':
    logger.info("Starting cache refresh thread")
    # cache_refresh_thread = threading.Thread(target=refresh_cache, daemon=True)
    # cache_refresh_thread.start()
    logger.info("Starting Flask application")
    app.run(debug=True, port=5000)
