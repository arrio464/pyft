import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional

from pyft.client import Core


class FileTransferGUI(Core):
    def __init__(self, server_url: str, token: str, threads: int = 4):
        super().__init__(server_url, token, threads)
        self.root = tk.Tk()
        self.root.title("File Transfer Client")
        self.root.geometry("800x600")

        # Add selected_transfer attribute
        self.selected_transfer = None

        # Transfer queue and active transfers
        self.transfer_queue = queue.Queue()
        self.active_transfers: Dict[str, Dict] = {}

        self._init_ui()
        self._start_transfer_worker()

    def _init_ui(self):
        # Create main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Files list
        files_frame = ttk.LabelFrame(main_frame, text="Remote Files", padding="5")
        files_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.files_list = ttk.Treeview(
            files_frame, columns=("name", "size", "modified"), show="headings"
        )
        self.files_list.heading("name", text="Name")
        self.files_list.heading("size", text="Size")
        self.files_list.heading("modified", text="Modified")
        self.files_list.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Scrollbar for files list
        scrollbar = ttk.Scrollbar(
            files_frame, orient=tk.VERTICAL, command=self.files_list.yview
        )
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.files_list.configure(yscrollcommand=scrollbar.set)

        # Buttons
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E))

        ttk.Button(btn_frame, text="Refresh", command=self.refresh_files).grid(
            row=0, column=0, padx=5
        )
        ttk.Button(btn_frame, text="Download", command=self.start_download).grid(
            row=0, column=1, padx=5
        )
        ttk.Button(btn_frame, text="Upload", command=self.start_upload).grid(
            row=0, column=2, padx=5
        )
        ttk.Button(btn_frame, text="Stop", command=self.stop_selected_transfer).grid(
            row=0, column=3, padx=5
        )

        # Transfers frame
        transfers_frame = ttk.LabelFrame(
            main_frame, text="Active Transfers", padding="5"
        )
        transfers_frame.grid(
            row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S)
        )

        self.transfers_canvas = tk.Canvas(transfers_frame)
        self.transfers_canvas.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=3)
        main_frame.rowconfigure(2, weight=1)
        files_frame.columnconfigure(0, weight=1)
        files_frame.rowconfigure(0, weight=1)
        transfers_frame.columnconfigure(0, weight=1)
        transfers_frame.rowconfigure(0, weight=1)

    def refresh_files(self):
        self.files_list.delete(*self.files_list.get_children())
        try:
            self._update_files_list()
            for file in self.files:
                self.files_list.insert(
                    "",
                    tk.END,
                    values=(
                        file["name"],
                        self._format_size(file.get("size", 0)),
                        file.get("modified", "Unknown"),
                    ),
                )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to refresh files: {str(e)}")

    def start_download(self):
        selection = self.files_list.selection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file to download")
            return

        file_name = self.files_list.item(selection[0])["values"][0]
        transfer_id = f"download_{file_name}_{time.time()}"

        self.active_transfers[transfer_id] = {
            "type": "download",
            "file_name": file_name,
            "progress": 0,
            "speed": 0,
            "status": "preparing",
            "threads": [],
        }

        self.transfer_queue.put((transfer_id, "download", file_name))
        self._update_transfer_display()

    def start_upload(self):
        file_path = filedialog.askopenfilename()
        if not file_path:
            return

        file_name = os.path.basename(file_path)
        transfer_id = f"upload_{file_name}_{time.time()}"

        self.active_transfers[transfer_id] = {
            "type": "upload",
            "file_name": file_name,
            "progress": 0,
            "speed": 0,
            "status": "preparing",
            "threads": [],
        }

        self.transfer_queue.put((transfer_id, "upload", file_path))
        self._update_transfer_display()

    def stop_selected_transfer(self):
        if not hasattr(self, "selected_transfer") or not self.selected_transfer:
            messagebox.showwarning("Warning", "Please select a transfer to stop")
            return

        transfer = self.active_transfers.get(self.selected_transfer)
        if transfer:
            if transfer["status"] == "running":
                transfer["status"] = "paused"
                # if hasattr(transfer, "threads"):
                for thread in transfer.get("threads", []):
                    if thread.is_alive():
                        thread._pause()
            elif transfer["status"] == "paused":
                transfer["status"] = "running"
                # if hasattr(transfer, "threads"):
                for thread in transfer.get("threads", []):
                    if thread.is_alive():
                        thread._resume()

            self._update_transfer_display()

    def _start_transfer_worker(self):
        def worker():
            while True:
                try:
                    transfer_id, operation, path = self.transfer_queue.get()
                    if operation == "download":
                        self._perform_download(transfer_id, path)
                    else:
                        self._perform_upload(transfer_id, path)
                except Exception as e:
                    print(f"Transfer worker error: {e}")
                finally:
                    self.transfer_queue.task_done()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _perform_download(self, transfer_id: str, file_name: str):
        transfer = self.active_transfers[transfer_id]
        transfer["status"] = "running"
        transfer["threads"] = []

        def progress_callback(progress: float, speed: float):
            if transfer["status"] != "paused":
                transfer["progress"] = progress
                transfer["speed"] = speed
                self._update_transfer_display()

        try:
            download_thread = threading.Thread(
                target=self.download_file,
                args=(file_name,),
                kwargs={"progress_callback": progress_callback},
            )
            download_thread.start()
            transfer["threads"].append(download_thread)
            download_thread.join()

            if transfer["status"] != "paused":
                transfer["status"] = "completed"
        except Exception as e:
            if transfer["status"] != "paused":
                transfer["status"] = "failed"
                messagebox.showerror("Error", f"Download failed: {str(e)}")

        self._update_transfer_display()

    def _perform_upload(self, transfer_id: str, file_path: str):
        transfer = self.active_transfers[transfer_id]
        transfer["status"] = "running"
        transfer["pause_event"] = threading.Event()

        def progress_callback(progress: float, speed: float):
            if not transfer["pause_event"].is_set():
                transfer["progress"] = progress
                transfer["speed"] = speed
                self._update_transfer_display()

        try:
            self.upload_file(
                file_path,
                progress_callback=progress_callback,
                pause_event=transfer["pause_event"],
            )
            transfer["status"] = "completed"
        except Exception as e:
            transfer["status"] = "failed"
            messagebox.showerror("Error", f"Upload failed: {str(e)}")

        self._update_transfer_display()

    def _pause_transfer(self, transfer_id: str):
        transfer = self.active_transfers.get(transfer_id)
        if transfer and transfer.get("pause_event"):
            transfer["pause_event"].set()
            transfer["status"] = "paused"
            self._update_transfer_display()

    def _resume_transfer(self, transfer_id: str):
        transfer = self.active_transfers.get(transfer_id)
        if transfer and transfer.get("pause_event"):
            transfer["status"] = "running"
            transfer["pause_event"].clear()
            self._update_transfer_display()

    def _update_transfer_display(self):
        self.transfers_canvas.delete("all")
        y = 10

        for transfer_id, transfer in self.active_transfers.items():
            # Make the entire transfer row clickable
            row_height = 60
            fill_color = (
                "lightblue"
                if transfer_id == self.selected_transfer
                else ("lightgray" if transfer["status"] == "paused" else "white")
            )

            # Create clickable background
            self.transfers_canvas.create_rectangle(
                5,
                y - 5,
                self.transfers_canvas.winfo_width() - 5,
                y + row_height,
                fill=fill_color,
                tags=("transfer_bg", transfer_id),
            )

            # Draw transfer info
            self.transfers_canvas.create_text(
                10,
                y,
                text=f"{transfer['type'].title()}: {transfer['file_name']}",
                anchor="w",
                tags=("transfer", transfer_id),
            )

            # Draw progress bar
            bar_width = 400
            bar_height = 20
            self.transfers_canvas.create_rectangle(
                10,
                y + 20,
                10 + bar_width,
                y + 20 + bar_height,
                outline="black",
                tags=("transfer", transfer_id),
            )

            # Draw progress
            if transfer["status"] == "completed":
                transfer["progress"] = 100.0
                self.transfers_canvas.create_rectangle(
                    10,
                    y + 20,
                    10 + (bar_width * transfer["progress"]) / 100,
                    y + 20 + bar_height,
                    fill="blue" if transfer["status"] != "paused" else "gray",
                    outline="",
                    tags=("transfer", transfer_id),
                )
            else:
                # Calculate dimensions for 4 segments
                segment_width = bar_width / 4
                segment_spacing = 2
                progress_width = (segment_width * transfer["progress"]) / 100

                # Draw 4 progress segments
                for i in range(4):
                    x_start = 10 + (i * (segment_width + segment_spacing))
                    self.transfers_canvas.create_rectangle(
                        x_start,
                        y + 20,
                        x_start + progress_width - (i * segment_spacing),
                        y + 20 + bar_height,
                        fill="blue" if transfer["status"] != "paused" else "gray",
                        outline="",
                        tags=("transfer", transfer_id),
                    )

            # Draw status text
            status_text = (
                f"[{transfer['progress']:.1f}%]"
                f"[{self._format_speed(transfer['speed'])}]"
                f"[{transfer['status']}]"
            )
            self.transfers_canvas.create_text(
                10,
                y + 45,
                text=status_text,
                anchor="w",
                tags=("transfer", transfer_id),
            )

            y += 70

        # Add click handling for background rectangles
        self.transfers_canvas.tag_bind(
            "transfer_bg", "<Button-1>", lambda e: self._select_transfer(e)
        )

    def _select_transfer(self, event):
        # Find clicked transfer
        clicked = self.transfers_canvas.find_closest(event.x, event.y)
        if clicked:
            tags = self.transfers_canvas.gettags(clicked[0])
            if len(tags) >= 2 and tags[0] == "transfer_bg":
                self.selected_transfer = tags[1]
                self._update_transfer_display()

    def _format_size(self, size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _format_speed(self, speed: float) -> str:
        return f"{speed:.1f} KB/s"

    def run(self):
        self.refresh_files()
        self.root.mainloop()


class LoginGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Login")
        self.master.geometry("400x300")
        self.master.resizable(False, False)

        self.frame = ttk.Frame(self.master, padding=20)
        self.frame.pack(fill="both", expand=True)

        ttk.Label(self.frame, text="文件传输", font=("Arial", 10, "bold")).grid(
            row=0, column=0, columnspan=2, pady=10
        )

        # Server URL
        ttk.Label(self.frame, text="Server URL:", font=("Arial", 10)).grid(
            row=1, column=0, sticky="e", pady=10, padx=5
        )
        self.server_var = tk.StringVar()
        self.server_entry = ttk.Entry(
            self.frame, textvariable=self.server_var, font=("Arial", 12)
        )
        self.server_entry.grid(row=1, column=1, pady=10, padx=5)

        # Username
        ttk.Label(self.frame, text="Username:", font=("Arial", 10)).grid(
            row=2, column=0, sticky="e", pady=10, padx=5
        )
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(
            self.frame, textvariable=self.username_var, font=("Arial", 12)
        )
        self.username_entry.grid(row=2, column=1, pady=10, padx=5)

        # Password
        ttk.Label(self.frame, text="Password:", font=("Arial", 10)).grid(
            row=3, column=0, sticky="e", pady=10, padx=5
        )
        self.password_var = tk.StringVar()
        self.password_entry = ttk.Entry(
            self.frame, textvariable=self.password_var, show="*", font=("Arial", 12)
        )
        self.password_entry.grid(row=3, column=1, pady=10, padx=5)

        # Error message label (commented out in your code, uncomment if needed)
        # self.error_message = tk.StringVar()
        # self.error_label = ttk.Label(self.frame, textvariable=self.error_message, foreground="red", font=("Arial", 10))
        # self.error_label.grid(row=4, column=0, columnspan=2, pady=5)

        self.login_button = ttk.Button(self.frame, text="Login", command=self.try_login)
        self.login_button.grid(row=5, column=0, columnspan=2, pady=20)

        self.username_entry.focus()

    def try_login(self):
        url = self.server_var.get()
        username = self.username_var.get()
        password = self.password_var.get()

        # Here you would add the logic to validate the login credentials
        # For example, you could call a function that attempts to log in and returns True or False
        # If the login is successful, proceed with generating token and opening the FileTransferGUI
        if self.validate_login(url, username, password):
            from pyft.utils import generate_token

            token = generate_token(username, password)
            gui = FileTransferGUI(url, token)
            gui.run()
            self.master.destroy()  # Close the login window after successful login
        else:
            print("Wrong password or username")
            input("Press Enter to continue...")

    def validate_login(self, url, username, password):
        # Add your validation logic here
        # Return True if login is successful, otherwise return False
        return True  # Placeholder for actual validation logic


if __name__ == "__main__":
    root = tk.Tk()
    app = LoginGUI(root)
    root.mainloop()
