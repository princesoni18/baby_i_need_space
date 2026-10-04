import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# Standalone helper to test Meta's webhook verification without the full app.
# Usage: WHATSAPP_VERIFY_TOKEN=yourtoken python verify_webhook.py
VERIFY_TOKEN = os.environ.get('WHATSAPP_VERIFY_TOKEN', '')

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/webhook':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            mode = query_params.get('hub.mode', [''])[0]
            token = query_params.get('hub.verify_token', [''])[0]
            challenge = query_params.get('hub.challenge', [''])[0]

            if mode == 'subscribe' and token == VERIFY_TOKEN:
                self.send_response(200)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(challenge.encode('utf-8'))
                print(f"Verified webhook successfully! Challenge sent: {challenge}")
            else:
                self.send_response(403)
                self.end_headers()
                print("Failed verification: Invalid token or mode.")
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    server_address = ('', 8000)
    httpd = HTTPServer(server_address, WebhookHandler)
    print("Listening on port 8000 for Meta Webhook verification...")
    httpd.serve_forever()
