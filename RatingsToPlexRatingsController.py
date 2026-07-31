import csv
import datetime
import logging
import threading
import time
import webbrowser
from typing import Callable, List, Optional, Dict
from pathlib import Path
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount
from RatingsImportPipeline import ImportOptions, ImportPipelineError, RatingsImportPipeline

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

    def build_import_plan(self, filepath, selected_library, values, max_items=0):
        if not self.plex_connection or not self.plex_connection.server:
            raise ImportPipelineError("Not connected to a Plex server")
        options = ImportOptions.from_values(values)
        pipeline = RatingsImportPipeline(self.plex_connection.server)
        return pipeline.build_plan(
            filepath,
            selected_library,
            options,
            max_items=max_items,
        )

    def update_ratings(self, filepath, selected_library, values):
        now = datetime.datetime.now()
        log_filename = f"RatingsUpdateLog_{now.strftime('%Y%m%d_%H%M%S')}.log"
        logger.info("Starting update_ratings with file: %s and library: %s", filepath, selected_library)
        if not self.plex_connection or not self.plex_connection.server:
            logger.error("Not connected to a Plex server")
            self.log_message('Error: Not connected to a Plex server', log_filename)
            return False

        try:
            options = ImportOptions.from_values(values)
            if options.dry_run:
                self.log_message('DRY RUN ENABLED: No changes will be written to Plex.', log_filename)
            if options.all_libraries:
                self.log_message('Cross-library mode enabled.', log_filename)

            self.log_message(f"Planning {options.source} ratings import", log_filename)
            pipeline = RatingsImportPipeline(
                self.plex_connection.server,
                log=lambda message: self.log_message(message, log_filename),
            )
            plan = pipeline.build_plan(filepath, selected_library, options)
            result = pipeline.apply(plan)

            updated = result.stats["updated"]
            total_items = result.stats["total_items"]
            if options.dry_run:
                summary = (
                    f"DRY RUN: {updated} of {total_items} items would be updated "
                    f"({options.source})"
                )
            else:
                summary = (
                    f"Successfully updated {updated} out of {total_items} "
                    f"({options.source})"
                )
            self.log_message(summary, log_filename)

            breakdown = [
                "Breakdown:",
                f"  Skipped unchanged: {result.stats['skipped_unchanged']}",
                f"  Missing IMDb ID: {result.stats['missing_id']}",
                f"  Missing required fields: {result.stats['missing_fields']}",
                f"  Invalid rating value: {result.stats['invalid_rating']}",
                f"  Not found in Plex: {result.stats['not_found']}",
                f"  Type mismatch: {result.stats['type_mismatch']}",
                f"  Rate failed errors: {result.stats['rate_failed']}",
                f"  Exported failures: {len(result.failures)}",
            ]
            for line in breakdown:
                self.log_message(line, log_filename)

            if options.dry_run:
                self.log_message('Dry run mode: No failure CSV exported.', log_filename)
            else:
                self._export_failures_if_any(
                    list(result.failures),
                    filepath,
                    options.source.lower(),
                    log_filename,
                )
            return result.success
        except FileNotFoundError:
            logger.error("CSV file not found: %s", filepath)
            self.log_message('Error: File not found', log_filename)
            return False
        except ImportPipelineError as e:
            logger.error("Import planning failed: %s", e)
            self.log_message(f'Error planning import: {e}', log_filename)
            return False
        except Exception as e:
            logger.error("Error processing CSV: %s", e)
            self.log_message(f'Error processing CSV: {e}', log_filename)
            return False

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

