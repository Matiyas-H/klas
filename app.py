from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
import os
from dotenv import load_dotenv
from requests.packages.urllib3.util.retry import Retry
import logging
from cachetools import TTLCache, cached
from time import time

load_dotenv()
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_SECRET = os.getenv('SERVER_SECRET')

TEXTBACK_API_URL = os.getenv('TEXTBACK_API_URL')
TEXTBACK_API_TOKEN = os.getenv('TEXTBACK_API_TOKEN')
TEXTBACK_API_SECRET = os.getenv('TEXTBACK_API_SECRET')
#added session
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

@app.route('/handle_incoming_call', methods=['POST'])
def handle_incoming_call():
    data = request.json

    print(f"Incoming Request Data: {data}")
    print(f"Headers: {request.headers}")

    received_secret = request.headers.get('X-Vapi-Secret')
    print(f"Received Secret: {received_secret}")

    if received_secret != SERVER_SECRET:
        abort(403) 

    message_type = data.get('message', {}).get('type')

    if message_type == 'assistant-request':
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
                            "description": "Extracts the caller's phone number.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "callSid": {
                                        "type": "string"
                                    },
                                    "from": {
                                        "type": "string"
                                    }
                                },
                                "required": [
                                    "callSid",
                                    "from"
                                ]
                            }
                        }
                    ]
                }
            }
        }
        return jsonify(response), 200

    elif message_type == 'function-call':
        function_call = data.get('message', {}).get('functionCall', {})
        function_name = function_call.get('name')
        parameters = function_call.get('parameters')

        if function_name == 'extractCallerInfo':
            call_object = data.get('message', {}).get('call', {})
            from_number = call_object.get('customer', {}).get('number')
            call_sid = call_object.get('phoneCallProviderId')

            print(f"Received call from {from_number} with CallSid {call_sid}")

            caller_info = get_contact_info(from_number)
            if caller_info:
                first_name = caller_info.get('fName', [''])[0]
                last_name = caller_info.get('lName', [''])[0]
                state = caller_info.get('stateCode', [''])[0]
                personalized_message = f"Hi {first_name} {last_name} from {state}, how can I assist you today?"

                response = {
                    "result": {
                        "personalized_message": personalized_message
                    }
                }
                return jsonify(response), 200
            else:
                response = {
                    "result": {
                        "message": f"Failed to extract caller information for: {from_number}",
                        "caller": from_number
                    }
                }
                return jsonify(response), 500

    return jsonify({"error": "Invalid request"}), 400

@cached(cache)
def get_contact_info(phone_number):
    headers = {
        'accept': 'application/json',
        'token': TEXTBACK_API_TOKEN,
        'secret': TEXTBACK_API_SECRET
    }
    params = {
        'phone': phone_number
    }
    try:
        response = session.get(TEXTBACK_API_URL, headers=headers, params=params, timeout=(5, 10)) 
        response.raise_for_status()  
        return response.json().get('info', {})
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return None

if __name__ == '__main__':
    app.run(debug=True, port=5000)
