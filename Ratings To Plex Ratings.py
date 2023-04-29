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
    [sg.OK(), sg.Cancel()]
]

window = sg.Window('IMDb Ratings To Plex Ratings', layout)

plex_account = None

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
                resources = [resource for resource in plex_account.resources() if resource.owned]
                # Update the resources_dict and servers list
                for resource in resources:
                    server_name = f"{resource.name} ({resource.connections[0].address})"
                    resources_dict[server_name] = resource
                servers = list(resources_dict.keys())
                max_len = max(len(server) for server in servers)
                window['-SERVER-'].update(values=servers, size=(max_len, 10))
            else:
                print('Error', 'Could not log in to Plex account')
                sg.popup('Error', 'Could not log in to Plex account')
        except Exception as e:
            print('Error', f'Could not log in to Plex account: {str(e)}')
            sg.popup('Error', f'Could not log in to Plex account: {str(e)}')

    # If user selects a server
    if event == '-SERVER-':
        if plex_account:
            # Look up the resource in the dictionary and connect to it
            resource = resources_dict[values['-SERVER-']]
            server = resource.connect()
            print(f"Connected to {server.friendlyName}")

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