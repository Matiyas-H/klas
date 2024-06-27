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



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

logger.info("Starting application")

SERVER_SECRET = "s3cr3tK3yExAmpl3SecReT"
TEXTBACK_API_URL = "https://api.textback.ai/swagger-ui/index.html#/contact-resource/findPhoneForUser"
TEXTBACK_API_TOKEN = "QJ0fzQzwBlx2DfqfRZpopS2NPYoQV7nE"
TEXTBACK_API_SECRET = "PfVq2I-5Js4="
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
                "firstMessage": "Hi, thanks for calling in. My name is Jessica Miller. How can I assist you today?",
                "model": {
                    "provider": "openai",
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a helpful assistant. When a call is received, trigger the extractCallerInfo function and use the extracted information to personalize the conversation. Do not ask for the phone number, you have it already"
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

    # Implement qualification logic
    is_qualified = qualify_lead(financial_data)
    logger.info(f"Is qualified: {is_qualified}")

    if is_qualified:
        logger.info("Caller is qualified. Attempting to send keypress and financial data.")
        if td_uuid:
            logger.info(f"Attempting to send keypress '*' and financial data for TD_UUID: {td_uuid}")
            success = handle_send_keypress(td_uuid, '*', subdomain, financial_data)
            if success:
                logger.info(f"Keypress '*' and financial data sent successfully for TD_UUID: {td_uuid}")
                return jsonify({
                    "status": "success", 
                    "message": "Caller is qualified, keypress and financial data sent",
                    "qualified": True,
                    "data_sent": True
                }), 200
            else:
                logger.warning(f"Failed to send keypress '*' and financial data for TD_UUID: {td_uuid}")
                return jsonify({
                    "status": "partial_success", 
                    "message": "Caller is qualified but failed to send keypress and financial data",
                    "qualified": True,
                    "data_sent": False
                }), 200
        else:
            logger.warning("Caller is qualified but td_uuid is missing. Cannot send data.")
            return jsonify({
                "status": "partial_success", 
                "message": "Caller is qualified but td_uuid is missing",
                "qualified": True,
                "data_sent": False
            }), 200
    else:
        logger.info("Caller is not qualified. No data will be sent.")
        return jsonify({
            "status": "success", 
            "message": "Caller is not qualified",
            "qualified": False,
            "data_sent": False
        }), 200


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



# import logging
# from flask import Flask, request, jsonify, abort
# import requests
# from requests.adapters import HTTPAdapter
# import os
# from dotenv import load_dotenv
# from requests.packages.urllib3.util.retry import Retry
# from cachetools import TTLCache, cached
# from time import time
# import threading
# import json

# # Configure logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# load_dotenv()
# app = Flask(__name__)

# logger.info("Starting application")

# SERVER_SECRET = "s3cr3tK3yExAmpl3SecReT"
# TEXTBACK_API_URL = "QJ0fzQzwBlx2DfqfRZpopS2NPYoQV7nE"
# TEXTBACK_API_TOKEN = "QJ0fzQzwBlx2DfqfRZpopS2NPYoQV7nE"
# TEXTBACK_API_SECRET = "PfVq2I-5Js4="
# TRACKDRIVE_API_URL = os.getenv('TRACKDRIVE_API_URL')
# TRACKDRIVE_API_KEY = os.getenv('TRACKDRIVE_API_KEY')

# logger.info(f"Loaded environment variables. SERVER_SECRET: {'*' * len(SERVER_SECRET)}")

# session = requests.Session()
# retry_strategy = Retry(
#     total=3,
#     status_forcelist=[429, 500, 502, 503, 504],
#     allowed_methods=["HEAD", "GET", "OPTIONS"],
#     backoff_factor=1
# )

# adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=100)
# session.mount('http://', adapter)
# session.mount('https://', adapter)
# cache = TTLCache(maxsize=1000, ttl=86400)

# logger.info("Configured session and cache")

# @app.route('/handle_incoming_call', methods=['POST'])
# def handle_incoming_call():
#     logger.info("Received request at /handle_incoming_call")
#     data = request.json
#     logger.info(f"Incoming Request Data: {json.dumps(data, indent=2)}")
#     logger.info(f"Headers: {dict(request.headers)}")

#     received_secret = request.headers.get('X-Vapi-Secret')
#     logger.info(f"Received Secret: {'*' * len(received_secret) if received_secret else 'None'}")

#     if received_secret != SERVER_SECRET:
#         logger.warning("Secret mismatch. Access denied.")
#         abort(403)

#     message_type = data.get('message', {}).get('type')
#     logger.info(f"Message Type: {message_type}")

#     if message_type == 'assistant-request':
#         logger.info("Handling assistant-request")
#         response = {
#             "assistant": {
#                 "firstMessage": "Hi, thanks for calling in. My name is Jessica Miller. How are you today?",
#                 "model": {
#                     "provider": "openai",
#                     "model": "gpt-3.5-turbo",
#                     "messages": [
#                         {
#                             "role": "system",
#                             "content": "You are Jessica Miller, an AI assistant for a debt relief company. Your goal is to qualify callers for a program that could erase up to 40% of their debts. When a call is received, immediately trigger the extractCallerInfo function and use the extracted information to personalize the conversation. Follow the qualification process strictly, asking about debt amount, monthly income, checking account, debt types, state of residence, and total debt amount. Collect financial details and use the sendFinancialDetails function when the caller qualifies. If the caller qualifies and agrees to transfer, use the sendKeypress function. Maintain a friendly, professional, and empathetic demeanor throughout the call."
#                         }
#                     ],
#                     "functions": [
#                         {
#                             "name": "extractCallerInfo",
#                             "description": "Extracts the caller's information for personalization.",
#                             "parameters": {
#                                 "type": "object",
#                                 "properties": {
#                                     "td_uuid": {"type": "string", "description": "Unique Call ID from TrackDrive"},
#                                     "caller_id": {"type": "string", "description": "Caller's phone number from TrackDrive"},
#                                     "from": {"type": "string", "description": "Caller's phone number from Twilio"},
#                                     "callSid": {"type": "string", "description": "Twilio Call SID"},
#                                     "category": {"type": "string", "description": "Type of call (inbound, outbound, or scheduled_callback)"},
#                                     "schedule_id": {"type": "string", "description": "ID for scheduled callbacks"}
#                                 },
#                                 "required": ["td_uuid", "category"]
#                             }
#                         },
#                         {
#                             "name": "sendFinancialDetails",
#                             "description": "Sends collected financial details to the server.",
#                             "parameters": {
#                                 "type": "object",
#                                 "properties": {
#                                     "debtAmount": {"type": "number", "description": "Total amount of debt."},
#                                     "debtType": {"type": "string", "description": "Type of debt (e.g., credit card, student loan)."},
#                                     "monthlyIncome": {"type": "number", "description": "Monthly income of the caller."},
#                                     "hasCheckingAccount": {"type": "boolean", "description": "Whether the caller has a checking account."},
#                                     "employmentStatus": {"type": "string", "description": "Current employment status."}
#                                 },
#                                 "required": ["debtAmount", "debtType", "monthlyIncome", "hasCheckingAccount", "employmentStatus"]
#                             }
#                         },
#                         {
#                             "name": "sendKeypress",
#                             "description": "Sends a keypress to TrackDrive.",
#                             "parameters": {
#                                 "type": "object",
#                                 "properties": {
#                                     "td_uuid": {"type": "string", "description": "Unique Call ID from TrackDrive"},
#                                     "keypress": {"type": "string", "description": "Keypress to send (e.g., '*', '#', '6', '7', '8', '9', '0')"}
#                                 },
#                                 "required": ["td_uuid", "keypress"]
#                             }
#                         }
#                     ]
#                 }
#             }
#         }
#         logger.info("Sending assistant-request response")
#         return jsonify(response), 200

#     elif message_type == 'function-call':
#         logger.info("Handling function-call")
#         function_call = data.get('message', {}).get('functionCall', {})
#         function_name = function_call.get('name')
#         parameters = function_call.get('parameters')
#         logger.info(f"Function Name: {function_name}")
#         logger.info(f"Parameters: {json.dumps(parameters, indent=2)}")

#         if function_name == 'extractCallerInfo':
#             return handle_extract_caller_info(data, parameters)
#         elif function_name == 'sendFinancialDetails':
#             return handle_send_financial_details(parameters)
#         elif function_name == 'sendKeypress':
#             return handle_send_keypress(parameters)

#     logger.warning(f"Invalid request type: {message_type}")
#     return jsonify({"error": "Invalid request"}), 400

# def handle_extract_caller_info(data, parameters):
#     logger.info("Handling extractCallerInfo")
#     td_uuid = parameters.get('td_uuid')
#     caller_id = parameters.get('caller_id')
#     from_number = parameters.get('from')
#     category = parameters.get('category')

#     logger.info(f"Extracting caller info. TD_UUID: {td_uuid}, Caller ID: {caller_id}, From: {from_number}, Category: {category}")

#     if not caller_id:
#         call_object = data.get('message', {}).get('call', {})
#         caller_id = call_object.get('customer', {}).get('number')
#         logger.info(f"Caller ID from call object: {caller_id}")

#     phone_number = caller_id or from_number

#     if not phone_number:
#         logger.warning("No valid phone number provided")
#         return jsonify({"error": "No valid phone number provided"}), 400

#     logger.info(f"Using phone number: {phone_number}")

#     caller_info = get_contact_info(phone_number)
#     logger.info(f"Caller info retrieved: {json.dumps(caller_info, indent=2)}")

#     if caller_info:
#         first_name = caller_info.get('fName', [''])[0]
#         last_name = caller_info.get('lName', [''])[0]
#         state = caller_info.get('stateCode', [''])[0]
#         personalized_message = f"Hi {first_name} {last_name} from {state}, how can I assist you today?"

#         response = {
#             "result": {
#                 "personalized_message": personalized_message
#             }
#         }
#         logger.info(f"Returning personalized message: {personalized_message}")
#         return jsonify(response), 200
#     else:
#         response = {
#             "result": {
#                 "message": f"Failed to extract caller information for: {phone_number}",
#                 "caller": phone_number
#             }
#         }
#         logger.warning(f"Failed to get caller info for: {phone_number}")
#         return jsonify(response), 500

# def handle_send_financial_details(parameters):
#     logger.info("Handling sendFinancialDetails")
#     financial_data = {
#         "debtAmount": parameters.get('debtAmount'),
#         "debtType": parameters.get('debtType'),
#         "monthlyIncome": parameters.get('monthlyIncome'),
#         "hasCheckingAccount": parameters.get('hasCheckingAccount'),
#         "employmentStatus": parameters.get('employmentStatus')
#     }
#     td_uuid = parameters.get('td_uuid')

#     logger.info(f"Received financial data: {json.dumps(financial_data, indent=2)}")
#     logger.info(f"TD_UUID: {td_uuid}")

#     is_qualified = qualify_lead(financial_data)
#     logger.info(f"Is qualified: {is_qualified}")

#     if is_qualified:
#         if td_uuid:
#             success = send_trackdrive_keypress(td_uuid, '*')
#             if success:
#                 logger.info("Caller is qualified and keypress sent")
#                 return jsonify({
#                     "status": "success", 
#                     "message": "Caller is qualified and keypress sent",
#                     "qualified": True,
#                     "keypress_sent": True
#                 }), 200
#             else:
#                 logger.warning("Caller is qualified but failed to send keypress")
#                 return jsonify({
#                     "status": "partial_success", 
#                     "message": "Caller is qualified but failed to send keypress",
#                     "qualified": True,
#                     "keypress_sent": False
#                 }), 200
#         else:
#             logger.warning("Caller is qualified but td_uuid is missing")
#             return jsonify({
#                 "status": "partial_success", 
#                 "message": "Caller is qualified but td_uuid is missing",
#                 "qualified": True,
#                 "keypress_sent": False
#             }), 200
#     else:
#         logger.info("Caller is not qualified")
#         return jsonify({
#             "status": "success", 
#             "message": "Caller is not qualified",
#             "qualified": False,
#             "keypress_sent": False
#         }), 200

# def qualify_lead(financial_data):
#     logger.info("Qualifying lead")
#     is_qualified = (
#         financial_data['debtAmount'] >= 10000 and
#         financial_data['monthlyIncome'] >= 2000 and
#         financial_data['hasCheckingAccount'] == True
#     )
#     logger.info(f"Lead qualification result: {is_qualified}")
#     return is_qualified

# def send_trackdrive_keypress(td_uuid, keypress):
#     logger.info(f"Sending TrackDrive keypress. TD_UUID: {td_uuid}, Keypress: {keypress}")
#     url = f"{TRACKDRIVE_API_URL}/api/v1/calls/send_key_press"
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Token {TRACKDRIVE_API_KEY}"
#     }
#     payload = {
#         "id": td_uuid,
#         "digits": keypress
#     }
#     try:
#         response = requests.post(url, headers=headers, json=payload)
#         response.raise_for_status()
#         logger.info(f"Keypress sent successfully for TD_UUID: {td_uuid}")
#         return True
#     except requests.RequestException as e:
#         logger.error(f"Failed to send keypress: {str(e)}")
#         return False
    
# def handle_send_keypress(parameters):
#     logger.info("Handling sendKeypress")
#     td_uuid = parameters.get('td_uuid')
#     keypress = parameters.get('keypress')
#     logger.info(f"TD_UUID: {td_uuid}, Keypress: {keypress}")

#     success = send_trackdrive_keypress(td_uuid, keypress)
#     if success:
#         logger.info(f"Keypress {keypress} sent successfully for call {td_uuid}")
#         return jsonify({"status": "success", "message": f"Keypress {keypress} sent for call {td_uuid}"}), 200
#     else:
#         logger.error(f"Failed to send keypress {keypress} for call {td_uuid}")
#         return jsonify({"status": "error", "message": "Failed to send keypress"}), 500

# @cached(cache)
# def get_contact_info(phone_number):
#     logger.info(f"Getting contact info for phone number: {phone_number}")
#     headers = {
#         'accept': 'application/json',
#         'token': TEXTBACK_API_TOKEN,
#         'secret': TEXTBACK_API_SECRET
#     }
#     params = {
#         'phone': phone_number
#     }
#     try:
#         response = session.get(TEXTBACK_API_URL, headers=headers, params=params, timeout=(5, 10)) 
#         response.raise_for_status()
#         contact_info = response.json().get('info', {})
#         logger.info(f"Retrieved contact info: {json.dumps(contact_info, indent=2)}")
#         return contact_info
#     except requests.RequestException as e:
#         logger.error(f"Failed to get contact info: {str(e)}")
#         return None

# # def refresh_cache():
#     # logger.info("Starting cache refresh")
#     # while True:
#     #     for phone_number in list(cache.keys()):
#     #         logger.info(f"Refreshing cache for phone number: {phone_number}")
#     #         get_contact_info(phone_number)
#     #     logger.info("Cache refresh complete. Sleeping for 24 hours.")
#         # time.sleep(86400)  # Refresh cache every 24 hours

# if __name__ == '__main__':
#     logger.info("Starting cache refresh thread")
#     # cache_refresh_thread = threading.Thread(target=refresh_cache, daemon=True)
#     # cache_refresh_thread.start()
#     logger.info("Starting Flask application")
#     app.run(debug=True, port=5000)