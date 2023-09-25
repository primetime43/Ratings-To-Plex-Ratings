import csv
import webbrowser
import PySimpleGUI as sg
import threading
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Initialize an empty dictionary to store the resources
resources_dict = {}

# Set the version number
VERSION = '1.2'

# Create a GUI window
layout = [
    [sg.Button("Login to Plex", key='-LOGIN-')],
    [sg.Text("Plex Server"), sg.Combo([], key='-SERVER-', enable_events=True, readonly=True, size=(20,10))],
    [sg.Text("Plex Library"), sg.Combo([], key='-LIBRARY-', enable_events=True, readonly=True, size=(20,10))],
    [sg.Radio('IMDb', "RADIO1", default=True, key='-IMDB-', enable_events=True), sg.Radio('Letterboxd', "RADIO1", key='-LETTERBOXD-', enable_events=True)],
    [sg.Text("Select a CSV file"), sg.Input(key='-CSV-'), sg.FileBrowse()],  # Add key='-CSV-' to the input element
    [sg.Checkbox('Movie', key='-MOVIE-', default=True), 
     sg.Checkbox('TV Series', key='-TVSERIES-', default=True), 
     sg.Checkbox('TV Mini Series', key='-TVMINISERIES-', default=True), 
     sg.Checkbox('TV Movie', key='-TVMOVIE-', default=True)],
    [sg.Button("Update Plex Ratings", key='OK', disabled=True)],  # Disable the button initially
    [sg.ProgressBar(1000, orientation='h', size=(20, 20), key='-PROGRESS-')],  # Progress bar
    [sg.Multiline(default_text='', key='-LOG-', size=(60, 10), autoscroll=True, disabled=True)]  # Log window
]

window = sg.Window(f'IMDb Ratings To Plex Ratings v{VERSION} - Not Logged In', layout)

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
    library_names = [library.title for library in server.library.sections()]
    window['-LIBRARY-'].update(values=library_names)
    window['OK'].update(disabled=False)  # Enable the update button

# Function to update ratings and progress bar
def update_ratings(filepath, progress_bar, values):
    global server  # Access the global server variable
    
    # Get the selected library section
    selected_library = values['-LIBRARY-']
    library_section = server.library.section(selected_library)

    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            csv_reader = csv.DictReader(file)
            
            if values['-IMDB-']:  # If IMDb is selected
                selected_media_types = []
                if values['-MOVIE-']:
                    selected_media_types.append('movie')
                if values['-TVSERIES-']:
                    selected_media_types.append('tvSeries')
                if values['-TVMINISERIES-']:
                    selected_media_types.append('tvMiniSeries')
                if values['-TVMOVIE-']:
                    selected_media_types.append('tvMovie')
                
                movies_data = [row for row in csv_reader if row['Title Type'] in selected_media_types]
                total_movies = len(movies_data)
                total_updated_movies = 0
                
                # Create guidLookup dictionary for faster performance
                guidLookup = {}
                for item in library_section.all():
                    guidLookup[item.guid] = item
                    guidLookup.update({guid.id: item for guid in item.guids})
                
                for i, movie in enumerate(movies_data):
                    your_rating = float(movie['Your Rating'])
                    plex_rating = your_rating / 2
                    
                    imdb_id = movie['Const']
                    found_movie = guidLookup.get(f'imdb://{imdb_id}')
                    
                    if found_movie:
                        found_movie.rate(rating=your_rating)
                        log_message(window, f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}.')
                        total_updated_movies += 1
                        
            elif values['-LETTERBOXD-']:  # If Letterboxd is selected
                movies_data = []
                seen_movies = set()

                for row in csv_reader:
                    if not row['Name'] or not row['Year'] or not row['Rating']:
                        continue
                    movie_key = (row['Name'], row['Year'])
                    if movie_key not in seen_movies:
                        movies_data.append(row)
                        seen_movies.add(movie_key)

                total_movies = len(movies_data)
                total_updated_movies = 0
                
                # Optimized: Preprocess library data
                library_movies = {(item.title, str(item.year)): item for item in library_section.all()}
                
                # Iterate over movies_data list
                for i, movie in enumerate(movies_data):
                    try:
                        name = movie['Name']
                        year = movie['Year']
                        library_movie = library_movies.get((name, year))
                        
                        if not library_movie:
                            #log_message(window, f'Movie "{name} ({year})" not found in Plex library.')
                            continue  # Skip to the next iteration
                        
                        rating_str = movie['Rating']
                        if not rating_str.replace('.', '', 1).isdigit():
                            log_message(window, f'Invalid rating "{rating_str}" for "{name} ({year})". Skipping.')
                            continue
                        
                        your_rating = float(rating_str)
                        
                        # Rate the movie
                        library_movie.rate(rating=your_rating)
                        log_message(window, f'Updated Plex rating for "{library_movie.title} ({library_movie.year})" to {your_rating}.')
                        total_updated_movies += 1
                    except Exception as e:
                        log_message(window, f'Error processing "{name} ({year})": {str(e)}. Skipping.')

                
            # Progress bar
            for i, movie in enumerate(movies_data):
                progress = int(((i+1) / total_movies) * 1000)
                progress_bar.update_bar(progress)
                
            sg.popup('Success', f'Found {total_movies} media items in the CSV file. {total_updated_movies} Plex ratings updated.')
    except FileNotFoundError:
        sg.popup('Error', 'File not found')

# List to store movie data from the CSV file
movies_data = []

while True:
    event, values = window.read()

    # If user closes window or clicks cancel
    if event == sg.WINDOW_CLOSED or event == 'Cancel':
        break

    # Check the state of the radio buttons and adjust the UI accordingly
    if values['-IMDB-']:  # if IMDb is selected
        window['-MOVIE-'].update(value=True, disabled=False)  # Enable and Select Movie Checkbox
        window['-TVSERIES-'].update(value=True, disabled=False)  # Enable and Select TV Series Checkbox
        window['-TVMINISERIES-'].update(value=True, disabled=False)  # Enable and Select TV Mini Series Checkbox
        window['-TVMOVIE-'].update(value=True, disabled=False)  # Enable and Select TV Movie Checkbox
    elif values['-LETTERBOXD-']:  # if Letterboxd is selected
        window['-MOVIE-'].update(value=True, disabled=False)  # Enable and Select Movie Checkbox
        window['-TVSERIES-'].update(value=False, disabled=True)  # Unselect and Disable TV Series Checkbox
        window['-TVMINISERIES-'].update(value=False, disabled=True)  # Unselect and Disable TV Mini Series Checkbox
        window['-TVMOVIE-'].update(value=False, disabled=True)  # Unselect and Disable TV Movie Checkbox

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
                resources = [resource for resource in plex_account.resources() if resource.owned and resource.connections and resource.provides == 'server']
                # Update the resources_dict and servers list
                for resource in resources:
                    if resource.connections:
                        server_name = f"{resource.name} ({resource.connections[0].address})"
                    else:
                        server_name = f"{resource.name} (No Available Connections)"
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
            update_ratings(filepath, progress_bar, values) # gives access to the values dictionary, and it can use the values of the different elements in the GUI, such as radio buttons, checkboxes, etc

window.close()