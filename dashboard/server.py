import os
import json
import csv
from http.server import SimpleHTTPRequestHandler, HTTPServer
import urllib.parse

class DashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        # Serve API endpoint for trade data
        if self.path.startswith('/api/trades'):
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            data = self.load_trade_data()
            self.wfile.write(json.dumps(data).encode())
            return
            
        # Default behavior: serve static files
        if self.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def load_trade_data(self):
        log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot_logs')
        if not os.path.exists(log_dir):
            return []

        all_records = []
        for file in sorted(os.listdir(log_dir)):
            if file.startswith("executions_") and file.endswith(".csv"):
                file_path = os.path.join(log_dir, file)
                with open(file_path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Convert numeric fields
                        for key in ['k_price', 'p_price', 'intended_qty', 'theoretical_profit', 
                                  'k_fill_qty', 'k_fill_time_ms', 'p_fill_qty', 'p_fill_time_ms', 
                                  'unwind_pnl', 'net_realized_pnl']:
                            if key in row and row[key]:
                                try:
                                    row[key] = float(row[key])
                                except ValueError:
                                    pass
                        all_records.append(row)
        return all_records

def run(server_class=HTTPServer, handler_class=DashboardHandler, port=8000):
    os.chdir(os.path.dirname(__file__)) # Serve from the dashboard directory
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"🚀 Janus Dashboard running at http://localhost:{port}")
    httpd.serve_forever()

if __name__ == '__main__':
    run()
