import csv
import datetime
import logging
import threading
import time
import webbrowser
from typing import Callable, List, Optional, Dict, Tuple
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount

# Performance & parallelism constants
IMDB_LAZY_LOOKUP_THRESHOLD = 300  # If number of IMDb rows to process <= this, do per-guid lookup instead of full library scan
PARALLEL_MIN_ITEMS = 600          # Activate parallel rating updates if >= this many IMDb rows (and not lazy)
PARALLEL_WORKERS = 6              # Thread pool size for parallel updates
MAX_WRITES_PER_SECOND = 0         # 0 => unlimited (disable limiter); tune if server errors appear


class _RateLimiter:
    """Simple moving-window rate limiter (thread-safe).

    Ensures no more than max_per_second operations occur in any rolling 1s window.
    Blocks (sleeping in small increments) until a slot is available.
    """

    def __init__(self, max_per_second: int):
        self.max_per_second = max_per_second
        self._timestamps = deque()
        self._lock = threading.Lock()

    def acquire(self):  # pragma: no cover (timing based)
        if self.max_per_second <= 0:
            return  # unlimited
        while True:
            with self._lock:
                now = time.perf_counter()
                while self._timestamps and now - self._timestamps[0] > 1.0:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_per_second:
                    self._timestamps.append(now)
                    return
            time.sleep(0.01)

# Configure logging
logging.basicConfig(
    filename="RatingsToPlex.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    encoding='utf-8'
)
logger = logging.getLogger(__name__)


class PlexConnection:
    """Wraps a Plex account/resources with lightweight caching for faster UI interactions."""

    def __init__(self, account, server, resources):
        self.account = account
        self.server = server
        self.resources = resources
        self._server_cache = {}  # server_name -> connected PlexServer
        self._libraries_cache = {}  # server_name -> list[str]
        self._lock = threading.Lock()
        logger.debug("PlexConnection initialized with account: %s, server: %s", account, server)

    def get_servers(self) -> List[str]:
        return [resource.name for resource in self.resources]

    def switch_to_server(self, server_name: str) -> bool:
        # Reuse cached connection if available
        with self._lock:
            if server_name in self._server_cache:
                self.server = self._server_cache[server_name]
                logger.debug("Using cached server connection for: %s", server_name)
                return True
        try:
            resource = next((res for res in self.resources if res.name == server_name), None)
            if resource:
                connected = self.account.resource(resource.name).connect(timeout=8)  # type: ignore[arg-type]
                with self._lock:
                    self._server_cache[server_name] = connected
                self.server = connected
                logger.info("Connected to server: %s", server_name)
                return True
        except Exception as e:
            logger.error("Error switching server: %s", e)
        return False

    def get_libraries(self) -> List[str]:
        if not self.server:
            logger.warning("Server is not connected. Cannot fetch libraries.")
            return []
        server_name = getattr(self.server, 'friendlyName', None) or getattr(self.server, 'name', None)
        if server_name and server_name in self._libraries_cache:
            logger.debug("Libraries cache hit for server: %s", server_name)
            return self._libraries_cache[server_name]
        try:
            libs = [section.title for section in self.server.library.sections()]
            if server_name:
                self._libraries_cache[server_name] = libs
            logger.debug("Fetched %d libraries for server %s", len(libs), server_name)
            return libs
        except Exception as e:
            logger.error("Failed to fetch libraries from server: %s", e)
            return []

    def prefetch_all_libraries_async(self, log_fn: Optional[Callable[[str], None]] = None):
        """Background warm-up of server connections and library lists for all servers."""

        def _worker():
            for res in self.resources:
                name = res.name
                if name in self._libraries_cache:
                    continue
                try:
                    start = time.perf_counter()
                    if name not in self._server_cache:
                        connected = self.account.resource(res.name).connect(timeout=8)  # type: ignore[arg-type]
                        with self._lock:
                            self._server_cache[name] = connected
                    server_obj = self._server_cache[name]
                    libs = [s.title for s in server_obj.library.sections()]
                    self._libraries_cache[name] = libs
                    duration = time.perf_counter() - start
                    if log_fn:
                        log_fn(f"Prefetched libraries for '{name}' ({len(libs)} libraries) in {duration:.2f}s")
                except Exception as e:  # pragma: no cover (best-effort prefetch)
                    if log_fn:
                        log_fn(f"Prefetch failed for '{name}': {e}")
        threading.Thread(target=_worker, daemon=True).start()


