import datetime
from flask import Flask, request, jsonify, abort
import requests
import logging
import json
import os
from dotenv import load_dotenv

# Enhanced logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
app = Flask(__name__)

logger.info("Starting application and loading environment variables")

SERVER_SECRET = os.getenv('SERVER_SECRET')
TEXTBACK_API_URL = os.getenv('TEXTBACK_API_URL')
TEXTBACK_API_TOKEN = os.getenv('TEXTBACK_API_TOKEN')
TEXTBACK_API_SECRET = os.getenv('TEXTBACK_API_SECRET')
TRACKDRIVE_PUBLIC_KEY = os.getenv('TRACKDRIVE_PUBLIC_KEY')
TRACKDRIVE_PRIVATE_KEY = os.getenv('TRACKDRIVE_PRIVATE_KEY')
OMNIA_VOICE_API_KEY = os.getenv('OMNIA_VOICE_API_KEY')
TRACKDRIVE_AUTH = os.getenv('TRACKDRIVE_AUTH')

@app.route('/handle_incoming_call', methods=['POST'])
def handle_incoming_call():
    logger.info("-------- NEW INCOMING CALL REQUEST --------")
    logger.info(f"Received request at /handle_incoming_call at {datetime.datetime.now()}")
    
    # Log request details
    data = request.json
    logger.info(f"Incoming Request Data: {json.dumps(data, indent=2)}")
    logger.info(f"Request Headers: {dict(request.headers)}")

    # Log secret validation
    received_secret = request.headers.get('X-Vapi-Secret')
    logger.info(f"Validating secret: {'*' * len(received_secret) if received_secret else 'None'}")

    if received_secret != SERVER_SECRET:
        logger.warning("❌ Secret validation failed. Access denied.")
        abort(403)
    logger.info("✅ Secret validation successful")

    message_type = data.get('message', {}).get('type')
    logger.info(f"Processing message type: {message_type}")

    if message_type == 'function-call':
        function_call = data.get('message', {}).get('functionCall', {})
        function_name = function_call.get('name')
        parameters = function_call.get('parameters')
        logger.info(f"Function call detected - Name: {function_name}")
        logger.info(f"Parameters received: {json.dumps(parameters, indent=2)}")

        if function_name == 'sendFinancialDetails':
            return handle_send_financial_details(parameters, None, "global-telecom-investors", data)
        else:
            logger.warning(f"❌ Unknown function name received: {function_name}")
            return jsonify({"error": f"Unknown function: {function_name}"}), 400
    else:
        logger.warning(f"❌ Invalid request type received: {message_type}")
        return jsonify({"error": "Invalid request"}), 400

