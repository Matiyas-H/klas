import datetime
from flask import Flask, request, jsonify, abort
import requests
from requests.adapters import HTTPAdapter
import os
from dotenv import load_dotenv
import logging
from time import time
import threading
import json
import base64
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Add this at the top with other configurations
def create_session_with_retries():
    session = requests.Session()
    retries = Retry(
        total=3,  # number of retries
        backoff_factor=1,  # wait 1, 2, 4 seconds between retries
        status_forcelist=[408, 429, 500, 502, 503, 504],  # retry on these status codes
        allowed_methods=["GET", "POST"]  # allow retries on GET and POST
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

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
TRACKDRIVE_AUTH = os.getenv('TRACKDRIVE_AUTH')
logger.info("Loaded environment variables")





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

    if message_type == 'function-call':
        logger.info("Handling function-call")
        function_call = data.get('message', {}).get('functionCall', {})
        function_name = function_call.get('name')
        parameters = function_call.get('parameters')
        logger.info(f"Function Name: {function_name}")
        logger.info(f"Parameters: {json.dumps(parameters, indent=2)}")

        if function_name == 'sendFinancialDetails':
            return handle_send_financial_details(parameters, None, "global-telecom-investors", data)
        else:
            logger.warning(f"Unknown function name: {function_name}")
            return jsonify({"error": f"Unknown function: {function_name}"}), 400

    else:
        logger.warning(f"Invalid request type: {message_type}")
        return jsonify({"error": "Invalid request"}), 400


def handle_extract_caller_info(data, td_uuid, category, subdomain):
    pass


def fetch_webhook_data(phone_number):
    """Fetch webhook data from API using phone number with retries"""
    session = create_session_with_retries()
    
    try:
        headers = {
            "X-API-Key": OMNIA_VOICE_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "caller_phone_number": phone_number,
            "caller_first_name": "",
            "caller_last_name": ""
        }
        
        logger.info(f"Attempting to fetch webhook data for phone: {phone_number}")
        response = session.post(
            f"https://api.omnia-voice.com/api/incoming",
            headers=headers,
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        
        # Log raw response
        logger.info(f"Raw response: {response.text}")
        
        # Parse response
        response_data = response.json()
        logger.info(f"Parsed response data: {json.dumps(response_data, indent=2)}")
        
        if isinstance(response_data, dict):
            # If response is a single object
            clean_from_number = phone_number.replace('+', '').replace('-', '').replace(' ', '')
            response_phone = response_data.get('caller_phone_number', '').replace('+', '').replace('-', '').replace(' ', '')
            
            if clean_from_number == response_phone:
                logger.info(f"Found matching call data for phone: {phone_number}")
                return response_data
        elif isinstance(response_data, list):
            # If response is an array
            clean_from_number = phone_number.replace('+', '').replace('-', '').replace(' ', '')
            
            logger.info(f"Successfully fetched calls data. Searching for phone: {clean_from_number}")
            matching_call = next(
                (call for call in response_data 
                 if call.get('caller_phone_number', '').replace('+', '').replace('-', '').replace(' ', '') == clean_from_number),
                None
            )
            
            if matching_call:
                logger.info(f"Found matching call data for phone: {phone_number}")
                return matching_call
            
        logger.warning(f"No matching call found for phone number: {phone_number}")
        return None
            
    except requests.Timeout:
        logger.error(f"Timeout while fetching webhook data for phone: {phone_number} after retries")
        return None
    except requests.RequestException as e:
        logger.error(f"Failed to fetch webhook data after retries: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while fetching webhook data: {str(e)}")
        logger.error(f"Full traceback:", exc_info=True)  # Add full traceback
        return None
    finally:
        session.close()

def handle_send_financial_details(parameters, td_uuid, subdomain, data):
    logger.info(f"Handling sendFinancialDetails")
    
    # Get phone number from incoming data
    call_object = data.get('message', {}).get('call', {})
    from_number = call_object.get('customer', {}).get('number')
    
    if not from_number:
        logger.error("No phone number provided in request")
        return jsonify({
            "status": "error",
            "message": "No phone number provided",
            "data_sent": False
        }), 400

    # Fetch webhook data using phone number
    webhook_data = fetch_webhook_data(from_number)
    if not webhook_data:
        logger.error(f"No webhook data found for phone number: {from_number}")
        return jsonify({
            "status": "error",
            "message": "No webhook data found",
            "data_sent": False
        }), 404

    # Use call_id from webhook data as td_uuid
    td_uuid = webhook_data['call_id']

    # Prepare financial data
    financial_data = {
        "debtAmount": parameters.get('debtAmount'),
        "debtType": parameters.get('debtType'),
        "monthlyIncome": parameters.get('monthlyIncome'),
        "hasCheckingAccount": parameters.get('hasCheckingAccount'),
        "alreadyEnrolledAnyOtherProgram": parameters.get('alreadyEnrolledAnyOtherProgram')
    }

    # Combine webhook data with financial data
    combined_data = {
        "webhook_data": {
            "first_name": webhook_data.get('first_name'),
            "last_name": webhook_data.get('last_name'),
            "email": webhook_data.get('email'),
            "address": webhook_data.get('address'),
            "city": webhook_data.get('city'),
            "state": webhook_data.get('state'),
            "zip": webhook_data.get('zip'),
            "campaign_title": webhook_data.get('campaign_title'),
            "additional_data": webhook_data.get('additional_data')
        },
        "financial_data": financial_data
    }

    logger.info(f"Attempting to send keypress and combined data for TD_UUID: {td_uuid}")
    success = send_trackdrive_keypress(td_uuid, '*', subdomain, combined_data)
    
    if success:
        logger.info(f"Keypress '*' and combined data sent successfully for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "success",
            "message": "Keypress and combined data sent",
            "data_sent": True
        }), 200
    else:
        logger.warning(f"Failed to send keypress '*' and combined data for TD_UUID: {td_uuid}")
        return jsonify({
            "status": "error",
            "message": "Failed to send keypress and combined data",
            "data_sent": False
        }), 500



def send_trackdrive_keypress(td_uuid, keypress, subdomain="global-telecom-investors", combined_data=None):
    logger.info(f"Attempting to send TrackDrive keypress and data. TD_UUID: {td_uuid}, Keypress: {keypress}, Subdomain: {subdomain}")
    
    session = create_session_with_retries()
    url = "https://global-telecom-investors.trackdrive.com/api/v1/calls/send_key_press"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {TRACKDRIVE_AUTH}"
    }
    
    if not td_uuid:
        logger.error("Missing TD_UUID. Cannot send keypress to TrackDrive.")
        return False
    
    payload = {
        "id": str(td_uuid),
        "digits": keypress
    }
    
    if combined_data:
        payload.update({
            "data": {
                "customer_info": combined_data.get("webhook_data", {}),
                "financial_info": combined_data.get("financial_data", {}),
                "timestamp": datetime.now().isoformat()
            }
        })

    try:
        logger.info(f"Sending POST request to TrackDrive API. Payload: {json.dumps(payload)}")
        response = session.post(url, headers=headers, json=payload, timeout=10)
        
        # Log the response details
        logger.info(f"TrackDrive API response: Status Code {response.status_code}")
        logger.info(f"Response Content: {response.text}")
        
        response.raise_for_status()
        
        if response.status_code == 200:
            success_message = f"SUCCESS: Keypress '{keypress}' sent successfully for TD_UUID: {td_uuid}"
            logger.info(success_message)
            print(success_message)
            
            if keypress == '*':
                transfer_message = f"SUCCESS: Call transfer initiated for TD_UUID: {td_uuid}"
                logger.info(transfer_message)
                print(transfer_message)
        
        return True
    except requests.Timeout:
        logger.error(f"Timeout sending keypress to TrackDrive for TD_UUID: {td_uuid}")
        return False
    except requests.RequestException as e:
        error_message = f"FAILED: Could not send keypress '{keypress}' for TD_UUID: {td_uuid}. Error: {str(e)}"
        logger.error(error_message)
        print(error_message)
        
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response status code: {e.response.status_code}")
            logger.error(f"Response content: {e.response.content}")
        return False
    finally:
        session.close()
    



if __name__ == '__main__':
    logger.info("Starting Flask application")
    app.run(debug=True, port=5000)
