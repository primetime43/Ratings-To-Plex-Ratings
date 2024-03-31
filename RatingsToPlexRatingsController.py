import csv
import datetime
import webbrowser
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

class PlexConnection:
    def __init__(self, account, server, resources):
        self.account = account
        self.server = server
        self.resources = resources

    def get_servers(self):
        # Return a list of server names
        return [resource.name for resource in self.resources]

    def get_libraries(self):
        # Return a list of library names from the connected server
        if self.server:
            return [section.title for section in self.server.library.sections()]
        return []
    
    def switch_to_server(self, server_name):
        # Example logic to switch the server; adjust based on your application's needs
        try:
            # Find the server resource by name
            resource = next((res for res in self.resources if res.name == server_name), None)
            if resource:
                self.server = self.account.resource(resource.name).connect()
                return True
        except Exception as e:
            print(f"Error switching server: {e}")
        return False

class RatingsToPlexRatingsController:
    def __init__(self, server=None, log_callback=None):
        self.plex_connection = None  # This will hold a PlexConnection object
        self.log_callback = log_callback

    def log_message(self, message, log_filename):
        # Get the current datetime to timestamp the log
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # Construct the full log message with timestamp
        full_message = f"{timestamp} - {message}\n"
        
        # If a callback is provided, call it with the message
        if self.log_callback:
            self.log_callback(full_message)
        else:
            print(full_message)  # Fallback to printing to console if no callback is provided
        
        # Append the message to the provided log file
        with open(log_filename, 'a') as log_file:
            log_file.write(full_message)

    def login_and_fetch_servers(self, update_ui_callback):
        headers = {'X-Plex-Client-Identifier': 'unique_client_identifier'}
        pinlogin = MyPlexPinLogin(headers=headers, oauth=True)
        oauth_url = pinlogin.oauthUrl()
        webbrowser.open(oauth_url)
        pinlogin.run(timeout=120)
        pinlogin.waitForLogin()
        if pinlogin.token:
            plex_account = MyPlexAccount(token=pinlogin.token)
            resources = [resource for resource in plex_account.resources() if resource.owned and resource.connections and resource.provides == 'server']
            servers = [resource.name for resource in resources]
            if servers:
                # Just create a PlexConnection object without connecting to a specific server
                self.plex_connection = PlexConnection(plex_account, None, resources)  # Pass None for the server since we're not connecting yet
                # Callback with server names and success=True
                update_ui_callback(servers=servers, success=True)
            else:
                # No servers found, callback with success=False
                update_ui_callback(servers=None, success=False)
        else:
            # Failed to log in, callback with success=False
            update_ui_callback(servers=None, success=False)

            
    def get_servers(self):
        if self.plex_connection:
            return self.plex_connection.get_servers()
        return []

    def get_libraries(self, server_name):
        # Assuming PlexConnection has a method to switch to a server by name
        if self.plex_connection.switch_to_server(server_name):
            return self.plex_connection.get_libraries()
        else:
            self.log_message(f"Failed to switch to server: {server_name}")
            return []

    def update_ratings(self, filepath, selected_library, values):
        # Generate a unique log file name for this run at the beginning of update_ratings call
        now = datetime.datetime.now()
        log_filename = f"RatingsUpdateLog_{now.strftime('%Y%m%d_%H%M%S')}.log"
        
        # Logging the parameters
        values_str = ", ".join(f"{key}: {value}" for key, value in values.items())
        self.log_message(f"Starting update_ratings with parameters - Filepath: {filepath}, Selected Library: {selected_library}, Values: {values_str}", log_filename)
        
        if not self.plex_connection or not self.plex_connection.server:
            self.log_message('Error: Not connected to a Plex server')
            return False

        library_section = self.plex_connection.server.library.section(selected_library)
        if not library_section:
            self.log_message(f'Error: Library section {selected_library} not found')
            return False

        # Process the CSV file and update ratings
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)

                if values['-IMDB-']:
                    return self.update_ratings_from_imdb(csv_reader, library_section, values, log_filename)
                elif values['-LETTERBOXD-']:
                    return self.update_ratings_from_letterboxd(csv_reader, library_section, values, log_filename)
        except FileNotFoundError:
            self.log_message('Error: File not found', log_filename)
            return False
        except Exception as e:
            self.log_message(f'Error processing CSV: {e}', log_filename)
            return False

    def update_ratings_from_imdb(self, csv_reader, library_section, values, log_filename):
        selected_media_types = self._get_selected_media_types(values)
        total_movies = 0
        total_updated_movies = 0

        # Create a dictionary for faster lookups
        guidLookup = {item.guid: item for item in library_section.all()}
        guidLookup.update({guid.id: item for item in library_section.all() for guid in item.guids})

        for movie in csv_reader:
            if movie['Title Type'] not in selected_media_types:
                continue

            imdb_id = movie['Const']
            your_rating = float(movie['Your Rating'])
            plex_rating = your_rating # Plex on uses a 10-point scale on the backend, but uses out of 5 in the UI
            found_movie = guidLookup.get(f'imdb://{imdb_id}')

            if found_movie:
                found_movie.rate(rating=plex_rating)
                self.log_message(f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}.', log_filename)
                total_updated_movies += 1
            total_movies += 1

        self.log_message(f'Success: Found {total_movies} media items in the CSV file. {total_updated_movies} Plex ratings updated.', log_filename)
        return True

    def update_ratings_from_letterboxd(self, csv_reader, library_section, values, log_filename):
        total_movies = 0
        total_updated_movies = 0

        # Preprocess library data for faster lookups
        library_movies = {(item.title, str(item.year)): item for item in library_section.all()}

        for movie in csv_reader:
            try:
                name = movie.get('Name', '').strip()
                year = movie.get('Year', '').strip()
                rating_str = movie.get('Rating', '').strip()

                if not name or not year or not rating_str:
                    continue

                your_rating = float(rating_str) * 2
                plex_rating = your_rating # Plex on uses a 10-point scale on the backend, but uses out of 5 in the UI

                search_key = (name, year)
                found_movie = library_movies.get(search_key)

                if found_movie:
                    found_movie.rate(rating=plex_rating)
                    self.log_message(f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}.', log_filename)
                    total_updated_movies += 1
            except Exception as e:
                self.log_message(f'Error processing "{name} ({year})": {str(e)}. Skipping.', log_filename)
            total_movies += 1

        self.log_message(f'Success: Found {total_movies} media items in the CSV file. {total_updated_movies} Plex ratings updated.', log_filename)
        return True

    def _get_selected_media_types(self, values):
        selected_media_types = []
        if values['-MOVIE-']:
            selected_media_types.append('movie')
        if values['-TVSERIES-']:
            selected_media_types.append('tvSeries')
        if values['-TVMINISERIES-']:
            selected_media_types.append('tvMiniSeries')
        if values['-TVMOVIE-']:
            selected_media_types.append('tvMovie')
        return selected_media_types
