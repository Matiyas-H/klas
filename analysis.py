from flask import Flask, jsonify, request, render_template_string
import requests
from flask_cors import CORS
from collections import Counter

app = Flask(__name__)
CORS(app)

# API configuration
API_URL = "https://api.vapi.ai/call"
ASSISTANT_ID = "c80f483e-16c1-4d12-a04a-a3c58d3c2dca"
API_KEY = "Bearer 71c0393e-fcfd-4147-ac15-42b68fdd53ff"

def fetch_calls():
    """Fetch calls from external API and return as JSON."""
    headers = {"Authorization": API_KEY}
    params = {
        "assistantId": ASSISTANT_ID,
        "limit": "200"
    }
    response = requests.get(API_URL, headers=headers, params=params)
    if response.status_code == 200:
        return response.json()
    else:
        return None

def process_calls(response_data, search_number=None):
    """Extract specific fields from call data and perform analysis."""
    processed_calls = []
    tool_usage = Counter()
    qualified_count = 0
    
    calls = response_data if isinstance(response_data, list) else [response_data]
    
    for call in calls:
        caller_number = call.get("customer", {}).get("number", "No number available")
        
        if search_number and search_number not in caller_number:
            continue
        
        financial_details = None
        tool_calls = []
        
        for message in call.get('messages', []):
            if message.get('role') == 'tool_calls':
                for tool_call in message.get('toolCalls', []):
                    function = tool_call.get('function', {})
                    tool_name = function.get('name')
                    tool_calls.append(tool_name)
                    tool_usage[tool_name] += 1
                    if tool_name == 'sendFinancialDetails':
                        financial_details = function.get('arguments')
                        qualified_count += 1
        
        processed_call = {
            "caller_number": caller_number,
            "call_summary": call.get("summary", "No summary available"),
            "tools_used": tool_calls,
            "financial_details": financial_details
        }
        processed_calls.append(processed_call)
    
    analysis = {
        "total_calls": len(processed_calls),
        "tool_usage": dict(tool_usage),
        "qualified_leads": qualified_count,
        "qualification_rate": f"{(qualified_count / len(processed_calls)) * 100:.2f}%" if processed_calls else "0.00%"
    }
    
    return processed_calls, analysis

@app.route('/', methods=['GET'])
def get_calls():
    """API endpoint to get processed call data and analysis."""
    search_number = request.args.get('search', '')
    response_data = fetch_calls()
    if response_data is not None:
        summarized_calls, analysis = process_calls(response_data, search_number)
        
        html = """
        <html>
        <head>
            <style>
                table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
                th, td { border: 1px solid black; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                form { margin-bottom: 20px; }
            </style>
        </head>
        <body>
            <h1>Call Analysis Dashboard</h1>
            
            <form action="/" method="get">
                <input type="text" name="search" placeholder="Search by phone number" value="{{ search_number }}">
                <input type="submit" value="Search">
            </form>
            
            <h2>Call Analysis</h2>
            <table>
                <tr><th>Metric</th><th>Value</th></tr>
                <tr><td>Total Calls</td><td>{{ analysis.total_calls }}</td></tr>
                <tr><td>Qualified Leads</td><td>{{ analysis.qualified_leads }}</td></tr>
                <tr><td>Qualification Rate</td><td>{{ analysis.qualification_rate }}</td></tr>
            </table>
            
            <h2>Tool Usage</h2>
            <table>
                <tr><th>Tool</th><th>Count</th></tr>
                {% for tool, count in analysis.tool_usage.items() %}
                <tr><td>{{ tool }}</td><td>{{ count }}</td></tr>
                {% endfor %}
            </table>
            
            <h2>Call Details</h2>
            <table>
                <tr>
                    <th>Caller Number</th>
                    <th>Summary</th>
                    <th>Tools Used</th>
                    <th>Financial Details</th>
                </tr>
                {% for call in calls %}
                <tr>
                    <td>{{ call.caller_number }}</td>
                    <td>{{ call.call_summary }}</td>
                    <td>{{ ', '.join(call.tools_used) }}</td>
                    <td>{{ call.financial_details }}</td>
                </tr>
                {% endfor %}
            </table>
        </body>
        </html>
        """
        
        return render_template_string(html, calls=summarized_calls, analysis=analysis, search_number=search_number)
    else:
        return jsonify({"error": "Failed to fetch data from API"}), 500

if __name__ == '__main__':
    app.run(debug=True)