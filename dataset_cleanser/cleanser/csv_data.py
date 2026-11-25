import csv
import hashlib
import re
from collections import Counter
from datetime import date, datetime
from time import monotonic

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from .catalog import EXPORT_DELIMITER, EXPORT_ENCODING, PSEUDONYM_STRATEGIES
from .files import stored_path
from .models import DataType


class ProcessingError(Exception):
    def __init__(self, code, message, *, retryable=False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class CSVParseError(ProcessingError):
    def __init__(self, line, message):
        super().__init__("CSV_PARSE_ERROR", f"Строка {line}: {message}")


LINE_BREAK = re.compile(r"\r\n|\r|\n")
FIELDS = {delimiter: re.compile(r'"(?:[^"]|"")*+"|[^"\r\n' + re.escape(delimiter) + r']*+')
          for delimiter in (",", ";")}
INTEGER = re.compile(r"[+-]?[0-9]+")
DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
ISO_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
                          r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?")
EMAIL_HEADERS = {"email", "e-mail", "e_mail", "электронная почта"}
TYPE_PRIORITY = (DataType.EMAIL, DataType.BOOLEAN, DataType.INTEGER,
                 DataType.DECIMAL, DataType.DATE, DataType.DATETIME)


def records(text, delimiter, tick):
    field_pattern = FIELDS[delimiter]
    cursor = 0
    line = 1
    while cursor < len(text):
        start = line
        row = []
        tick()
        if text[cursor] in "\r\n":
            raise CSVParseError(start, "пустая запись.")
        while True:
            if len(row) == settings.MAX_CSV_COLUMNS:
                raise CSVParseError(start, "слишком много столбцов.")
            match = field_pattern.match(text, cursor)
            encoded = match[0]
            cursor = match.end()
            if cursor < len(text) and text[cursor] not in (delimiter, "\r", "\n"):
                raise CSVParseError(line, "некорректное размещение кавычек.")
            if encoded.startswith('"'):
                value = encoded[1:-1].replace('""', '"')
                line += len(LINE_BREAK.findall(encoded))
            else:
                value = encoded
            if len(value) > settings.MAX_CSV_FIELD_CHARS:
                raise CSVParseError(start, "поле превышает допустимую длину.")
            row.append(value or None)
            if cursor == len(text):
                yield start, row
                break
            if text[cursor] != delimiter:
                cursor = LINE_BREAK.match(text, cursor).end()
                line += 1
                yield start, row
                break
            cursor += 1


def _with_header(text, delimiter, tick):
    stream = records(text, delimiter, tick)
    _, header = next(stream, (1, []))
    return header, stream


def _read_rows(header, stream):
    if not header or any(is_missing(name) for name in header):
        raise CSVParseError(1, "укажите непустые заголовки столбцов.")
    rows = []
    for line, row in stream:
        if len(row) != len(header):
            raise CSVParseError(line, f"ожидалось полей: {len(header)}, получено: {len(row)}.")
        if len(rows) >= settings.MAX_CSV_ROWS or (len(rows) + 1) * len(header) > settings.MAX_CSV_CELLS:
            raise CSVParseError(line, "превышен лимит строк или ячеек.")
        rows.append(row)
    if not rows:
        raise CSVParseError(2, "нет строк данных.")
    return rows


def read_csv(file, delimiter, encoding, heartbeat):
    payload = stored_path(file).read_bytes()
    if hashlib.sha256(payload).hexdigest() != file.sha256 or len(payload) != file.size_bytes:
        raise ProcessingError("FILE_INTEGRITY_ERROR", "Исходный файл повреждён.", retryable=True)
    text = payload.decode("utf-8-sig" if encoding == "utf-8" else encoding)
    deadline = monotonic() + settings.CSV_PARSE_TIMEOUT_SECONDS

    def tick():
        if monotonic() >= deadline:
            raise ProcessingError("CSV_PARSE_TIMEOUT", "Превышено время разбора CSV.")
        heartbeat()

    if delimiter != "auto":
        header, stream = _with_header(text, delimiter, tick)
        return header, _read_rows(header, stream)

    candidates = []
    header_failures = []
    for candidate in (",", ";"):
        try:
            candidates.append(_with_header(text, candidate, tick))
        except CSVParseError as exc:
            header_failures.append(exc)
    if not candidates:
        raise header_failures[0]

    candidates.sort(key=lambda item: -len(item[0]))
    widest = len(candidates[0][0])
    first_row_failure = None
    for header, stream in candidates:
        if widest > 1 and len(header) == 1:
            break
        try:
            return header, _read_rows(header, stream)
        except CSVParseError as exc:
            if first_row_failure is None:
                first_row_failure = exc
    raise first_row_failure


def is_missing(value):
    return value is None or not value.strip()


def is_email(value):
    if "@" not in value:
        return False
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


def matches_type(value, data_type):
    if data_type == DataType.STRING:
        return True
    if data_type == DataType.BOOLEAN:
        return value.lower() in {"true", "false"}
    if data_type == DataType.INTEGER:
        return bool(INTEGER.fullmatch(value))
    if data_type == DataType.DECIMAL:
        return bool(DECIMAL.fullmatch(value))
    if data_type == DataType.EMAIL:
        return is_email(value)
    try:
        if data_type == DataType.DATE and ISO_DATE.fullmatch(value):
            date.fromisoformat(value)
            return True
        if data_type == DataType.DATETIME and ISO_DATETIME.fullmatch(value):
            datetime.fromisoformat(value)
            return True
    except ValueError:
        return False
    return False


def infer_schema(header, rows, heartbeat):
    columns = []
    for position, name in enumerate(header):
        count = Counter()
        nonempty = 0
        email_header = name.strip().casefold() in EMAIL_HEADERS
        for row in rows:
            heartbeat()
            value = row[position]
            if is_missing(value):
                continue
            nonempty += 1
            if email_header:
                continue
            value = value.strip()
            for candidate in TYPE_PRIORITY:
                if matches_type(value, candidate):
                    count[candidate] += 1
                    if candidate == DataType.INTEGER:
                        count[DataType.DECIMAL] += 1
                    break
        data_type = DataType.EMAIL if email_header else next(
            (candidate for candidate in TYPE_PRIORITY if count[candidate] * 2 > nonempty), DataType.STRING,
        )
        columns.append({"name": name, "data_type": data_type, "nullable": nonempty < len(rows)})
    return columns


def write_csv(staged, header, rows, heartbeat):
    with staged.temporary_path.open("w", encoding=EXPORT_ENCODING, newline="") as file:
        # csv.writer uses its line ending to detect fields requiring quoting. Keep CR quoted
        # while emitting LF between records and preserving embedded CR/LF verbatim.
        class LFRecords:
            def write(self, record):
                file.write(record[:-2] + "\n")

        writer = csv.writer(LFRecords(), delimiter=EXPORT_DELIMITER, lineterminator="\r\n")
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
            heartbeat()
    staged.seal(heartbeat)


def pseudonym(value, tokens, strategy, salt):
    if value not in tokens:
        # Number each distinct input within the column. The per-run salt prevents
        # intentional reuse of tokens across runs, and the ordinal guarantees uniqueness.
        alias = f"{salt}-{len(tokens) + 1}"
        tokens[value] = f"{alias}@example.invalid" if strategy == PSEUDONYM_STRATEGIES[DataType.EMAIL] else alias
    return tokens[value]
