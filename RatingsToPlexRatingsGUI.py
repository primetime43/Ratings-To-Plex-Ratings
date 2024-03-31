import customtkinter as ctk
import threading
import tkinter as tk
from tkinter import StringVar
from tkinter import filedialog
from RatingsToPlexRatingsController import RatingsToPlexRatingsController

# Set the version number
VERSION = '2.0.0'

class IMDbRatingsToPlexRatingsApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.controller = RatingsToPlexRatingsController(log_callback=self.log_message)
        self.selected_file_path = None  # To store the selected file path
        
        # Server selection variable
        self.server_var = tk.StringVar(value="Select a server")
        self.server_var.trace_add("write", self.on_server_selection_change)  # Attach listener
        
        self.library_var = tk.StringVar(value="Select a library")
        self.library_var.trace_add("write", self.on_library_selection_change)
        
        self.title(f'IMDb Ratings To Plex Ratings v{VERSION}')
        self.geometry("550x450")
        self.resizable(False, False)
        self.font = ("MS Sans Serif", 12, "bold")
        
        # Initialize radio_value here
        self.radio_value = StringVar(value="IMDb")  # Default value set to "IMDb"
        
        self.processed_servers = set()  # To keep track of servers for which libraries have been loaded

        # Checkbox state variables
        self.movie_var = tk.BooleanVar(value=True)
        self.tv_series_var = tk.BooleanVar(value=True)
        self.tv_mini_series_var = tk.BooleanVar(value=True)
        self.tv_movie_var = tk.BooleanVar(value=True)
        
        # Create widgets
        self.setup_ui()

    def setup_ui(self):
        self.login_button = ctk.CTkButton(self, text="Login to Plex", command=self.login_to_plex)
        self.login_button.pack(pady=10)

        # Server dropdown menu setup
        self.server_menu = ctk.CTkOptionMenu(
            self,
            variable=self.server_var,
            values=[""],  # Initial placeholder values
            command=self.on_server_selection_change  # Assign the callback function directly
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
        self.imdb_radio = ctk.CTkRadioButton(self.radio_button_frame, text="IMDb", variable=self.radio_value, value="IMDb")
        self.imdb_radio.grid(row=0, column=0, padx=10)

        self.letterboxd_radio = ctk.CTkRadioButton(self.radio_button_frame, text="Letterboxd", variable=self.radio_value, value="Letterboxd")
        self.letterboxd_radio.grid(row=0, column=1, padx=10)
        
        self.select_file_button = ctk.CTkButton(self, text="Select CSV File", command=self.select_file)
        self.select_file_button.pack(pady=10)
        
        # Create a frame to hold checkboxes
        self.checkbox_frame = ctk.CTkFrame(self)
        self.checkbox_frame.pack(pady=10)

        # Checkbox setup within the frame using grid
        self.movie_checkbox = ctk.CTkCheckBox(self.checkbox_frame, text="Movie", variable=self.movie_var)
        self.movie_checkbox.grid(row=0, column=0, padx=10)

        self.tv_series_checkbox = ctk.CTkCheckBox(self.checkbox_frame, text="TV Series", variable=self.tv_series_var)
        self.tv_series_checkbox.grid(row=0, column=1, padx=10)

        self.tv_mini_series_checkbox = ctk.CTkCheckBox(self.checkbox_frame, text="TV Mini Series", variable=self.tv_mini_series_var)
        self.tv_mini_series_checkbox.grid(row=0, column=2, padx=10)

        self.tv_movie_checkbox = ctk.CTkCheckBox(self.checkbox_frame, text="TV Movie", variable=self.tv_movie_var)
        self.tv_movie_checkbox.grid(row=0, column=3, padx=10)
        
        # Update libraries button setup
        self.startUpdate_button = ctk.CTkButton(self, text="Update Plex Ratings", command=self.update_ratings)
        self.startUpdate_button.pack(pady=10)
        
        # Log display setup
        self.log_label = ctk.CTkLabel(self, text="", wraplength=500)
        self.log_label.pack(pady=10)
    
    def update_ratings(self):
        # Disable UI elements
        self._set_ui_state('disabled')
        # Start the background thread
        threading.Thread(target=self._update_ratings_thread, daemon=True).start()
    
    def _update_ratings_thread(self):
        selected_library = self.library_var.get()
        filepath = self.selected_file_path
        if not filepath or selected_library == "Select a library":
            self.log_message("Please select a file and a library first.")
            return

        values = {
            "-IMDB-": self.radio_value.get() == "IMDb",
            "-LETTERBOXD-": self.radio_value.get() == "Letterboxd",
            "-MOVIE-": self.movie_var.get(),
            "-TVSERIES-": self.tv_series_var.get(),
            "-TVMINISERIES-": self.tv_mini_series_var.get(),
            "-TVMOVIE-": self.tv_movie_var.get()
        }

        self.controller.update_ratings(filepath, selected_library, values)
        # re-enable the UI elements on the main thread
        self.after(0, self._set_ui_state, 'normal')

    def update_servers_ui(self, servers, success):
        def update():
            if success and servers:
                self.server_menu.configure(values=servers)
                self.log_message("Servers fetched successfully. Please select a server.")
            else:
                self.log_message("Failed to fetch servers.")
        self.after(0, update)
        
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
    
    def on_server_selection_change(self, *args):
        selected_server = self.server_var.get()
        # Skip if this server's libraries have already been loaded or if it's a placeholder value
        if selected_server in self.processed_servers or selected_server in ["Select a server", "Loading servers..."]:
            return
        #print(f"Server selected: {selected_server}")
        libraries = self.controller.get_libraries(selected_server)
        self.update_libraries_dropdown(libraries)
        self.processed_servers.add(selected_server)  # Mark this server as processed
        
    def on_library_selection_change(self, *args):
        selected_library = self.library_var.get()
        #print(f"Library selected: {selected_library}")

    def update_libraries_dropdown(self, libraries):
        if libraries:
            # Update the dropdown with the new list of libraries
            self.library_menu.configure(values=libraries)
            self.log_message("Libraries fetched successfully. Please select a library.")
        else:
            # If no libraries were found, indicate so
            self.library_var.set(None)

    def select_file(self):
        filepath = filedialog.askopenfilename(title="Select a CSV Ratings file", filetypes=(("CSV files", "*.csv"), ("All files", "*.*")))
        if filepath:
            # Handle the selected file (for example, store it in an instance variable or update the UI to show the selected file path)
            #print("Selected file:", filepath)
            self.selected_file_path = filepath 
            self.log_message("CSV file loaded successfully.")


    def login_to_plex(self):
        # Call the login method with the UI update callback
        threading.Thread(target=self._login_to_plex_thread, daemon=True).start()
                
    def _login_to_plex_thread(self):
        self.controller.login_and_fetch_servers(self.update_servers_ui)

    def log_message(self, message):
        # Update the log label with the new message
        self.log_label.configure(text=message)

if __name__ == "__main__":
    app = IMDbRatingsToPlexRatingsApp()
    app.mainloop()
