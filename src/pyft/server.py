import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .utils import validate_token


def generate_file_list(directory):
    return [
        os.path.join(root, file)
        for root, _, files in os.walk(directory)
        for file in files
    ]


class ThreadedHTTPRequestHandler(BaseHTTPRequestHandler):
    # Speed limit in bytes per second (e.g., 1MB/s)
    # SPEED_LIMIT = 1024 * 1024
    SPEED_LIMIT = 8192

    def throttled_read(self, file_obj, chunk_size=8192):
        """Read file with speed limiting."""
        while True:
            start_time = time.time()

            chunk = file_obj.read(chunk_size)
            if not chunk:
                break

            yield chunk

            # Calculate sleep time to maintain speed limit
            elapsed = time.time() - start_time
            expected_time = len(chunk) / self.SPEED_LIMIT
            if elapsed < expected_time:
                time.sleep(expected_time - elapsed)

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/download":
            self.handle_download(parsed_path)
        else:
            self.handle_file_list(parsed_path)

    def do_POST(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/upload":
            self.handle_upload(parsed_path)
        else:
            self.send_response(404)
            self.end_headers()

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
                    "size": os.path.getsize(file),
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

        file_size = os.path.getsize(file_path)
        start_byte = 0
        end_byte = file_size - 1

        # Handle Range header
        range_header = self.headers.get("Range")
        if range_header:
            try:
                range_match = range_header.replace("bytes=", "").split("-")
                start_byte = int(range_match[0])
                if range_match[1]:
                    end_byte = int(range_match[1])
            except (ValueError, IndexError):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid range header"}).encode())
                return

            if start_byte >= file_size:
                self.send_response(416)  # Range Not Satisfiable
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.end_headers()
                return

            self.send_response(206)  # Partial Content
            self.send_header(
                "Content-Range", f"bytes {start_byte}-{end_byte}/{file_size}"
            )
        else:
            self.send_response(200)

        content_length = end_byte - start_byte + 1
        self.send_header("Content-Length", content_length)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f"attachment; filename={file_name}")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        with open(file_path, "rb") as f:
            f.seek(start_byte)
            bytes_to_read = content_length
            while bytes_to_read > 0:
                chunk_size = min(8192, bytes_to_read)
                for chunk in self.throttled_read(f, chunk_size):
                    self.wfile.write(chunk)
                    bytes_to_read -= len(chunk)

    def handle_upload(self, parsed_path):
        query_params = parse_qs(parsed_path.query)
        token = query_params.get("token", [None])[0]

        if not token or not validate_token(token):
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "Forbidden. Invalid token."}).encode()
            )
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": "No file content received."}).encode()
            )
            return

        file_data = self.rfile.read(content_length)
        file_name = self.headers.get("X-File-Name", "uploaded_file")

        directory = "./files"
        if not os.path.exists(directory):
            os.makedirs(directory)

        file_path = os.path.join(directory, file_name)
        try:
            with open(file_path, "wb") as f:
                f.write(file_data)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"message": "File uploaded successfully"}).encode()
            )
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": f"Upload failed: {str(e)}"}).encode())


def run_server(host="0.0.0.0", port=8080):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, ThreadedHTTPRequestHandler)
    print(f"Starting threaded server on {host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        httpd.server_close()


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 23536

    run_server(host, port)
