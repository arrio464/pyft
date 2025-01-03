import cmd
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from .utils import generate_token


@dataclass
class ChunkInfo:
    start: int
    end: int
    downloaded: int = 0
    complete: bool = False


class Downloader:
    def __init__(
        self, url: str, output_file: str, num_threads: int = 4, chunk_size: int = 8192
    ):
        self.url = url
        self.output_file = output_file
        self.num_threads = num_threads
        self.chunk_size = chunk_size
        self.chunks: List[ChunkInfo] = []
        self.lock = threading.Lock()
        self.progress_lock = threading.Lock()
        self.total_size = 0
        self.downloaded = 0

    def _get_file_size(self) -> Optional[int]:
        """Try different methods to get the file size."""
        # First try a HEAD request
        response = requests.head(self.url, allow_redirects=True)
        size = response.headers.get("content-length")
        if size and size != "0" and size != "357":
            return int(size)

        # If HEAD doesn't work, try a GET request with stream
        print("HEAD request didn't provide file size. Trying GET request...")
        response = requests.get(self.url, stream=True, allow_redirects=True)
        size = response.headers.get("content-length")
        if size:
            response.close()
            return int(size)

        # If still no size, we'll need to download the file first
        print("Server didn't provide file size. Will download single-threaded first...")
        return None

    def _single_thread_download(self) -> int:
        """Download the file using a single thread and return the file size."""
        temp_file = f"{self.output_file}.temp"
        downloaded_size = 0

        with requests.get(self.url, stream=True) as response:
            response.raise_for_status()
            with open(temp_file, "wb") as f:
                for chunk in response.iter_content(chunk_size=self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        print(
                            f"\rDownloaded: {downloaded_size} bytes", end="", flush=True
                        )

        # Move temp file to final location
        if os.path.exists(self.output_file):
            os.remove(self.output_file)
        os.rename(temp_file, self.output_file)
        print(f"\nSingle-thread download complete. File size: {downloaded_size} bytes")
        return downloaded_size

    def _load_progress(self) -> Dict[int, int]:
        """Load download progress from progress file if it exists."""
        progress_file = f"{self.output_file}.progress"
        if os.path.exists(progress_file):
            try:
                with open(progress_file, "r") as f:
                    return {
                        int(chunk): int(pos)
                        for line in f
                        for chunk, pos in [line.strip().split(":")]
                    }
            except:
                return {}
        return {}

    def _save_progress(self):
        """Save current download progress to file."""
        progress_file = f"{self.output_file}.progress"
        with open(progress_file, "w") as f:
            for i, chunk in enumerate(self.chunks):
                f.write(f"{i}:{chunk.downloaded}\n")

    def _download_chunk(self, chunk_id: int):
        """Download a specific chunk of the file."""
        chunk = self.chunks[chunk_id]
        headers = {"Range": f"bytes={chunk.start + chunk.downloaded}-{chunk.end}"}

        try:
            response = requests.get(self.url, headers=headers, stream=True)

            # Check if server supports range requests
            if response.status_code != 206:
                raise ValueError("Server doesn't support range requests")

            with open(self.output_file, "rb+") as f:
                f.seek(chunk.start + chunk.downloaded)

                for data in response.iter_content(chunk_size=self.chunk_size):
                    if not data:
                        break

                    with self.lock:
                        f.write(data)
                        chunk.downloaded += len(data)
                        self.downloaded += len(data)

                    # Save progress periodically
                    if chunk.downloaded % (self.chunk_size * 10) == 0:
                        with self.progress_lock:
                            self._save_progress()

            chunk.complete = True

        except Exception as e:
            print(f"Error downloading chunk {chunk_id}: {str(e)}")

    def download(self):
        """Start the download process."""
        # First try to get the file size
        self.total_size = self._get_file_size()

        # If we couldn't get the file size, use single-threaded download
        if self.total_size is None:
            self.total_size = self._single_thread_download()
            print(
                "Single-threaded download completed. No need for multi-threaded resume."
            )
            return

        # Test if server supports range requests
        test_response = requests.get(self.url, headers={"Range": "bytes=0-0"})
        if test_response.status_code != 206:
            print(
                "Server doesn't support range requests. Using single-threaded download..."
            )
            self.total_size = self._single_thread_download()
            return

        print(f"Starting multi-threaded download. File size: {self.total_size} bytes")

        # Create output file if it doesn't exist
        if not os.path.exists(self.output_file):
            with open(self.output_file, "wb") as f:
                f.seek(self.total_size - 1)
                f.write(b"\0")

        # Load previous progress if any
        progress = self._load_progress()

        # Calculate chunk sizes
        chunk_size = self.total_size // self.num_threads
        for i in range(self.num_threads):
            start = i * chunk_size
            end = (
                start + chunk_size - 1
                if i < self.num_threads - 1
                else self.total_size - 1
            )
            downloaded = progress.get(i, 0)
            self.chunks.append(ChunkInfo(start, end, downloaded))
            self.downloaded += downloaded

        # Start download threads
        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            futures = []
            for i in range(self.num_threads):
                if not self.chunks[i].complete:
                    futures.append(executor.submit(self._download_chunk, i))

            # Monitor progress
            while self.downloaded < self.total_size:
                progress = (self.downloaded / self.total_size) * 100
                print(
                    f"\rProgress: {progress:.1f}% ({self.downloaded}/{self.total_size} bytes)",
                    end="",
                    flush=True,
                )
                time.sleep(0.1)
            print("\rProgress: 100.0% (complete)", flush=True)

        print("\nDownload complete!")

        # Clean up progress file
        progress_file = f"{self.output_file}.progress"
        if os.path.exists(progress_file):
            os.remove(progress_file)


class Core:
    def __init__(self, server_url: str, token: str, threads: int = 4):
        self.server_url = server_url
        self.token = token
        self.threads = threads
        self.files = self.list_files()

    def list_files(self) -> List[Dict[str, str]]:
        response = requests.get(self.server_url, params={"token": self.token})
        response.raise_for_status()
        return response.json()["files"]

    def _update_files_list(self):
        self.files = self.list_files()

    def download_file(self, file_name: str, output_dir: Optional[str] = None):
        self._update_files_list()
        output_dir = output_dir or "downloads"
        for file in self.files:
            if file["name"] == file_name:
                d = Downloader(
                    file["url"],
                    output_file=os.path.join(output_dir, file_name),
                    num_threads=self.threads,
                )
                d.download()
                return

        raise FileNotFoundError(f"File {file_name} not found")


if __name__ == "__main__":
    server_url = "http://127.0.0.1:23536"
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--username", help="Username for authentication")
    parser.add_argument("-p", "--password", help="Password for authentication")
    args = parser.parse_args()

    username = args.username or input("Enter your username: ")
    password = args.password or input("Enter your password: ")

    token = generate_token(username, password)
    print(f"Generated token: {token}")
    core = Core(server_url, token)

    while True:
        print("Available files:")
        for i, file in enumerate(core.files):
            print(f"{i}: {file['name']}")

        choice = input("Enter the number of the file you want to download: ")
        file_index = int(choice)
        file = core.files[file_index]
        core.download_file(file["name"])
