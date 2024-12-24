import os
import threading
from http.server import HTTPServer

import pytest
import requests

from src.pyft.server import SimpleHTTPRequestHandler
from src.pyft.utils import generate_token

# a0cad194c6d3f84467b52e175dea19db8aab04e300ac2360ca3b423d5b14ca9d
valid_token = generate_token("user1", "password1")


# Test setup
@pytest.fixture(scope="module")
def http_server():
    host = "127.0.0.1"
    port = 8080
    server = HTTPServer((host, port), SimpleHTTPRequestHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.setDaemon(True)
    server_thread.start()

    yield server

    server.shutdown()
    server_thread.join()


@pytest.fixture(scope="module")
def setup_files():
    test_dir = "./files"
    if not os.path.exists(test_dir):
        os.makedirs(test_dir)

    test_files = ["1", "2", "3"]
    for file_name in test_files:
        with open(os.path.join(test_dir, file_name), "w") as f:
            f.write(f"Content of {file_name}")

    yield test_files

    # Cleanup
    for file_name in test_files:
        os.remove(os.path.join(test_dir, file_name))
    os.rmdir(test_dir)


def test_file_list(http_server, setup_files):
    response = requests.get("http://127.0.0.1:8080", params={"token": valid_token})
    assert response.status_code == 200

    data = response.json()
    assert "files" in data
    assert len(data["files"]) == len(setup_files)

    for file_info in data["files"]:
        assert "name" in file_info
        assert "url" in file_info
        assert file_info["name"] in setup_files


def test_download_file(http_server, setup_files):
    for file_name in setup_files:
        response = requests.get(
            "http://127.0.0.1:8080/download",
            params={"token": valid_token, "file": file_name},
        )
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/octet-stream"
        assert response.text == f"Content of {file_name}"


def test_unauthorized_access():
    response = requests.get("http://127.0.0.1:8080")
    assert response.status_code == 401
    assert "error" in response.json()
    assert (
        response.json()["error"]
        == "Unauthorized. Provide a valid token to access the file list."
    )


def test_invalid_token():
    response = requests.get("http://127.0.0.1:8080", params={"token": "invalid-token"})
    assert response.status_code == 403
    assert "error" in response.json()
    assert response.json()["error"] == "Forbidden. Invalid token."


def test_file_not_found(http_server):
    response = requests.get(
        "http://127.0.0.1:8080/download",
        params={"token": valid_token, "file": "nonexistent"},
    )
    assert response.status_code == 404
    assert "error" in response.json()
    assert response.json()["error"] == "File not found."
