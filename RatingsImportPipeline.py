import csv
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple


IMDB_TYPE_TO_PLEX_TYPES = {
    "Movie": {"movie"},
    "TV Movie": {"movie"},
    "Short": {"movie"},
    "TV Series": {"show"},
    "TV Mini Series": {"show"},
    "TV Episode": {"episode"},
}


class ImportPipelineError(Exception):
    """Raised when an import plan cannot be built safely."""


@dataclass(frozen=True)
class ImportOptions:
    source: str
    selected_media_types: FrozenSet[str]
    force_overwrite: bool = False
    mark_watched: bool = False
    dry_run: bool = False
    all_libraries: bool = False

    @classmethod
    def from_values(cls, values: Dict[str, Any]) -> "ImportOptions":
        if values.get("-IMDB-"):
            source = "IMDb"
        elif values.get("-LETTERBOXD-"):
            source = "Letterboxd"
        else:
            raise ImportPipelineError("A supported ratings source must be selected")

        media_types = set()
        option_to_type = {
            "-MOVIE-": "Movie",
            "-TVSERIES-": "TV Series",
            "-TVMINISERIES-": "TV Mini Series",
            "-TVMOVIE-": "TV Movie",
            "-SHORT-": "Short",
            "-TVEPISODE-": "TV Episode",
        }
        for option_name, media_type in option_to_type.items():
            if values.get(option_name, False):
                media_types.add(media_type)

        return cls(
            source=source,
            selected_media_types=frozenset(media_types),
            force_overwrite=bool(values.get("-FORCEOVERWRITE-", False)),
            mark_watched=bool(values.get("-WATCHED-", False)),
            dry_run=bool(values.get("-DRYRUN-", False)),
            all_libraries=bool(values.get("-ALLLIBS-", False)),
        )


@dataclass(frozen=True)
class ParsedRow:
    source: str
    raw: Dict[str, str]
    title: str
    year: str
    rating_text: str
    title_type: str = ""
    external_id: str = ""


@dataclass(frozen=True)
class ParsedImport:
    rows: Sequence[ParsedRow]
    total_rows: int


@dataclass(frozen=True)
class ValidatedRow:
    parsed: ParsedRow
    new_rating: Optional[float]
    status: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class MatchedRow:
    validated: ValidatedRow
    plex_item: Any = None
    section: Any = None
    status: Optional[str] = None
    reason: str = ""


@dataclass
class PlanItem:
    parsed: ParsedRow
    status: str
    matched: bool
    new_rating: Optional[float]
    current_rating: Optional[float]
    title: str
    year: str
    thumb: Optional[str]
    plex_item: Any = field(default=None, repr=False)
    section: Any = field(default=None, repr=False)
    reason: str = ""

    def to_preview_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "year": self.year,
            "matched": self.matched,
            "status": self.status,
            "newRating": self.new_rating,
            "currentRating": self.current_rating,
            "thumb": self.thumb,
        }

    def failure_record(self, reason: Optional[str] = None) -> Dict[str, str]:
        failure_reason = reason or self.reason or self.status.replace("_", " ").title()
        if self.parsed.source == "IMDb":
            return {
                "Title": self.parsed.title,
                "Year": self.parsed.year,
                "IMDbID": self.parsed.external_id,
                "Reason": failure_reason,
                "YourRating": self.parsed.rating_text,
                "TitleType": self.parsed.title_type,
            }
        return {
            "Title": self.parsed.title,
            "Year": self.parsed.year,
            "Reason": failure_reason,
            "YourRating": self.parsed.rating_text,
        }


@dataclass(frozen=True)
class ImportPlan:
    source: str
    items: Sequence[PlanItem]
    total_rows: int
    options: ImportOptions

    @property
    def matched_count(self) -> int:
        return sum(1 for item in self.items if item.matched)

    @property
    def unmatched_count(self) -> int:
        return len(self.items) - self.matched_count

    @property
    def update_count(self) -> int:
        return sum(1 for item in self.items if item.status == "will_update")


@dataclass(frozen=True)
class ApplyResult:
    success: bool
    stats: Dict[str, Any]
    failures: Sequence[Dict[str, str]]


