import customtkinter as ctk
import threading
import tkinter as tk
from tkinter import StringVar, filedialog, scrolledtext, messagebox
from typing import Optional
from RatingsToPlexRatingsController import RatingsToPlexRatingsController
from version import __version__


class IMDbRatingsToPlexRatingsApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title(f"IMDb Ratings To Plex Ratings v{__version__}")
        self.geometry("1000x640")
        self.minsize(900, 600)
        self.resizable(True, True)

        self.controller = RatingsToPlexRatingsController(log_callback=self.log_message)

        self.selected_file_path: Optional[str] = None
        self.server_var = tk.StringVar(value="Select a server")
        self.server_var.trace_add("write", self.on_server_selection_change)
        self.library_var = tk.StringVar(value="Select a library")
        self.library_var.trace_add("write", self.on_library_selection_change)
        self.radio_value = StringVar(value="IMDb")
        self.movie_var = tk.BooleanVar(value=True)
        self.tv_series_var = tk.BooleanVar(value=True)
        self.tv_mini_series_var = tk.BooleanVar(value=True)
        self.tv_movie_var = tk.BooleanVar(value=True)
        self.mark_watched_var = tk.BooleanVar(value=False)
        self.mark_watched_var.trace_add("write", self.on_mark_watched_change)
        self.force_overwrite_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.all_libraries_var = tk.BooleanVar(value=False)
        self.all_libraries_var.trace_add("write", self.on_all_libraries_change)
        self.file_label_var = tk.StringVar(value="No file selected")
        self.status_var = tk.StringVar(value="Ready")
        self.theme_var = tk.StringVar(value="Dark")
        self.theme_var.trace_add("write", self.on_theme_change)
        self._update_running = False

        self.setup_ui()

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0, minsize=380)
        self.grid_columnconfigure(1, weight=1)

        self.left_panel = ctk.CTkFrame(self, corner_radius=8)
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        self.left_panel.grid_rowconfigure(0, weight=1)
        self.left_panel.grid_rowconfigure(1, weight=0)
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self.left_panel, corner_radius=8)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        tab_general = self.tabview.add("General")
        tab_login = self.tabview.add("Login")
        tab_source = self.tabview.add("Source")
        tab_filters = self.tabview.add("Filters")
        tab_options = self.tabview.add("Options")

        # General Tab
        tab_general.grid_columnconfigure(0, weight=1)
        header = ctk.CTkLabel(tab_general, text="IMDb → Plex Ratings", font=("Segoe UI", 16, "bold"))
        header.grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))
        ver = ctk.CTkLabel(tab_general, text=f"v{__version__}", font=("Segoe UI", 12))
        ver.grid(row=0, column=0, sticky="e", padx=8, pady=(8, 2))
        theme_row = ctk.CTkFrame(tab_general)
        theme_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 8))
        theme_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(theme_row, text="Theme:").grid(row=0, column=0, padx=(0, 6))
        self.theme_menu = ctk.CTkOptionMenu(theme_row, values=["Dark", "Light", "System"], variable=self.theme_var, width=120)
        self.theme_menu.grid(row=0, column=1, sticky="ew")
        src_type_frame = ctk.CTkFrame(tab_general)
        src_type_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        ctk.CTkLabel(src_type_frame, text="Source Type", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(6, 2))
        self.imdb_radio = ctk.CTkRadioButton(src_type_frame, text="IMDb", variable=self.radio_value, value="IMDb")
        self.imdb_radio.grid(row=1, column=0, padx=8, pady=2, sticky="w")
        self.letterboxd_radio = ctk.CTkRadioButton(src_type_frame, text="Letterboxd", variable=self.radio_value, value="Letterboxd")
        self.letterboxd_radio.grid(row=1, column=1, padx=8, pady=2, sticky="w")

        # Login Tab
        tab_login.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab_login, text="Plex Login", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.login_button = ctk.CTkButton(tab_login, text="Login to Plex", command=self.login_to_plex)
        self.login_button.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        self.server_menu = ctk.CTkOptionMenu(tab_login, variable=self.server_var, values=[""], width=200)
        self.server_menu.grid(row=2, column=0, padx=8, pady=4, sticky="ew")
        self.library_menu = ctk.CTkOptionMenu(tab_login, variable=self.library_var, values=[""], width=200)
        self.library_menu.grid(row=3, column=0, padx=8, pady=(0, 4), sticky="ew")
        self.all_libraries_checkbox = ctk.CTkCheckBox(tab_login, text="Search ALL libraries (no library selection required)", variable=self.all_libraries_var)
        self.all_libraries_checkbox.grid(row=4, column=0, padx=8, pady=(0, 8), sticky="w")

        # Source Tab
        tab_source.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab_source, text="Source CSV", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.select_file_button = ctk.CTkButton(tab_source, text="Select CSV File", command=self.select_file)
        self.select_file_button.grid(row=1, column=0, padx=8, pady=4, sticky="ew")
        self.file_label = ctk.CTkLabel(tab_source, textvariable=self.file_label_var, anchor="w", wraplength=300)
        self.file_label.grid(row=2, column=0, padx=8, pady=(0, 8), sticky="ew")

        # Filters Tab
        tab_filters.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab_filters, text="Media Filters", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        filters_inner = ctk.CTkFrame(tab_filters)
        filters_inner.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        filters_inner.grid_columnconfigure((0, 1), weight=1)
        self.movie_checkbox = ctk.CTkCheckBox(filters_inner, text="Movie", variable=self.movie_var)
        self.movie_checkbox.grid(row=0, column=0, padx=6, pady=2, sticky="w")
        self.tv_series_checkbox = ctk.CTkCheckBox(filters_inner, text="TV Series", variable=self.tv_series_var)
        self.tv_series_checkbox.grid(row=0, column=1, padx=6, pady=2, sticky="w")
        self.tv_mini_series_checkbox = ctk.CTkCheckBox(filters_inner, text="TV Mini Series", variable=self.tv_mini_series_var)
        self.tv_mini_series_checkbox.grid(row=1, column=0, padx=6, pady=2, sticky="w")
        self.tv_movie_checkbox = ctk.CTkCheckBox(filters_inner, text="TV Movie", variable=self.tv_movie_var)
        self.tv_movie_checkbox.grid(row=1, column=1, padx=6, pady=2, sticky="w")

        # Options Tab
        tab_options.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab_options, text="Options", font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 4))
        self.watched_checkbox = ctk.CTkCheckBox(tab_options, text="Mark watched if rating imported", variable=self.mark_watched_var)
        self.watched_checkbox.grid(row=1, column=0, padx=8, pady=2, sticky="w")
        self.force_overwrite_checkbox = ctk.CTkCheckBox(tab_options, text="Force reapply ratings (ignore unchanged)", variable=self.force_overwrite_var)
        self.force_overwrite_checkbox.grid(row=2, column=0, padx=8, pady=2, sticky="w")
        self.dry_run_checkbox = ctk.CTkCheckBox(tab_options, text="Dry run (preview only)", variable=self.dry_run_var)
        self.dry_run_checkbox.grid(row=3, column=0, padx=8, pady=(2, 8), sticky="w")

        # Action Bar
        self.action_frame = ctk.CTkFrame(self.left_panel)
        self.action_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.action_frame.grid_columnconfigure(0, weight=1)
        self.startUpdate_button = ctk.CTkButton(self.action_frame, text="Update Plex Ratings", command=self.update_ratings)
        self.startUpdate_button.grid(row=0, column=0, padx=8, pady=(8, 4), sticky="ew")
        self.progress_bar = ctk.CTkProgressBar(self.action_frame, mode="indeterminate")
        self.progress_bar.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        self.progress_bar.set(0)

        # Log Panel
        self.log_frame = ctk.CTkFrame(self, corner_radius=8)
        self.log_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 10), pady=10)
        self.log_frame.grid_rowconfigure(1, weight=1)
        self.log_frame.grid_columnconfigure(0, weight=1)
        log_header = ctk.CTkLabel(self.log_frame, text="Activity Log", font=("Segoe UI", 14, "bold"))
        log_header.grid(row=0, column=0, sticky="nw", padx=12, pady=(12, 4))
        self.log_textbox = scrolledtext.ScrolledText(
            self.log_frame,
            wrap=tk.WORD,
            height=10,
            state="disabled",
            font=("Consolas", 10),
            bg="#1e1e1e",
            fg="white",
            insertbackground="white",
            borderwidth=0,
        )
        self.log_textbox.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")

        # Status Bar
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(self.status_frame, textvariable=self.status_var, anchor="w")
        self.status_label.grid(row=0, column=0, padx=10, pady=4, sticky="ew")

        self.bind("<Configure>", self._on_root_resize)

    # Event & Helper Methods
    def on_theme_change(self, *args):
        mode = self.theme_var.get().lower()
        ctk.set_appearance_mode("system" if mode == "system" else mode)

    def set_status(self, text: str):
        self.status_var.set(text)

    def on_mark_watched_change(self, *args):
        if self.mark_watched_var.get():
            messagebox.showwarning(
                "WARNING - Mark as Watched Enabled",
                "When enabled, any title that has its rating imported will be marked as watched. Use with caution."
            )

    def select_file(self):
        self.selected_file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if self.selected_file_path:
            self.log_message(f"Selected file: {self.selected_file_path}")
            display_name = self.selected_file_path.replace("\\", "/").split("/")[-1]
            self.file_label_var.set(display_name)
            self.set_status("CSV loaded. Ready to update.")
        else:
            self.log_message("No file selected.")
            self.file_label_var.set("No file selected")
            self.set_status("No file selected")

    def on_server_selection_change(self, *args):
        selected_server = self.server_var.get()
        if selected_server == "Select a server":
            return
        self.log_message(f"Server selected: {selected_server} (loading libraries...)")
        self.library_menu.configure(values=["Loading..."])
        self.set_status(f"Fetching libraries for {selected_server}...")
        self.controller.get_libraries_async(selected_server, self._on_libraries_loaded)

    def _on_libraries_loaded(self, libraries):
        def _update():
            self.update_libraries_dropdown(libraries)
        self.after(0, _update)

    def on_library_selection_change(self, *args):
        if self.all_libraries_var.get():
            return
        selected_library = self.library_var.get()
        if selected_library and selected_library != "Select a library":
            self.set_status(f"Library '{selected_library}' selected.")

    def update_libraries_dropdown(self, libraries):
        if libraries:
            self.library_menu.configure(values=libraries)
            self.set_status("Libraries loaded. Choose a library or enable all-libraries mode.")
        else:
            self.set_status("No libraries found.")

    def update_ratings(self):
        if self._update_running:
            return
        self._update_running = True
        self._set_ui_state("disabled")
        self.set_status("Updating Plex ratings...")
        self.progress_bar.start()
        threading.Thread(target=self._update_ratings_thread, daemon=True).start()

    def _update_ratings_thread(self):
        selected_library = self.library_var.get()
        filepath = self.selected_file_path
        if not filepath:
            self.log_message("Please select a file first.")
            self.after(0, self._on_update_complete, False, "Missing file.")
            return
        if not self.all_libraries_var.get() and selected_library == "Select a library":
            self.log_message("Please select a library or enable 'Search ALL libraries'.")
            self.after(0, self._on_update_complete, False, "Missing library.")
            return
        self.log_message(f"Starting update from {self.radio_value.get()}...")
        values = {
            "-IMDB-": self.radio_value.get() == "IMDb",
            "-LETTERBOXD-": self.radio_value.get() == "Letterboxd",
            "-MOVIE-": self.movie_var.get(),
            "-TVSERIES-": self.tv_series_var.get(),
            "-TVMINISERIES-": self.tv_mini_series_var.get(),
            "-TVMOVIE-": self.tv_movie_var.get(),
            "-WATCHED-": self.mark_watched_var.get(),
            "-FORCEOVERWRITE-": self.force_overwrite_var.get(),
            "-DRYRUN-": self.dry_run_var.get(),
            "-ALLLIBS-": self.all_libraries_var.get(),
        }
        success = self.controller.update_ratings(filepath, selected_library, values)
        self.after(0, self._on_update_complete, success, None)

    def _on_update_complete(self, success: bool, error_msg: Optional[str]):
        self.progress_bar.stop()
        self._set_ui_state("normal")
        self._update_running = False
        self.set_status("Update complete." if success else (error_msg or "Update failed."))

    def log_message(self, message: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert(tk.END, message + "\n")
        self.log_textbox.configure(state="disabled")
        self.log_textbox.see(tk.END)

    def _set_ui_state(self, state: str):
        widgets = [
            self.startUpdate_button,
            self.select_file_button,
            self.server_menu,
            self.library_menu,
            self.imdb_radio,
            self.letterboxd_radio,
            self.movie_checkbox,
            self.tv_series_checkbox,
            self.tv_mini_series_checkbox,
            self.tv_movie_checkbox,
            self.login_button,
            self.watched_checkbox,
            self.force_overwrite_checkbox,
            self.dry_run_checkbox,
            self.all_libraries_checkbox,
        ]
        for w in widgets:
            w.configure(state=state)
        if state == "normal" and self.all_libraries_var.get():
            self.library_menu.configure(state="disabled")

    def on_all_libraries_change(self, *args):
        if self.all_libraries_var.get():
            self.library_menu.configure(state="disabled")
            self.set_status("All libraries mode enabled.")
        else:
            self.library_menu.configure(state="normal")
            self.set_status("Select a library or enable all-libraries mode.")

    def login_to_plex(self):
        threading.Thread(target=self._login_to_plex_thread, daemon=True).start()

    def _login_to_plex_thread(self):
        self.controller.login_and_fetch_servers(self.update_servers_ui)

    def update_servers_ui(self, servers, success):
        if success and servers:
            self.server_menu.configure(values=servers)
            self.set_status("Servers loaded. Select a server.")
        elif success:
            self.set_status("No servers found.")
        else:
            self.set_status("Login failed. Retry.")

    def _on_root_resize(self, event):
        try:
            panel_w = self.left_panel.winfo_width()
            if panel_w > 150:
                self.file_label.configure(wraplength=panel_w - 70)
        except Exception:
            pass


if __name__ == "__main__":
    app = IMDbRatingsToPlexRatingsApp()
    app.mainloop()
