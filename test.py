from flask import Flask, request, jsonify
import logging
import json

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/simulate_financial_data', methods=['POST'])
def simulate_financial_data():
    data = request.json

    # Log the entire raw request body to inspect what is being received
    logging.info(f"Received request data: {data}")

    # Extract financial details from the functionCall
    message = data.get('message', {})
    function_call = message.get('functionCall', {})
    
    if function_call.get('name') == 'sendFinancialDetails':
        financial_details = function_call.get('parameters')
        if not financial_details:
            # If not in 'parameters', try to parse from 'arguments'
            arguments = function_call.get('arguments')
            if arguments:
                try:
                    financial_details = json.loads(arguments)
                except json.JSONDecodeError:
                    logging.error("Failed to parse sendFinancialDetails arguments")
                    financial_details = None
    else:
        financial_details = None

    if not financial_details:
        logging.error("Financial details not found in the request")
        return jsonify({"status": "error", "message": "Financial details not found"}), 400

    # Map the extracted details to the expected format
    processed_data = {
        'debt_type': financial_details.get('debtType'),
        'debt_amount': financial_details.get('debtAmount'),
        'monthly_income': financial_details.get('monthlyIncome'),
        'employment_status': financial_details.get('employmentStatus'),
        'has_checking_account': financial_details.get('hasCheckingAccount')
    }

    # Validate required fields
    required_fields = ['debt_type', 'debt_amount', 'monthly_income', 'employment_status', 'has_checking_account']
    missing_fields = [field for field in required_fields if processed_data.get(field) is None]
    if missing_fields:
        logging.error(f"Missing fields: {', '.join(missing_fields)}")
        return jsonify({"status": "error", "message": f"Missing fields: {', '.join(missing_fields)}"}), 400

    # Log the processed financial data
    logging.info("Processed financial data:")
    for field in required_fields:
        logging.info(f"{field.replace('_', ' ').title()}: {processed_data.get(field)}")

    return jsonify({"status": "success", "message": "Financial data processed successfully", "data": processed_data}), 200

if __name__ == '__main__':
    app.run(debug=True)