def fetch_webhook_data(phone_number):
    """Fetch webhook data from API using phone number"""
    logger.info(f"-------- FETCHING WEBHOOK DATA --------")
    logger.info(f"Attempting to fetch webhook data for phone number: {phone_number}")
    
    try:
        headers = {
            "X-API-Key": OMNIA_VOICE_API_KEY,
            "Content-Type": "application/json"
        }
        logger.info("Making API request to Omnia Voice API")
        response = requests.get(
            "https://api.omnia-voice.com/api/incoming",
            headers=headers
        )
        response.raise_for_status()
        
        calls = response.json()
        logger.info(f"Received {len(calls)} calls from API")
        
        matching_call = next(
            (call for call in calls 
             if call['caller_phone_number'] == phone_number),
            None
        )
        
        if matching_call:
            logger.info("✅ Found matching call data:")
            logger.info(f"Call ID: {matching_call.get('call_id')}")
            logger.info(f"Phone: {matching_call.get('caller_phone_number')}")
            return matching_call
        else:
            logger.warning(f"❌ No matching call found for phone number: {phone_number}")
            return None
            
    except requests.RequestException as e:
        logger.error(f"❌ Failed to fetch webhook data: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return None

def handle_send_financial_details(parameters, td_uuid, subdomain, data):
    logger.info("-------- HANDLING FINANCIAL DETAILS --------")
    logger.info("Starting financial details processing")
    
    # Extract phone number
    call_object = data.get('message', {}).get('call', {})
    from_number = call_object.get('customer', {}).get('number')
    logger.info(f"Extracted phone number: {from_number}")
    
    if not from_number:
        logger.error("❌ No phone number found in request data")
        return jsonify({
            "status": "error",
            "message": "No phone number provided",
            "data_sent": False
        }), 400

    # Fetch webhook data
    webhook_data = fetch_webhook_data(from_number)
    if not webhook_data:
        logger.error(f"❌ No webhook data found for phone: {from_number}")
        return jsonify({
            "status": "error",
            "message": "No webhook data found",
            "data_sent": False
        }), 404

    # Get td_uuid from call_id
    td_uuid = webhook_data['call_id']
    logger.info(f"✅ Successfully mapped td_uuid: {td_uuid}")

    # Prepare data
    logger.info("Preparing combined data for TrackDrive")
    combined_data = {
        "webhook_data": {
            "first_name": webhook_data.get('first_name', ''),
            "last_name": webhook_data.get('last_name', ''),
            "email": webhook_data.get('email', ''),
            "address": webhook_data.get('address', ''),
            "city": webhook_data.get('city', ''),
            "state": webhook_data.get('state', ''),
            "zip": webhook_data.get('zip', ''),
            "campaign_title": webhook_data.get('campaign_title', ''),
            "additional_data": webhook_data.get('additional_data', ''),
            "caller_phone_number": webhook_data.get('caller_phone_number', '')
        },
        "financial_data": {
            "debtAmount": parameters.get('debtAmount'),
            "debtType": parameters.get('debtType'),
            "monthlyIncome": parameters.get('monthlyIncome'),
            "hasCheckingAccount": parameters.get('hasCheckingAccount'),
            "alreadyEnrolledAnyOtherProgram": parameters.get('alreadyEnrolledAnyOtherProgram')
        },
        "timestamp": webhook_data.get('timestamp', datetime.datetime.now().isoformat())
    }
    logger.info(f"Combined data prepared: {json.dumps(combined_data, indent=2)}")

    # Send to TrackDrive
    logger.info(f"Initiating TrackDrive keypress send for td_uuid: {td_uuid}")
    success = send_trackdrive_keypress(td_uuid, '*', subdomain, combined_data)
    
    if success:
        logger.info(f"✅ Successfully processed financial details for td_uuid: {td_uuid}")
        return jsonify({
            "status": "success",
            "message": "Keypress and combined data sent",
            "data_sent": True,
            "td_uuid": td_uuid
        }), 200
    else:
        logger.error(f"❌ Failed to process financial details for td_uuid: {td_uuid}")
        return jsonify({
            "status": "error",
            "message": "Failed to send keypress and combined data",
            "data_sent": False,
            "td_uuid": td_uuid
        }), 500

def send_trackdrive_keypress(td_uuid, keypress, subdomain="global-telecom-investors", combined_data=None):
    logger.info("-------- SENDING TO TRACKDRIVE --------")
    logger.info(f"Preparing TrackDrive request for td_uuid: {td_uuid}")
    
    url = f"https://{subdomain}.trackdrive.com/api/v1/calls/send_key_press"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {TRACKDRIVE_AUTH}"
    }
    
    if not td_uuid:
        logger.error("❌ Missing td_uuid - Cannot proceed with TrackDrive update")
        return False
    
    payload = {
        "id": td_uuid,
        "digits": keypress,
        "data": combined_data
    }
    
    logger.info("TrackDrive request details:")
    logger.info(f"URL: {url}")
    logger.info(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        logger.info("Sending request to TrackDrive")
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        logger.info(f"✅ Successfully sent data to TrackDrive")
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Response body: {response.text}")
        
        if keypress == '*':
            logger.info(f"✅ Call transfer initiated for td_uuid: {td_uuid}")
        
        return True
    except requests.RequestException as e:
        logger.error(f"❌ Failed to send data to TrackDrive: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return False

if __name__ == '__main__':
    logger.info("Starting Flask application server")
    app.run(debug=True, port=5000)
