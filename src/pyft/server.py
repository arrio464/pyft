import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from .utils import validate_token


def generate_file_list(directory):
    return [
        os.path.join(root, file)
        for root, _, files in os.walk(directory)
        for file in files
    ]


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/download":
            self.handle_download(parsed_path)
        else:
            self.handle_file_list(parsed_path)

    def handle_file_list(self, parsed_path):
        query_params = parse_qs(parsed_path.query)

        if "token" not in query_params:
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "error": "Unauthorized. Provide a valid token to access the file list."
                    }
                ).encode()
            )
            return

        token = query_params.get("token", [None])[0]

        if not validate_token(token):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "Forbidden. Invalid token."}).encode()
            )
            return

        directory = "./files"
        if not os.path.exists(directory):
            os.makedirs(directory)

        file_list = generate_file_list(directory)
        response_data = {
            "files": [
                {
                    "name": os.path.basename(file),
                    "url": f"http://{self.server.server_address[0]}:{self.server.server_address[1]}/download?token={token}&file={os.path.basename(file)}",
                }
                for file in file_list
            ]
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response_data).encode())

    def handle_download(self, parsed_path):
        query_params = parse_qs(parsed_path.query)
        token = query_params.get("token", [None])[0]
        file_name = query_params.get("file", [None])[0]

        if not validate_token(token) or not file_name:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "Forbidden or missing parameters."}).encode()
            )
            return

        file_path = os.path.join("./files", file_name)
        if not os.path.isfile(file_path):
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "File not found."}).encode())
            return

        self.send_response(200)
        self.send_header("Content-Disposition", f"attachment; filename={file_name}")
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()

        with open(file_path, "rb") as f:
            self.wfile.write(f.read())


if __name__ == "__main__":
    host = "localhost"
    port = 8080

    server = HTTPServer((host, port), SimpleHTTPRequestHandler)
    print(f"Server started at http://{host}:{port}")
    server.serve_forever()