class RatingsToPlexRatingsController:
    def __init__(self, server=None, log_callback=None):
        self.plex_connection = None
        self.log_callback = log_callback
        logger.debug("RatingsToPlexRatingsController initialized")

    def log_message(self, message, log_filename):
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        full_message = f"{timestamp} - {message}\n"
        logger.info(message)
        if self.log_callback:
            self.log_callback(full_message)
    # Ensure UTF-8 so special characters in logs do not raise Windows charmap errors
        try:
            with open(log_filename, 'a', encoding='utf-8') as log_file:
                log_file.write(full_message)
        except UnicodeEncodeError:
            # Fallback: strip/replace problematic chars and retry to avoid aborting the entire run
            safe_message = full_message.encode('ascii', 'replace').decode('ascii')
            try:
                with open(log_filename, 'a', encoding='utf-8', errors='ignore') as log_file:
                    log_file.write(safe_message)
            except Exception as inner_e:  # pragma: no cover
                logger.error("Secondary log write failure (sanitized) for %s: %s", log_filename, inner_e)
        except Exception as e:  # pragma: no cover
            logger.error("Log write failure for %s: %s", log_filename, e)

    def login_and_fetch_servers(self, update_ui_callback):
        logger.info("Initiating Plex login and fetching servers")
        headers = {'X-Plex-Client-Identifier': 'unique_client_identifier'}
        pinlogin = MyPlexPinLogin(headers=headers, oauth=True)
        oauth_url = pinlogin.oauthUrl()
        webbrowser.open(oauth_url)
        pinlogin.run(timeout=120)
        pinlogin.waitForLogin()
        if pinlogin.token:
            logger.info("Plex login successful")
            plex_account = MyPlexAccount(token=pinlogin.token)
            resources = [r for r in plex_account.resources() if r.owned and r.connections and r.provides == 'server']
            servers = [r.name for r in resources]
            if servers:
                logger.info("Fetched servers: %s", servers)
                self.plex_connection = PlexConnection(plex_account, None, resources)
                # No persistent seeding; rely on live prefetch
                self.plex_connection.prefetch_all_libraries_async(log_fn=lambda m: logger.debug(m))
                update_ui_callback(servers=servers, success=True)
            else:
                logger.warning("No servers found after login")
                update_ui_callback(servers=None, success=False)
        else:
            logger.error("Plex login failed or timed out")
            update_ui_callback(servers=None, success=False)

    def get_servers(self):
        if self.plex_connection:
            return self.plex_connection.get_servers()
        logger.warning("No Plex connection found. Cannot get servers.")
        return []

    def get_libraries(self, server_name):
        if self.plex_connection.switch_to_server(server_name):
            return self.plex_connection.get_libraries()
        logger.error("Failed to switch to server: %s", server_name)
        return []

    def get_libraries_async(self, server_name: str, callback: Callable[[List[str]], None]):
        def _worker():
            libs = self.get_libraries(server_name)
            try:
                callback(libs)
            except Exception as e:  # pragma: no cover
                logger.error("Library callback error: %s", e)
        threading.Thread(target=_worker, daemon=True).start()

    # Persistent cache methods removed

    def update_ratings(self, filepath, selected_library, values):
        now = datetime.datetime.now()
        log_filename = f"RatingsUpdateLog_{now.strftime('%Y%m%d_%H%M%S')}.log"
        logger.info("Starting update_ratings with file: %s and library: %s", filepath, selected_library)
        if not self.plex_connection or not self.plex_connection.server:
            logger.error("Not connected to a Plex server")
            self.log_message('Error: Not connected to a Plex server', log_filename)
            return False
        library_section = self.plex_connection.server.library.section(selected_library)
        if not library_section:
            logger.error("Library section %s not found", selected_library)
            self.log_message(f'Error: Library section {selected_library} not found', log_filename)
            return False
        dry_run = values.get('-DRYRUN-', False)
        if dry_run:
            self.log_message('DRY RUN ENABLED: No changes will be written to Plex.', log_filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                csv_reader = csv.DictReader(file)
                if values['-IMDB-']:
                    return self.update_ratings_from_imdb(csv_reader, library_section, values, log_filename, filepath, dry_run=dry_run)
                elif values['-LETTERBOXD-']:
                    return self.update_ratings_from_letterboxd(csv_reader, library_section, values, log_filename, filepath, dry_run=dry_run)
        except FileNotFoundError:
            logger.error("CSV file not found: %s", filepath)
            self.log_message('Error: File not found', log_filename)
            return False
        except Exception as e:
            logger.error("Error processing CSV: %s", e)
            self.log_message(f'Error processing CSV: {e}', log_filename)
            return False

    def update_ratings_from_imdb(self, csv_reader, library_section, values, log_filename, source_filepath, dry_run: bool = False):
        selected_media_types = self._get_selected_media_types(values)
        logger.info("Updating IMDb ratings (lazy threshold=%d)", IMDB_LAZY_LOOKUP_THRESHOLD)
        self.log_message("Updating IMDb ratings", log_filename)

        rows = [r for r in csv_reader if r.get('Title Type') in selected_media_types]
        total_movies = len(rows)
        total_updated_movies = 0
        failures: List[Dict[str, str]] = []
        missing_id = 0
        invalid_rating = 0
        not_found = 0
        type_mismatch = 0
        rate_failed = 0
        unchanged_skipped = 0

        def imdb_type_to_plex_types(imdb_type):
            mapping = {
                'Movie': {'movie'},
                'TV Movie': {'movie'},
                'Short': {'movie'},
                'TV Series': {'show'},
                'TV Mini Series': {'show'},
                'TV Episode': {'episode'},
            }
            return mapping.get(imdb_type, set())

        use_lazy = total_movies <= IMDB_LAZY_LOOKUP_THRESHOLD
        logger.debug("IMDb rows=%d using %s strategy", total_movies, 'lazy lookup' if use_lazy else 'bulk scan')

        guidLookup = {}
        if not use_lazy:
            start = time.perf_counter()
            all_items = library_section.all()
            for item in all_items:
                if getattr(item, 'guid', None):
                    guidLookup[item.guid] = item
                for guid in getattr(item, 'guids', []) or []:
                    guidLookup[guid.id] = item
            duration = time.perf_counter() - start
            logger.debug("Built full GUID index (%d entries) in %.2fs", len(guidLookup), duration)

        preview_samples = []  # collect up to N previews (sequential lazy path)
        PREVIEW_LIMIT = 15

        # Decide if we will use parallel processing (only for non-lazy, non-dry-run large batches)
        use_parallel = (not dry_run and not use_lazy and total_movies >= PARALLEL_MIN_ITEMS)
        if use_parallel:
            self.log_message(f"Parallel IMDb update enabled: {total_movies} items, {PARALLEL_WORKERS} workers", log_filename)

        if use_parallel:
            rate_limiter = _RateLimiter(MAX_WRITES_PER_SECOND)
            force_overwrite = values.get('-FORCEOVERWRITE-', False)
            mark_watched = values.get('-WATCHED-', False)
            lock = threading.Lock()

            def worker(movie_row) -> Tuple[Dict[str, int], Optional[Dict[str, str]]]:
                local_counts = {
                    'updated': 0,
                    'missing_id': 0,
                    'invalid_rating': 0,
                    'not_found': 0,
                    'type_mismatch': 0,
                    'rate_failed': 0,
                    'unchanged_skipped': 0
                }
                failure_entry = None
                imdb_id = movie_row.get('Const')
                if not imdb_id:
                    local_counts['missing_id'] += 1
                    failure_entry = {
                        'Title': movie_row.get('Title', ''),
                        'Year': movie_row.get('Year', ''),
                        'IMDbID': '',
                        'Reason': 'Missing IMDb ID (Const)',
                        'YourRating': movie_row.get('Your Rating', ''),
                        'TitleType': movie_row.get('Title Type', '')
                    }
                    return local_counts, failure_entry
                rating_raw = movie_row.get('Your Rating', '')
                try:
                    your_rating = float((rating_raw or '').strip())
                except (ValueError, AttributeError):
                    local_counts['invalid_rating'] += 1
                    failure_entry = {
                        'Title': movie_row.get('Title', ''),
                        'Year': movie_row.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': 'Invalid rating value',
                        'YourRating': rating_raw,
                        'TitleType': movie_row.get('Title Type', '')
                    }
                    return local_counts, failure_entry
                plex_rating = your_rating
                found = guidLookup.get(f'imdb://{imdb_id}')
                if not found:
                    local_counts['not_found'] += 1
                    failure_entry = {
                        'Title': movie_row.get('Title', ''),
                        'Year': movie_row.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': 'Not found in Plex by GUID',
                        'YourRating': rating_raw,
                        'TitleType': movie_row.get('Title Type', '')
                    }
                    return local_counts, failure_entry
                expected_types = imdb_type_to_plex_types(movie_row['Title Type'])
                item_type = getattr(found, 'type', None)
                if expected_types and item_type not in expected_types:
                    local_counts['type_mismatch'] += 1
                    failure_entry = {
                        'Title': movie_row.get('Title', ''),
                        'Year': movie_row.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': f'Type mismatch (Plex={item_type})',
                        'YourRating': rating_raw,
                        'TitleType': movie_row.get('Title Type', '')
                    }
                    return local_counts, failure_entry
                # Fetch fresh for current userRating
                if getattr(found, 'ratingKey', None):
                    try:
                        fresh = library_section.fetchItem(found.ratingKey)
                        if fresh:
                            found = fresh
                    except Exception:
                        pass
                existing_rating = getattr(found, 'userRating', None)
                if not force_overwrite and existing_rating is not None:
                    try:
                        existing_rating_float = float(existing_rating)
                    except Exception:
                        existing_rating_float = existing_rating
                    if isinstance(existing_rating_float, (int, float)) and abs(existing_rating_float - plex_rating) < 0.01:
                        local_counts['unchanged_skipped'] += 1
                        return local_counts, None
                try:
                    rate_limiter.acquire()
                    found.rate(rating=plex_rating)
                    msg = f'Updated Plex rating for "{found.title} ({found.year})" to {plex_rating}'
                    self.log_message(msg, log_filename)
                    if mark_watched:
                        rate_limiter.acquire()
                        try:
                            found.markWatched()
                            self.log_message(f'Marked "{found.title} ({found.year})" as watched', log_filename)
                        except Exception as e:
                            self.log_message(f'Error marking as watched for {found.title}: {e}', log_filename)
                    local_counts['updated'] += 1
                except Exception as e:
                    local_counts['rate_failed'] += 1
                    failure_entry = {
                        'Title': getattr(found, 'title', ''),
                        'Year': getattr(found, 'year', ''),
                        'IMDbID': imdb_id,
                        'Reason': f'Rate failed: {e}',
                        'YourRating': rating_raw,
                        'TitleType': movie_row.get('Title Type', '')
                    }
                return local_counts, failure_entry

            aggregated = {
                'updated': 0,
                'missing_id': 0,
                'invalid_rating': 0,
                'not_found': 0,
                'type_mismatch': 0,
                'rate_failed': 0,
                'unchanged_skipped': 0
            }
            with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
                for counts, failure in executor.map(worker, rows):
                    for k, v in counts.items():
                        aggregated[k] += v
                    if failure:
                        failures.append(failure)
            total_updated_movies = aggregated['updated']
            missing_id = aggregated['missing_id']
            invalid_rating = aggregated['invalid_rating']
            not_found = aggregated['not_found']
            type_mismatch = aggregated['type_mismatch']
            rate_failed = aggregated['rate_failed']
            unchanged_skipped = aggregated['unchanged_skipped']
        else:
            # Existing sequential path (includes dry-run & lazy path)
            for movie in rows:
                imdb_id = movie.get('Const')
                if not imdb_id:
                    missing_id += 1
                    failures.append({
                        'Title': movie.get('Title', ''),
                        'Year': movie.get('Year', ''),
                        'IMDbID': '',
                        'Reason': 'Missing IMDb ID (Const)',
                        'YourRating': movie.get('Your Rating', ''),
                        'TitleType': movie.get('Title Type', '')
                    })
                    continue
                rating_raw = movie.get('Your Rating', '')
                try:
                    your_rating = float((rating_raw or '').strip())
                except (ValueError, AttributeError):
                    invalid_rating += 1
                    failures.append({
                        'Title': movie.get('Title', ''),
                        'Year': movie.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': 'Invalid rating value',
                        'YourRating': rating_raw,
                        'TitleType': movie.get('Title Type', '')
                    })
                    continue
                plex_rating = your_rating
                found_movie = None
                if use_lazy:
                    try:
                        results = library_section.search(guid=f'imdb://{imdb_id}')
                        if results:
                            found_movie = results[0]
                    except Exception as e:  # pragma: no cover
                        logger.debug("Lazy search error for %s: %s", imdb_id, e)
                else:
                    found_movie = guidLookup.get(f'imdb://{imdb_id}')
                if not found_movie:
                    not_found += 1
                    failures.append({
                        'Title': movie.get('Title', ''),
                        'Year': movie.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': 'Not found in Plex by GUID',
                        'YourRating': rating_raw,
                        'TitleType': movie.get('Title Type', '')
                    })
                    continue
                expected_types = imdb_type_to_plex_types(movie['Title Type'])
                item_type = getattr(found_movie, 'type', None)
                if expected_types and item_type not in expected_types:
                    skip_msg = (f'Skipped "{found_movie.title} ({getattr(found_movie, "year", "?")})" - '
                                f'type mismatch (CSV: {movie["Title Type"]}, Plex: {item_type})')
                    logger.debug(skip_msg)
                    self.log_message(skip_msg, log_filename)
                    type_mismatch += 1
                    failures.append({
                        'Title': movie.get('Title', ''),
                        'Year': movie.get('Year', ''),
                        'IMDbID': imdb_id,
                        'Reason': f'Type mismatch (Plex={item_type})',
                        'YourRating': rating_raw,
                        'TitleType': movie.get('Title Type', '')
                    })
                    continue
                force_overwrite = values.get('-FORCEOVERWRITE-', False)
                if getattr(found_movie, 'ratingKey', None):
                    try:
                        fresh = library_section.fetchItem(found_movie.ratingKey)
                        if fresh:
                            found_movie = fresh
                    except Exception as e:  # pragma: no cover
                        logger.debug('fetchItem failed for %s: %s', imdb_id, e)
                existing_rating = getattr(found_movie, 'userRating', None)
                if not force_overwrite and existing_rating is not None:
                    try:
                        existing_rating_float = float(existing_rating)
                    except Exception:
                        existing_rating_float = existing_rating
                    logger.debug('Existing rating (fresh) for %s (%s): %s incoming: %s', found_movie.title, imdb_id, existing_rating_float, plex_rating)
                    if isinstance(existing_rating_float, (int, float)) and abs(existing_rating_float - plex_rating) < 0.01:
                        unchanged_skipped += 1
                        debug_msg = (f'Skipping unchanged rating for "{found_movie.title} ({getattr(found_movie, "year", "?")})" '
                                     f'existing={existing_rating_float} incoming={plex_rating}')
                        logger.debug(debug_msg)
                        self.log_message(debug_msg, log_filename)
                        continue
                try:
                    if dry_run:
                        star_form = plex_rating / 2.0
                        preview_entry = f'[DRY RUN] Would update "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                        if values.get("-WATCHED-", False):
                            preview_entry += " and mark watched"
                        preview_samples.append(preview_entry)
                        self.log_message(preview_entry, log_filename)
                        total_updated_movies += 1
                    else:
                        found_movie.rate(rating=plex_rating)
                        star_form = plex_rating / 2.0
                        message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                        logger.info(message)
                        self.log_message(message, log_filename)
                        if values.get("-WATCHED-", False):
                            try:
                                found_movie.markWatched()
                                watched_msg = f'Marked "{found_movie.title} ({found_movie.year})" as watched'
                                logger.info(watched_msg)
                                self.log_message(watched_msg, log_filename)
                            except Exception as e:
                                error_msg = f"Error marking as watched for {found_movie.title}: {e}"
                                logger.error(error_msg)
                                self.log_message(error_msg, log_filename)
                        total_updated_movies += 1
                except Exception as e:
                    rate_failed += 1
                    failures.append({
                        'Title': getattr(found_movie, 'title', ''),
                        'Year': getattr(found_movie, 'year', ''),
                        'IMDbID': imdb_id,
                        'Reason': f'Rate failed: {e}',
                        'YourRating': rating_raw,
                        'TitleType': movie.get('Title Type', '')
                    })
                if dry_run and len(preview_samples) >= PREVIEW_LIMIT:
                    pass

        if dry_run:
            message = f"DRY RUN: {total_updated_movies} of {total_movies} items would be updated (IMDb)"
        else:
            message = f"Successfully updated {total_updated_movies} out of {total_movies} (IMDb)"
        logger.info(message)
        self.log_message(message, log_filename)
        breakdown = [
            "Breakdown:",
            f"  Skipped unchanged: {unchanged_skipped}",
            f"  Missing IMDb ID: {missing_id}",
            f"  Invalid rating value: {invalid_rating}",
            f"  Not found in Plex: {not_found}",
            f"  Type mismatch: {type_mismatch}",
            f"  Rate failed errors: {rate_failed}",
            f"  Exported failures: {len(failures)}"
        ]
        for line in breakdown:
            self.log_message(line, log_filename)
        if not dry_run:
            self._export_failures_if_any(failures, source_filepath, 'imdb', log_filename)
        else:
            self.log_message('Dry run mode: No failure CSV exported.', log_filename)
        return True

    def update_ratings_from_letterboxd(self, csv_reader, library_section, values, log_filename, source_filepath, dry_run: bool = False):
        total_movies = 0
        total_updated_movies = 0
        failures: List[Dict[str, str]] = []
        missing_field = 0
        invalid_rating = 0
        not_found = 0
        rate_failed = 0
        unchanged_skipped = 0
        logger.info("Updating Letterboxd ratings")
        library_movies = {}
        for item in library_section.all():
            if getattr(item, 'type', None) != 'movie':
                continue
            key = (item.title.lower().strip(), str(item.year))
            library_movies.setdefault(key, item)
        for movie in csv_reader:
            try:
                name = (movie.get('Name') or '').strip()
                year = (movie.get('Year') or '').strip()
                rating_str = (movie.get('Rating') or '').strip()
                if not name or not year or not rating_str:
                    missing_field += 1
                    failures.append({
                        'Title': name,
                        'Year': year,
                        'Reason': 'Missing required field (Name/Year/Rating)',
                        'YourRating': rating_str
                    })
                    continue
                try:
                    your_rating = float(rating_str) * 2
                except ValueError:
                    invalid_rating += 1
                    failures.append({
                        'Title': name,
                        'Year': year,
                        'Reason': 'Invalid rating value',
                        'YourRating': rating_str
                    })
                    continue
                plex_rating = your_rating
                search_key = (name.lower(), year)
                found_movie = library_movies.get(search_key)
                if not found_movie:
                    not_found += 1
                    failures.append({
                        'Title': name,
                        'Year': year,
                        'Reason': 'Not found in Plex (title/year match failed)',
                        'YourRating': rating_str
                    })
                else:
                    force_overwrite = values.get('-FORCEOVERWRITE-', False)
                    if getattr(found_movie, 'ratingKey', None):
                        try:
                            fresh = library_section.fetchItem(found_movie.ratingKey)
                            if fresh:
                                found_movie = fresh
                        except Exception as e:  # pragma: no cover
                            logger.debug('fetchItem failed for ratingKey %s: %s', getattr(found_movie, 'ratingKey', '?'), e)
                    existing_rating = getattr(found_movie, 'userRating', None)
                    if not force_overwrite and existing_rating is not None:
                        try:
                            existing_rating_float = float(existing_rating)
                        except Exception:
                            existing_rating_float = existing_rating
                        logger.debug('Existing rating (fresh) for %s: %s incoming: %s', found_movie.title, existing_rating_float, plex_rating)
                        if isinstance(existing_rating_float, (int, float)) and abs(existing_rating_float - plex_rating) < 0.01:
                            unchanged_skipped += 1
                            total_movies += 1
                            debug_msg = (f'Skipping unchanged rating for "{found_movie.title} ({getattr(found_movie, "year", "?")})" '
                                         f'existing={existing_rating_float} incoming={plex_rating}')
                            logger.debug(debug_msg)
                            self.log_message(debug_msg, log_filename)
                            continue
                    try:
                        if dry_run:
                            star_form = plex_rating / 2.0
                            preview_entry = f'[DRY RUN] Would update "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                            if values.get("-WATCHED-", False):
                                preview_entry += " and mark watched"
                            self.log_message(preview_entry, log_filename)
                            total_updated_movies += 1
                        else:
                            found_movie.rate(rating=plex_rating)
                            star_form = plex_rating / 2.0
                            message = f'Updated Plex rating for "{found_movie.title} ({found_movie.year})" to {plex_rating}'
                            logger.info(message)
                            self.log_message(message, log_filename)
                            if values.get("-WATCHED-", False):
                                try:
                                    found_movie.markWatched()
                                    watched_msg = f'Marked "{found_movie.title} ({found_movie.year})" as watched'
                                    logger.info(watched_msg)
                                    self.log_message(watched_msg, log_filename)
                                except Exception as e:
                                    error_msg = f"Error marking as watched for {found_movie.title}: {e}"
                                    logger.error(error_msg)
                                    self.log_message(error_msg, log_filename)
                            total_updated_movies += 1
                    except Exception as e:
                        rate_failed += 1
                        failures.append({
                            'Title': name,
                            'Year': year,
                            'Reason': f'Rate failed: {e}',
                            'YourRating': rating_str
                        })
            except Exception as e:  # pragma: no cover
                logger.error('Error processing row: %s', e)
            total_movies += 1
        if dry_run:
            message = f"DRY RUN: {total_updated_movies} of {total_movies} items would be updated (Letterboxd)"
        else:
            message = f"Successfully updated {total_updated_movies} out of {total_movies} (Letterboxd)"
        logger.info(message)
        self.log_message(message, log_filename)
        breakdown = [
            "Breakdown:",
            f"  Skipped unchanged: {unchanged_skipped}",
            f"  Missing required fields: {missing_field}",
            f"  Invalid rating value: {invalid_rating}",
            f"  Not found in Plex: {not_found}",
            f"  Rate failed errors: {rate_failed}",
            f"  Exported failures: {len(failures)}"
        ]
        for line in breakdown:
            self.log_message(line, log_filename)
        if not dry_run:
            self._export_failures_if_any(failures, source_filepath, 'letterboxd', log_filename)
        else:
            self.log_message('Dry run mode: No failure CSV exported.', log_filename)
        return True

    def _get_selected_media_types(self, values):
        selected_media_types = []
        if values['-MOVIE-']:
            selected_media_types.append('Movie')
        if values['-TVSERIES-']:
            selected_media_types.append('TV Series')
        if values['-TVMINISERIES-']:
            selected_media_types.append('TV Mini Series')
        if values['-TVMOVIE-']:
            selected_media_types.append('TV Movie')
        if values.get('-SHORT-', False):
            selected_media_types.append('Short')
        if values.get('-TVEPISODE-', False):
            selected_media_types.append('TV Episode')
        logger.debug("Selected media types: %s", selected_media_types)
        return selected_media_types

    # --------------------- Failure Export Helper --------------------- #
    def _export_failures_if_any(self, failures: List[Dict[str, str]], source_filepath: str, source_name: str, log_filename: str):
        if not failures:
            self.log_message("No failed or unmatched items to export.", log_filename)
            return
        try:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            base = Path(source_filepath).stem
            out_path = Path.cwd() / f"Unmatched_{source_name}_{base}_{ts}.csv"
            # Determine headers union for robustness
            headers = set()
            for f in failures:
                headers.update(f.keys())
            headers = list(headers)
            with open(out_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(failures)
            self.log_message(f"Exported {len(failures)} unmatched/failed items to {out_path}", log_filename)
        except Exception as e:
            self.log_message(f"Failed to export unmatched items CSV: {e}", log_filename)

