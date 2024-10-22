from datetime import datetime
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

# Enhanced logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# Add a file handler to keep logs
file_handler = logging.FileHandler('trackdrive_integration.log')
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

def create_session_with_retries():
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

load_dotenv()
app = Flask(__name__)

# Load environment variables
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
    logger.info("🔵 New incoming call received")
    try:
        data = request.json
        logger.info(f"📥 Incoming Request Data: {json.dumps(data, indent=2)}")

        received_secret = request.headers.get('X-Vapi-Secret')
        if received_secret != SERVER_SECRET:
            logger.error("🚫 Security validation failed - invalid secret")
            abort(403)

        message_type = data.get('message', {}).get('type')
        logger.info(f"📋 Processing message type: {message_type}")

        if message_type == 'function-call':
            function_call = data.get('message', {}).get('functionCall', {})
            function_name = function_call.get('name')
            parameters = function_call.get('parameters')
            
            logger.info(f"⚙️ Function called: {function_name}")
            logger.info(f"📝 Parameters received: {json.dumps(parameters, indent=2)}")

            if function_name == 'sendFinancialDetails':
                return handle_send_financial_details(parameters, None, "global-telecom-investors", data)
            else:
                logger.error(f"❌ Unknown function called: {function_name}")
                return jsonify({"error": f"Unknown function: {function_name}"}), 400
        elif message_type == 'status-update':
            # Handle status updates
            logger.info("📊 Received status update")
            status_data = data.get('message', {}).get('status', {})
            logger.info(f"Status update data: {json.dumps(status_data, indent=2)}")
            return jsonify({"status": "success", "message": "Status update received"}), 200
        else:
            logger.error(f"❌ Invalid request type: {message_type}")
            return jsonify({"error": "Invalid request"}), 400

    except Exception as e:
        logger.error(f"💥 Error in handle_incoming_call: {str(e)}", exc_info=True)
        return jsonify({"error": "Internal server error"}), 500

def fetch_webhook_data(phone_number):
    logger.info(f"🔍 Fetching webhook data for phone: {phone_number}")
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
        
        response = session.post(
            f"https://api.omnia-voice.com/api/incoming",
            headers=headers,
            json=payload,
            timeout=10
        )
        
        logger.info(f"📡 Webhook API Response Status: {response.status_code}")
        logger.info(f"📡 Webhook API Response: {response.text}")
        
        response.raise_for_status()
        response_data = response.json()
        
        if response_data:
            logger.info("✅ Successfully retrieved webhook data")
            return response_data
        else:
            logger.warning("⚠️ No data found in webhook response")
            return None
            
    except Exception as e:
        logger.error(f"💥 Error fetching webhook data: {str(e)}", exc_info=True)
        return None
    finally:
        session.close()

def handle_send_financial_details(parameters, td_uuid, subdomain, data):
    logger.info("🏁 Starting financial details processing")
    
    call_object = data.get('message', {}).get('call', {})
    from_number = call_object.get('customer', {}).get('number')
    
    if not from_number:
        logger.error("❌ No phone number provided in request")
        return jsonify({
            "status": "error",
            "message": "No phone number provided",
            "data_sent": False
        }), 400

    logger.info(f"📞 Processing call from: {from_number}")
    webhook_data = fetch_webhook_data(from_number)
    
    financial_data = {
        "debtAmount": parameters.get('debtAmount'),
        "debtType": parameters.get('debtType'),
        "monthlyIncome": parameters.get('monthlyIncome'),
        "hasCheckingAccount": parameters.get('hasCheckingAccount'),
        "alreadyEnrolledAnyOtherProgram": parameters.get('alreadyEnrolledAnyOtherProgram')
    }
    
    logger.info(f"💰 Financial data prepared: {json.dumps(financial_data, indent=2)}")

    if webhook_data:
        logger.info("📋 Webhook data found, combining with financial data")
        td_uuid = webhook_data.get('call_id')
        combined_data = {
            "customer_info": {
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
            "financial_info": financial_data
        }
    else:
        logger.info("⚠️ No webhook data found, using financial data only")
        td_uuid = "1234"
        combined_data = {
            "customer_info": {},
            "financial_info": financial_data
        }

    logger.info(f"🎯 Sending data to TrackDrive for UUID: {td_uuid}")
    success = send_trackdrive_keypress(td_uuid, '*', subdomain, combined_data)
    
    if success:
        logger.info("✅ Successfully processed financial details")
        return jsonify({
            "status": "success",
            "message": "Keypress and combined data sent",
            "data_sent": True
        }), 200
    else:
        logger.error("❌ Failed to process financial details")
        return jsonify({
            "status": "error",
            "message": "Failed to send keypress and combined data",
            "data_sent": False
        }), 500

def send_trackdrive_keypress(td_uuid, keypress, subdomain="global-telecom-investors", combined_data=None):
    logger.info(f"🔄 Starting TrackDrive keypress operation - TD_UUID: {td_uuid}, Keypress: {keypress}")
    
    session = create_session_with_retries()
    
    # Updated URL format
    url = f"https://{subdomain}.trackdrive.net/api/v1/calls/keypress"  # Changed to .net and updated endpoint
    
    logger.info(f"🌐 Using TrackDrive endpoint: {url}")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {TRACKDRIVE_AUTH}"
    }
    
    if not td_uuid:
        logger.error("❌ Missing TD_UUID - Cannot proceed with keypress")
        return False
    
    try:
        payload = {
            "call_id": str(td_uuid),  # Changed from 'id' to 'call_id'
            "key": keypress,          # Changed from 'digits' to 'key'
            "timestamp": datetime.now().isoformat()
        }
        
        if combined_data:
            payload["additional_data"] = {  # Changed from 'data' to 'additional_data'
                "customer_info": combined_data.get("customer_info", {}),
                "financial_info": combined_data.get("financial_info", {})
            }

        # Log the payload (with sensitive data masked)
        masked_payload = {
            "call_id": payload["call_id"],
            "key": payload["key"],
            "timestamp": payload["timestamp"],
            "additional_data": "***MASKED***" if "additional_data" in payload else None
        }
        logger.info(f"📤 Sending payload to TrackDrive: {json.dumps(masked_payload, indent=2)}")
        
        # Send request to TrackDrive
        response = session.post(url, headers=headers, json=payload, timeout=10)
        
        # Log response details
        logger.info(f"📥 TrackDrive Response Status: {response.status_code}")
        logger.info(f"📥 TrackDrive Response Body: {response.text}")
        
        response.raise_for_status()
        
        # Process response
        if response.status_code == 200:
            response_data = response.json()
            
            # Log successful keypress details
            logger.info(f"✅ Keypress '{keypress}' successfully sent for TD_UUID: {td_uuid}")
            logger.info(f"📋 TrackDrive Response Data: {json.dumps(response_data, indent=2)}")
            
            if keypress == '*':
                logger.info(f"🔄 Transfer initiated for TD_UUID: {td_uuid}")
            
            return True
            
    except requests.Timeout:
        logger.error(f"⏰ Timeout sending keypress to TrackDrive - TD_UUID: {td_uuid}")
        return False
    except requests.RequestException as e:
        logger.error(f"💥 TrackDrive API error - TD_UUID: {td_uuid}, Error: {str(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response status: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
        return False
    except Exception as e:
        logger.error(f"💥 Unexpected error in TrackDrive keypress - TD_UUID: {td_uuid}, Error: {str(e)}", exc_info=True)
        return False
    finally:
        session.close()

if __name__ == '__main__':
    logger.info("🚀 Starting Flask application")
    app.run(debug=True, port=5000)
