import customtkinter as ctk
import threading
import tkinter as tk
from tkinter import StringVar
from tkinter import filedialog, scrolledtext
from RatingsToPlexRatingsController import RatingsToPlexRatingsController

# Set the version number
VERSION = '2.1.0'

class IMDbRatingsToPlexRatingsApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.controller = RatingsToPlexRatingsController(
            log_callback=self.log_message)
        self.selected_file_path = None  # To store the selected file path

        # Server selection variable
        self.server_var = tk.StringVar(value="Select a server")
        self.server_var.trace_add(
            "write", self.on_server_selection_change)  # Attach listener

        self.library_var = tk.StringVar(value="Select a library")
        self.library_var.trace_add("write", self.on_library_selection_change)

        self.title(f'IMDb Ratings To Plex Ratings v{VERSION}')
        self.geometry("550x600")  # Increased height for the log output
        self.resizable(False, False)
        self.font = ("MS Sans Serif", 12, "bold")

        # Initialize radio_value here
        # Default value set to "IMDb"
        self.radio_value = StringVar(value="IMDb")

        # To keep track of servers for which libraries have been loaded
        self.processed_servers = set()

        # Checkbox state variables
        self.movie_var = tk.BooleanVar(value=True)
        self.tv_series_var = tk.BooleanVar(value=True)
        self.tv_mini_series_var = tk.BooleanVar(value=True)
        self.tv_movie_var = tk.BooleanVar(value=True)
        
        # Checkbox for marking watched status
        self.mark_watched_var = tk.BooleanVar(value=False)

        # Create widgets
        self.setup_ui()

    def setup_ui(self):
        self.login_button = ctk.CTkButton(
            self, text="Login to Plex", command=self.login_to_plex)
        self.login_button.pack(pady=10)

        # Server dropdown menu setup
        self.server_menu = ctk.CTkOptionMenu(
            self,
            variable=self.server_var,
            values=[""]  # Initial placeholder values
        )
        self.server_menu.pack(pady=10)

        # Library dropdown menu setup
        self.library_menu = ctk.CTkOptionMenu(
            self,
            variable=self.library_var,
            values=[""]  # Placeholder text
        )
        self.library_menu.pack(pady=10)

        # Create a frame to hold radio buttons
        self.radio_button_frame = ctk.CTkFrame(self)
        self.radio_button_frame.pack(pady=10)

        # Radio button setup within the frame using grid
        self.imdb_radio = ctk.CTkRadioButton(
            self.radio_button_frame, text="IMDb", variable=self.radio_value, value="IMDb")
        self.imdb_radio.grid(row=0, column=0, padx=10)

        self.letterboxd_radio = ctk.CTkRadioButton(
            self.radio_button_frame, text="Letterboxd", variable=self.radio_value, value="Letterboxd")
        self.letterboxd_radio.grid(row=0, column=1, padx=10)

        self.select_file_button = ctk.CTkButton(
            self, text="Select CSV File", command=self.select_file)
        self.select_file_button.pack(pady=10)

        # Create a frame to hold checkboxes
        self.checkbox_frame = ctk.CTkFrame(self)
        self.checkbox_frame.pack(pady=10)

        # Checkbox setup within the frame using grid
        self.movie_checkbox = ctk.CTkCheckBox(
            self.checkbox_frame, text="Movie", variable=self.movie_var)
        self.movie_checkbox.grid(row=0, column=0, padx=10)

        self.tv_series_checkbox = ctk.CTkCheckBox(
            self.checkbox_frame, text="TV Series", variable=self.tv_series_var)
        self.tv_series_checkbox.grid(row=0, column=1, padx=10)

        self.tv_mini_series_checkbox = ctk.CTkCheckBox(
            self.checkbox_frame, text="TV Mini Series", variable=self.tv_mini_series_var)
        self.tv_mini_series_checkbox.grid(row=0, column=2, padx=10)

        self.tv_movie_checkbox = ctk.CTkCheckBox(
            self.checkbox_frame, text="TV Movie", variable=self.tv_movie_var)
        self.tv_movie_checkbox.grid(row=0, column=3, padx=10)
        
        # Checkbox for marking watched status
        self.watched_checkbox = ctk.CTkCheckBox(
            self,
            text="Mark as watched if rating is imported",
            variable=self.mark_watched_var
        )
        self.watched_checkbox.pack(pady=10)

        # Update libraries button setup
        self.startUpdate_button = ctk.CTkButton(
            self, text="Update Plex Ratings", command=self.update_ratings)
        self.startUpdate_button.pack(pady=10)

        # Log display setup with a scrollable text widget
        self.log_textbox = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            height=10,
            state='disabled',
            font=("MS Sans Serif", 10),
            bg="#2b2b2b",  # Dark gray background to match the dark theme of customtkinter
            fg="white",  # White text
            insertbackground="white",  # Ensures the cursor is white in the text box
            borderwidth=0,  # Removes the border to blend with customtkinter
        )
        self.log_textbox.pack(pady=10, fill=tk.BOTH, expand=True)

    def select_file(self):
        self.selected_file_path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if self.selected_file_path:
            self.log_message(f"Selected file: {self.selected_file_path}")
        else:
            self.log_message("No file selected.")

    def on_server_selection_change(self, *args):
        selected_server = self.server_var.get()
        if selected_server == "Select a server":
            self.log_message("Please select a valid server.")
        else:
            self.log_message(f"Server selected: {selected_server}")
            libraries = self.controller.get_libraries(selected_server)
            self.update_libraries_dropdown(libraries)

    def on_library_selection_change(self, *args):
        selected_library = self.library_var.get()
        self.log_message(f"Library selected: {selected_library}")

    def update_libraries_dropdown(self, libraries):
        if libraries:
            self.library_menu.configure(values=libraries)
            self.log_message(
                "Libraries fetched successfully. Please select a library.")
        else:
            self.log_message("No libraries found for the selected server.")

    def update_ratings(self):
        # Disable UI elements
        self._set_ui_state('disabled')
        # Start the background thread
        threading.Thread(target=self._update_ratings_thread,
                         daemon=True).start()

    def _update_ratings_thread(self):
        selected_library = self.library_var.get()
        filepath = self.selected_file_path
        if not filepath or selected_library == "Select a library":
            self.log_message("Please select a file and a library first.")
            # Ensure the UI elements are re-enabled even when returning early
            self.after(0, self._set_ui_state, 'normal')
            return

        # Determine the source (IMDb or Letterboxd)
        if self.radio_value.get() == "IMDb":
            self.log_message("Starting update from IMDb...")
        elif self.radio_value.get() == "Letterboxd":
            self.log_message("Starting update from Letterboxd...")

        values = {
            "-IMDB-": self.radio_value.get() == "IMDb",
            "-LETTERBOXD-": self.radio_value.get() == "Letterboxd",
            "-MOVIE-": self.movie_var.get(),
            "-TVSERIES-": self.tv_series_var.get(),
            "-TVMINISERIES-": self.tv_mini_series_var.get(),
            "-TVMOVIE-": self.tv_movie_var.get(),
            "-WATCHED-": self.mark_watched_var.get()
        }

        # Call controller to update ratings and pass the log_message function to log each movie update
        self.controller.update_ratings(filepath, selected_library, values)

        # Re-enable the UI elements on the main thread
        self.after(0, self._set_ui_state, 'normal')

    def log_message(self, message):
        self.log_textbox.configure(state='normal')
        self.log_textbox.insert(tk.END, message + '\n')
        self.log_textbox.configure(state='disabled')
        self.log_textbox.see(tk.END)  # Auto-scroll to the end

    def _set_ui_state(self, state):
        # Disable or enable UI elements
        self.startUpdate_button.configure(state=state)
        self.select_file_button.configure(state=state)
        self.server_menu.configure(state=state)
        self.library_menu.configure(state=state)
        self.imdb_radio.configure(state=state)
        self.letterboxd_radio.configure(state=state)
        self.movie_checkbox.configure(state=state)
        self.tv_series_checkbox.configure(state=state)
        self.tv_mini_series_checkbox.configure(state=state)
        self.tv_movie_checkbox.configure(state=state)
        self.login_button.configure(state=state)

    def login_to_plex(self):
        # Call the login method with the UI update callback
        threading.Thread(target=self._login_to_plex_thread,
                         daemon=True).start()

    def _login_to_plex_thread(self):
        self.controller.login_and_fetch_servers(self.update_servers_ui)

    def update_servers_ui(self, servers, success):
        if success:
            if servers:
                self.server_menu.configure(values=servers)
                self.log_message(
                    "Servers fetched successfully. Please select a server.")
            else:
                self.log_message("No servers found.")
        else:
            self.log_message(
                "Failed to fetch servers. Please try logging in again.")


if __name__ == "__main__":
    app = IMDbRatingsToPlexRatingsApp()
    app.mainloop()