class RatingsImportPipeline:
    """One import path used by both preview and update.

    Every import follows the same parse -> validate -> match -> plan -> apply
    stages. Applying a plan never performs a second match.
    """

    def __init__(self, server: Any, log: Optional[Callable[[str], None]] = None):
        self.server = server
        self.log = log or (lambda _message: None)

    def parse(
        self,
        filepath: str,
        options: ImportOptions,
        max_items: int = 0,
    ) -> ParsedImport:
        parsed_rows: List[ParsedRow] = []
        total_rows = 0
        with open(filepath, "r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            for raw_row in reader:
                total_rows += 1
                parsed_row = None
                if options.source == "IMDb":
                    title_type = (raw_row.get("Title Type") or "").strip()
                    if title_type not in options.selected_media_types:
                        continue
                    parsed_row = ParsedRow(
                        source="IMDb",
                        raw=raw_row,
                        title=(raw_row.get("Title") or "").strip(),
                        year=(raw_row.get("Year") or "").strip(),
                        rating_text=(raw_row.get("Your Rating") or "").strip(),
                        title_type=title_type,
                        external_id=(raw_row.get("Const") or "").strip(),
                    )
                elif options.source == "Letterboxd":
                    parsed_row = ParsedRow(
                        source="Letterboxd",
                        raw=raw_row,
                        title=(raw_row.get("Name") or "").strip(),
                        year=(raw_row.get("Year") or "").strip(),
                        rating_text=(raw_row.get("Rating") or "").strip(),
                    )
                else:
                    raise ImportPipelineError(f"Unsupported ratings source: {options.source}")

                if max_items <= 0 or len(parsed_rows) < max_items:
                    parsed_rows.append(parsed_row)
        return ParsedImport(rows=parsed_rows, total_rows=total_rows)

    def validate(self, parsed_import: ParsedImport) -> Sequence[ValidatedRow]:
        validated_rows: List[ValidatedRow] = []
        for parsed in parsed_import.rows:
            if parsed.source == "IMDb" and not parsed.external_id:
                validated_rows.append(ValidatedRow(
                    parsed=parsed,
                    new_rating=None,
                    status="missing_id",
                    reason="Missing IMDb ID (Const)",
                ))
                continue
            if parsed.source == "Letterboxd" and (
                not parsed.title or not parsed.year or not parsed.rating_text
            ):
                validated_rows.append(ValidatedRow(
                    parsed=parsed,
                    new_rating=None,
                    status="missing_fields",
                    reason="Missing required field (Name/Year/Rating)",
                ))
                continue

            try:
                source_rating = float(parsed.rating_text)
            except (TypeError, ValueError):
                source_rating = math.nan

            if parsed.source == "IMDb":
                valid_rating = math.isfinite(source_rating) and 1 <= source_rating <= 10
                new_rating = source_rating
            else:
                valid_rating = math.isfinite(source_rating) and 0.5 <= source_rating <= 5
                new_rating = source_rating * 2

            if not valid_rating:
                validated_rows.append(ValidatedRow(
                    parsed=parsed,
                    new_rating=None,
                    status="invalid_rating",
                    reason="Invalid rating value",
                ))
                continue
            validated_rows.append(ValidatedRow(parsed=parsed, new_rating=new_rating))
        return validated_rows

    def match(
        self,
        validated_rows: Sequence[ValidatedRow],
        sections: Sequence[Any],
        source: str,
    ) -> Sequence[MatchedRow]:
        if not validated_rows:
            return []

        guid_lookup: Dict[str, Tuple[Any, Any]] = {}
        title_lookup: Dict[Tuple[str, str], Tuple[Any, Any]] = {}

        for section in sections:
            try:
                section_items = section.all()
            except Exception as error:
                section_name = getattr(section, "title", "?")
                raise ImportPipelineError(
                    f'Could not scan Plex library "{section_name}": {error}'
                ) from error
            for item in section_items:
                if source == "IMDb":
                    primary_guid = getattr(item, "guid", None)
                    if primary_guid:
                        guid_lookup.setdefault(primary_guid, (item, section))
                    for guid in getattr(item, "guids", []) or []:
                        guid_id = getattr(guid, "id", None)
                        if guid_id:
                            guid_lookup.setdefault(guid_id, (item, section))
                elif getattr(item, "type", None) == "movie":
                    title = (getattr(item, "title", "") or "").lower().strip()
                    year = str(getattr(item, "year", "") or "")
                    title_lookup.setdefault((title, year), (item, section))

        matched_rows: List[MatchedRow] = []
        for validated in validated_rows:
            if validated.status:
                matched_rows.append(MatchedRow(
                    validated=validated,
                    status=validated.status,
                    reason=validated.reason,
                ))
                continue

            parsed = validated.parsed
            if source == "IMDb":
                match = guid_lookup.get(f"imdb://{parsed.external_id}")
            else:
                match = title_lookup.get((parsed.title.lower(), parsed.year))
            if not match:
                reason = (
                    "Not found in Plex by GUID"
                    if source == "IMDb"
                    else "Not found in Plex (title/year match failed)"
                )
                matched_rows.append(MatchedRow(
                    validated=validated,
                    status="not_found",
                    reason=reason,
                ))
                continue

            item, section = match
            if source == "IMDb":
                expected_types = IMDB_TYPE_TO_PLEX_TYPES.get(parsed.title_type, set())
                item_type = getattr(item, "type", None)
                if expected_types and item_type not in expected_types:
                    matched_rows.append(MatchedRow(
                        validated=validated,
                        plex_item=item,
                        section=section,
                        status="type_mismatch",
                        reason=f"Type mismatch (Plex={item_type})",
                    ))
                    continue
            matched_rows.append(MatchedRow(
                validated=validated,
                plex_item=item,
                section=section,
            ))
        return matched_rows

    def plan(
        self,
        matched_rows: Sequence[MatchedRow],
        parsed_import: ParsedImport,
        options: ImportOptions,
    ) -> ImportPlan:
        plan_items: List[PlanItem] = []
        for matched in matched_rows:
            parsed = matched.validated.parsed
            item = matched.plex_item
            current_rating = self._current_rating(item) if item is not None else None
            if matched.status:
                status = matched.status
            elif (
                not options.force_overwrite
                and current_rating is not None
                and abs(current_rating - matched.validated.new_rating) < 0.01
            ):
                status = "unchanged"
            else:
                status = "will_update"

            plan_items.append(PlanItem(
                parsed=parsed,
                status=status,
                matched=item is not None,
                new_rating=matched.validated.new_rating,
                current_rating=current_rating,
                title=(getattr(item, "title", None) or parsed.title),
                year=str(getattr(item, "year", None) or parsed.year),
                thumb=getattr(item, "thumb", None) if item is not None else None,
                plex_item=item,
                section=matched.section,
                reason=matched.reason,
            ))
        return ImportPlan(
            source=options.source,
            items=plan_items,
            total_rows=parsed_import.total_rows,
            options=options,
        )

    def build_plan(
        self,
        filepath: str,
        selected_library: str,
        options: ImportOptions,
        max_items: int = 0,
    ) -> ImportPlan:
        sections = self._resolve_sections(selected_library, options.all_libraries)
        parsed = self.parse(filepath, options, max_items=max_items)
        validated = self.validate(parsed)
        matched = self.match(validated, sections, options.source)
        return self.plan(matched, parsed, options)

    def apply(self, plan: ImportPlan) -> ApplyResult:
        stats: Dict[str, Any] = {
            "updated": 0,
            "total_items": len(plan.items),
            "skipped_unchanged": 0,
            "missing_id": 0,
            "missing_fields": 0,
            "invalid_rating": 0,
            "not_found": 0,
            "type_mismatch": 0,
            "rate_failed": 0,
            "dry_run": plan.options.dry_run,
        }
        failures: List[Dict[str, str]] = []

        for item in plan.items:
            if item.status == "unchanged":
                stats["skipped_unchanged"] += 1
                self.log(
                    f'Skipping unchanged rating for "{item.title} ({item.year})" '
                    f'existing={item.current_rating} incoming={item.new_rating}'
                )
                continue
            if item.status != "will_update":
                if item.status in stats:
                    stats[item.status] += 1
                failures.append(item.failure_record())
                if item.status == "type_mismatch":
                    self.log(
                        f'Skipped "{item.title} ({item.year})" - '
                        f'type mismatch (CSV: {item.parsed.title_type}, '
                        f'Plex: {getattr(item.plex_item, "type", "?")})'
                    )
                continue

            try:
                star_form = item.new_rating / 2.0
                if plan.options.dry_run:
                    message = (
                        f'[DRY RUN] Would update "{item.title} ({item.year})" '
                        f'to {item.new_rating} ({star_form:.1f}\u2605)'
                    )
                    if plan.options.mark_watched:
                        message += " and mark watched"
                    self.log(message)
                else:
                    item.plex_item.rate(rating=item.new_rating)
                    self.log(
                        f'Updated Plex rating for "{item.title} ({item.year})" '
                        f'to {item.new_rating} ({star_form:.1f}\u2605)'
                    )
                    if plan.options.mark_watched:
                        try:
                            item.plex_item.markWatched()
                            self.log(f'Marked "{item.title} ({item.year})" as watched')
                        except Exception as error:
                            self.log(f"Error marking as watched for {item.title}: {error}")
                stats["updated"] += 1
            except Exception as error:
                stats["rate_failed"] += 1
                failures.append(item.failure_record(reason=f"Rate failed: {error}"))

        return ApplyResult(success=True, stats=stats, failures=failures)

    def _resolve_sections(self, selected_library: str, all_libraries: bool) -> Sequence[Any]:
        try:
            if all_libraries:
                sections = [
                    section for section in self.server.library.sections()
                    if getattr(section, "type", "") in ("movie", "show")
                ]
                if not sections:
                    raise ImportPipelineError("No movie or TV libraries were found")
                return sections
            if not selected_library:
                raise ImportPipelineError("No library selected")
            return [self.server.library.section(selected_library)]
        except ImportPipelineError:
            raise
        except Exception as error:
            raise ImportPipelineError(
                f'Could not open Plex library "{selected_library}": {error}'
            ) from error

    @staticmethod
    def _current_rating(item: Any) -> Optional[float]:
        value = getattr(item, "userRating", None)
        if value is None:
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        return rating if math.isfinite(rating) else None
