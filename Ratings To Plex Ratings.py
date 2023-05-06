import csv
import webbrowser
import PySimpleGUI as sg
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Initialize an empty dictionary to store the resources
resources_dict = {}

# Create a GUI window
layout = [
    [sg.Button("Login to Plex", key='-LOGIN-')],
    [sg.Text("Plex Server"), sg.Combo([], key='-SERVER-', enable_events=True, readonly=True, size=(20,10))],
    [sg.Text("Select a CSV file"), sg.Input(), sg.FileBrowse()],
    [sg.Text("Enter movie name"), sg.Input(key='-MOVIE-')],  # Input box for movie name
    [sg.Button("Find Movie", key='-FIND-MOVIE-')],  # Button to trigger movie search
    [sg.OK(), sg.Cancel()]
]

window = sg.Window('IMDb Ratings To Plex Ratings - Not Logged In', layout)

plex_account = None
server = None  # Variable to store the selected Plex server

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
            # Look up the resource in the dictionary and connect to it
            resource = resources_dict[values['-SERVER-']]
            server = resource.connect()
            print(f"Connected to {server.friendlyName}")

    # If user clicks Find Movie button
    if event == '-FIND-MOVIE-':
        movie_name = values['-MOVIE-'].strip()  # Get the entered movie name
        if server and movie_name:
            # Search for the movie in the Plex library
            movies = server.library.section('Movies').search(title=movie_name)
            if movies:
                sg.popup('Success', f'Found {len(movies)} movies with the name "{movie_name}".')
            else:
                sg.popup('Error', f'Could not find any movies with the name "{movie_name}".')
        else:
            sg.popup('Error', 'Please select a server and enter a movie name.')

    # If user selects a file
    if event == 'OK':
        filepath = values[0]

        try:
            with open(filepath, 'r') as file:
                csv_reader = csv.reader(file)
                for row in csv_reader:
                    print(row)

        except FileNotFoundError:
            sg.popup('Error', 'File not found')

window.close()