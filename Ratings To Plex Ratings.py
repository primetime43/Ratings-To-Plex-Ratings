import csv
import webbrowser
import PySimpleGUI as sg
import threading
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Initialize an empty dictionary to store the resources
resources_dict = {}

# Create a GUI window
layout = [
    [sg.Button("Login to Plex", key='-LOGIN-')],
    [sg.Text("Plex Server"), sg.Combo([], key='-SERVER-', enable_events=True, readonly=True, size=(20,10))],
    [sg.Text("Select a CSV file"), sg.Input(key='-CSV-'), sg.FileBrowse()],  # Add key='-CSV-' to the input element
    [sg.Button("Update Plex Movie Ratings", key='OK', disabled=True)],  # Disable the button initially
    [sg.ProgressBar(1000, orientation='h', size=(20, 20), key='-PROGRESS-')],  # Progress bar
    [sg.Multiline(default_text='', key='-LOG-', size=(60, 10), autoscroll=True, disabled=True)]  # Log window
]

window = sg.Window('IMDb Ratings To Plex Ratings - Not Logged In', layout)

plex_account = None
server = None  # Variable to store the selected Plex server

# Function to log messages to the log window
def log_message(window, message):
    window['-LOG-'].update(value=message + '\n', append=True)

# Define a function to connect to the server in a separate thread
def connect_to_server(selected_server_info, resource):
    global server  # Declare server as a global variable before assigning a value to it
    log_message(window, f'Connecting to {selected_server_info}')
    server = resource.connect()
    log_message(window, f'Connected to {selected_server_info}')
    window['OK'].update(disabled=False)  # Enable the update button

# Function to update movie ratings and progress bar
def update_ratings(filepath, progress_bar):
    global server  # Access the global server variable
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            movies_data = [row for row in csv_reader if row['Title Type'] == 'movie']
            total_movies = len(movies_data)
            
            # Get the Movies library section
            movies_section = server.library.section('Movies')
            
            # Create guidLookup dictionary for faster performance
            guidLookup = {}
            for item in movies_section.all():
                guidLookup[item.guid] = item
                guidLookup.update({guid.id: item for guid in item.guids})
            
            for i, movie in enumerate(movies_data):
                your_rating = float(movie['Your Rating'])  # Convert the rating to float
                plex_rating = your_rating / 2
                year = movie['Release Date'].split('-')[0]
                log_message(window, f'{movie["Title"]} ({year}) - Your Rating: {your_rating} --> {plex_rating} Plex Rating')
                
                # Use the getGuid method to search for the movie using its IMDb ID
                imdb_id = movie['Const']  # Extract the IMDb ID from the "Const" column
                found_movie = guidLookup.get(f'imdb://{imdb_id}')  # Search for the movie in the guidLookup dictionary
                
                if found_movie:
                    found_movie.rate(rating=your_rating)  # Use the .rate(rating) method
                    log_message(window, f'Updated Plex rating for "{found_movie.title}" to {plex_rating}.')
                else:
                    log_message(window, f'Movie "{movie["Title"]} ({year})" not found in Plex library.')
                
                # Update progress bar
                progress = int(((i+1) / total_movies) * 1000)
                progress_bar.update_bar(progress)
                
            sg.popup('Success', f'Found {total_movies} movies in the CSV file. Plex ratings updated.')
    except FileNotFoundError:
        sg.popup('Error', 'File not found')

# List to store movie data from the CSV file
movies_data = []

while True:
    event, values = window.read()

    # If user closes window or clicks cancel
    if event == sg.WINDOW_CLOSED or event == 'Cancel':
        break

    # If user clicks Login button
    if event == '-LOGIN-':
        try:
            headers = {'X-Plex-Client-Identifier': 'your_unique_client_identifier'}
            pinlogin = MyPlexPinLogin(headers=headers, oauth=True)
            oauth_url = pinlogin.oauthUrl()
            webbrowser.open(oauth_url)
            pinlogin.run(timeout=120)
            pinlogin.waitForLogin()
            if pinlogin.token:
                plex_account = MyPlexAccount(token=pinlogin.token)
                username = plex_account.username  # Get the username
                resources = [resource for resource in plex_account.resources() if resource.owned]
                # Update the resources_dict and servers list
                for resource in resources:
                    server_name = f"{resource.name} ({resource.connections[0].address})"
                    resources_dict[server_name] = resource
                servers = list(resources_dict.keys())
                max_len = max(len(server) for server in servers)
                window['-SERVER-'].update(values=servers, size=(max_len, 10))
                # Update window title to "Logged In As [username]"
                window.set_title(f'IMDb Ratings To Plex Ratings - Logged In As {username}')
            else:
                # Update window title to "Not Logged In"
                window.set_title('IMDb Ratings To Plex Ratings - Not Logged In')
                print('Error', 'Could not log in to Plex account')
                sg.popup('Error', 'Could not log in to Plex account')
        except Exception as e:
            # Update window title to "Not Logged In"
            window.set_title('IMDb Ratings To Plex Ratings - Not Logged In')
            print('Error', f'Could not log in to Plex account: {str(e)}')
            sg.popup('Error', f'Could not log in to Plex account: {str(e)}')

    # If user selects a server
    if event == '-SERVER-':
        if plex_account:
            # Get the selected server's name and IP address from the combo box
            selected_server_info = values['-SERVER-']
            
            # Look up the resource in the dictionary
            resource = resources_dict[selected_server_info]
            
            # Start a new thread to connect to the server
            connection_thread = threading.Thread(target=connect_to_server, args=(selected_server_info, resource))
            connection_thread.start()

    # If user selects a file and clicks "Update Plex Movie Ratings" button
    if event == 'OK':
        filepath = values['-CSV-']
        if not filepath:  # Check if the filepath is empty
            sg.popup('Error', 'Please select a CSV file')
        else:
            progress_bar = window['-PROGRESS-']
            update_ratings(filepath, progress_bar)  # Call the update_ratings function

window.close()