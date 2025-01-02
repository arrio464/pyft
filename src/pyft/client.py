import cmd
import os
from typing import BinaryIO, Callable, Dict, List, Optional

import requests
from requests import Response
from tqdm import tqdm

from .utils import generate_token


class FileTransferBase:
    def __init__(self, server_url: str, token: str):
        self.server_url = server_url.rstrip("/")
        self.token = token
        self._progress_callback: Optional[Callable[[int, int], None]] = None

    def set_progress_callback(self, callback: Callable[[int, int], None]) -> None:
        """Set callback for progress updates: callback(bytes_processed, total_bytes)"""
        self._progress_callback = callback

    def list_files(self) -> List[Dict[str, str]]:
        """Get list of available files"""
        response = requests.get(self.server_url, params={"token": self.token})
        response.raise_for_status()
        return response.json()["files"]

    def download_file(self, file_name: str, output_dir: Optional[str] = None) -> str:
        """Download a file and return its local path"""
        response = self._start_download(file_name)
        return self._process_download(response, file_name, output_dir)

    def upload_file(self, file_path: str) -> dict:
        """Upload a file and return server response"""
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        with open(file_path, "rb") as f:
            return self._process_upload(f, file_name, file_size)

    def _start_download(self, file_name: str) -> Response:
        """Initialize file download"""
        response = requests.get(
            f"{self.server_url}/download",
            params={"token": self.token, "file": file_name},
            stream=True,
        )
        response.raise_for_status()
        return response

    def _process_download(
        self, response: Response, file_name: str, output_dir: Optional[str] = None
    ) -> str:
        """Process download stream and save to file"""
        output_dir = output_dir or "downloads"
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, file_name)

        total_size = int(response.headers.get("content-length", 0))
        bytes_downloaded = 0

        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if self._progress_callback:
                        self._progress_callback(bytes_downloaded, total_size)

        return output_path

    def _process_upload(
        self, file_obj: BinaryIO, file_name: str, file_size: int
    ) -> dict:
        """Process file upload"""
        bytes_uploaded = 0

        def upload_callback(chunk: bytes) -> bytes:
            nonlocal bytes_uploaded
            bytes_uploaded += len(chunk)
            if self._progress_callback:
                self._progress_callback(bytes_uploaded, file_size)
            return chunk

        response = requests.post(
            f"{self.server_url}/upload",
            params={"token": self.token},
            headers={"X-File-Name": file_name},
            data=iter(lambda: upload_callback(file_obj.read(8192)), b""),
        )

        response.raise_for_status()
        return response.json()


class TUIFileTransfer(FileTransferBase):
    """Terminal UI implementation of file transfer"""

    def download_file(self, file_name: str, output_dir: None = None) -> str:
        pbar = None

        def progress_callback(current: int, total: int):
            nonlocal pbar
            if pbar is None and total > 0:
                pbar = tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=f"Downloading {file_name}",
                )
            if pbar:
                pbar.n = current
                pbar.refresh()

        self.set_progress_callback(progress_callback)
        try:
            result = super().download_file(file_name, output_dir)
            if pbar:
                pbar.close()
            return result
        except:
            if pbar:
                pbar.close()
            raise

    def upload_file(self, file_path: str) -> dict:
        pbar = None

        def progress_callback(current: int, total: int):
            nonlocal pbar
            if pbar is None and total > 0:
                pbar = tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=f"Uploading {file_path}",
                )
            if pbar:
                pbar.n = current
                pbar.refresh()

        self.set_progress_callback(progress_callback)
        try:
            result = super().upload_file(file_path)
            if pbar:
                pbar.close()
            return result
        except:
            if pbar:
                pbar.close()
            raise


class TUI(cmd.Cmd):
    """Command-line interface for file transfer operations"""

    intro = "Welcome to the File Transfer TUI. Type help or ? to list commands."
    prompt = "(file-transfer) "

    def __init__(self, file_transfer: TUIFileTransfer):
        super().__init__()
        self.file_transfer = file_transfer

    def do_list(self, arg):
        """List files on the server: list"""
        try:
            files = self.file_transfer.list_files()
            if not files:
                print("No files found on the server.")
                return

            for file_info in files:
                print(f"{file_info['name']}\t{file_info['size']} bytes")
        except Exception as e:
            print(f"Error listing files: {e}")

    def do_download(self, arg):
        """Download a file from the server: download <file_name>"""
        args = arg.split()
        if len(args) < 1:
            print("Usage: download <file_name>")
            return

        file_name = args[0]
        output_dir = args[1] if len(args) > 1 else None

        try:
            result = self.file_transfer.download_file(file_name, output_dir)
            print(f"Downloaded {file_name} to {result}")
        except Exception as e:
            print(f"Error downloading file: {e}")

    def do_upload(self, arg):
        """Upload a file to the server: upload <file_path>"""
        args = arg.split()
        if len(args) < 1:
            print("Usage: upload <file_path>")
            return

        file_path = args[0]
        if not os.path.exists(file_path):
            print("File does not exist.")
            return

        try:
            result = self.file_transfer.upload_file(file_path)
            print(f"Uploaded {file_path}: {result}")
        except Exception as e:
            print(f"Error uploading file: {e}")

    def do_exit(self, arg):
        """Exit the TUI: exit"""
        print("Exiting...")
        return True

    def do_quit(self, arg):
        """Exit the TUI: quit"""
        return self.do_exit(arg)


def tui(server: str, token: str):
    file_transfer = TUIFileTransfer(server, token)
    TUI(file_transfer).cmdloop()


if __name__ == "__main__":
    server_url = "http://127.0.0.1:23536"

    username = input("Enter your username: ")
    password = input("Enter your password: ")

    token = generate_token(username, password)
    print(f"Generated token: {token}")
    tui(server_url, token)
