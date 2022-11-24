import enum
import os
import subprocess
import sys
from fnmatch import fnmatch
import logging

from typing import Dict, List
import re

logging.basicConfig(level=logging.INFO)


class MultileCommentToken(enum.Enum):
    START = enum.auto()
    END = enum.auto()
    NONE = enum.auto()


class Language(enum.Enum):
    UNKOWN = "unknown"
    TYPESCRIPT = "TypeScript"
    PYTHON = "Python"
    JAVASCRIPT = "JavaScript"
    HTML = "HTML"
    CSS = "CSS"
    CPP = "C++"
    C = "C"
    CMAKE = "CMake"
    JSON = "JSON"
    MARKDOWN = "Markdown"
    JENKINS = "Jenkins"
    DOCKER = "Docker"
    BASH = "Bash"
    BATCHFILE = "Batchfile"


class FileType(enum.Enum):
    UNKNOWN = enum.auto()
    CODE = enum.auto()
    TEST = enum.auto()
    DOC = enum.auto()


class LineType(enum.Enum):
    COMMENT = enum.auto()
    CODE = enum.auto()
    BLANK = enum.auto()


class FolderMetadata:
    test_patterns: List[str]
    doc_patterns: List[str]

    def __init__(self):
        self.test_patterns = []
        self.doc_patterns = []
        self.exclude_patterns = []


class FileReport:
    lines: Dict[LineType, int]
    language: Language
    file_type: FileType

    def __init__(self):
        self.lines = {}
        self.lines[LineType.CODE] = 0
        self.lines[LineType.COMMENT] = 0
        self.lines[LineType.BLANK] = 0
        self.language = Language.UNKOWN
        self.file_type = FileType.UNKNOWN

    def __repr__(self):
        return '<FileReport %s - %s - stats: [code:%d, comment:%d, blank:%d]>' % (
            self.language,
            self.file_type,
            self.lines[LineType.CODE],
            self.lines[LineType.COMMENT],
            self.lines[LineType.BLANK]
        )


class FolderReport:
    class LanguageSummary:
        test_lines: int
        code_lines: int
        comment_lines: int
        blank_lines: int

        def __init__(self):
            self.test_lines = 0
            self.code_lines = 0
            self.comment_lines = 0
            self.blank_lines = 0

    class Summary:
        summaries_per_lang: Dict[Language, "FolderReport.LanguageSummary"]

        def __init__(self):
            self.summaries_per_lang = {}

        def add(self, lang: Language, summary: "FolderReport.LanguageSummary"):
            self.summaries_per_lang[lang] = summary

        def get(self, lang: Language) -> "FolderReport.LanguageSummary":
            if lang not in self.summaries_per_lang:
                self.summaries_per_lang[lang] = FolderReport.LanguageSummary()

            return self.summaries_per_lang[lang]

        def get_languages(self) -> List[Language]:
            return list(self.summaries_per_lang.keys())

    files: Dict[str, FileReport]
    skipped: List[str]

    def __init__(self):
        self.files = {}
        self.skipped = []

    def get_summary(self) -> "FolderReport.Summary":
        summary = FolderReport.Summary()

        for filename in self.files:
            file_report = self.files[filename]
            lang_summary = summary.get(file_report.language)
            lang_summary.blank_lines += file_report.lines[LineType.BLANK]
            if file_report.file_type == FileType.TEST:
                lang_summary.test_lines += file_report.lines[LineType.CODE]
            else:
                lang_summary.code_lines += file_report.lines[LineType.CODE]
            lang_summary.comment_lines += file_report.lines[LineType.COMMENT]

        return summary

    def make_printable_row(self, elems: List[str], widths: List[int]):
        line = ""

        for i in range(len(elems)):
            line += (elems[i] + ' ' * (widths[i] - len(elems[i])))

        return line

    def print_summary(self):
        spacing = 4
        summary = self.get_summary()
        rows = []
        title_row = ("Language", "Code", "Test", "Comment", "Blank")
        col_widths = []
        total_row = ['Total', 0, 0, 0, 0]
        for i in range(len(title_row)):
            col_widths.append(len(title_row[i]))

        for lang in summary.get_languages():

            lang_summary = summary.get(lang)
            row = [
                str(lang.value),
                (lang_summary.code_lines),
                (lang_summary.test_lines),
                (lang_summary.comment_lines),
                (lang_summary.blank_lines)
            ]

            for i in range(1, len(row)):
                total_row[i] += row[i]
                row[i] = str(row[i])

            if (len(row) != len(title_row)):
                raise Exception("Table size mismatch")

            rows.append(row)
            for i in range(len(col_widths)):
                col_widths[i] = max(len(row[i]), col_widths[i])

        for i in range(len(total_row)):
            total_row[i] = str(total_row[i])
            col_widths[i] = max(len(total_row[i]), col_widths[i])

        for i in range(len(col_widths)):
            col_widths[i] += spacing

        print(self.make_printable_row(title_row, col_widths))
        for row in rows:
            print(self.make_printable_row(row, col_widths))
        print(self.make_printable_row(total_row, col_widths))


def get_language(filename: str, metadata: FolderMetadata) -> Language:
    ext = os.path.splitext(filename)[1].strip().lower()
    basename = os.path.basename(filename)
    if basename == 'CMakeLists.txt':
        return Language.CMAKE

    if basename == 'Dockerfile':
        return Language.DOCKER
    if basename == 'Jenkinsfile':
        return Language.JENKINS

    if ext in ['.ts']:
        return Language.TYPESCRIPT
    if ext in ['.c', '.h']:
        return Language.C
    if ext in ['.cpp', '.hpp']:
        return Language.CPP
    if ext in ['.py', '.pyi']:
        return Language.PYTHON
    if ext in ['.js', '.cjs']:
        return Language.JAVASCRIPT
    if ext in ['.html', '.htm']:
        return Language.HTML
    if ext in ['.md']:
        return Language.MARKDOWN
    if ext in ['.json']:
        return Language.JSON
    if ext in ['.sh', '.bash']:
        return Language.BASH
    if ext in ['.css']:
        return Language.CSS
    if ext in ['.cmake']:
        return Language.CMAKE
    if ext in ['.bat']:
        return Language.BATCHFILE

    raise Exception('Unknown language for file %s' % filename)


def get_line_type(line: str, lang: Language, in_comment: bool = False) -> LineType:
    line = line.strip()
    if not line:
        return LineType.BLANK
    if in_comment:  # Todo : handle multiline comments
        return LineType.COMMENT

    if lang in [Language.C, Language.CPP, Language.TYPESCRIPT, Language.JAVASCRIPT, Language.JENKINS]:
        comment_regex = re.compile('^\s*(\/\/.+)|(\/\*.*\*\/)\s*$')
        if comment_regex.match(line):
            return LineType.COMMENT
    elif lang in [Language.PYTHON, Language.CMAKE, Language.BASH, Language.DOCKER]:
        comment_regex = re.compile('^\s*#.+\s*$')
        if comment_regex.match(line):
            return LineType.COMMENT
    elif lang in [Language.CSS]:
        comment_regex = re.compile('^\s*(\/\*.*\*\/)\s*$')
        if comment_regex.match(line):
            return LineType.COMMENT
    elif lang in [Language.HTML]:
        comment_regex = re.compile('^\s*<!--.*-->\s*$')
        if comment_regex.match(line):
            return LineType.COMMENT

    return LineType.CODE


def get_file_type(filename: str, lang: Language, metadata: FolderMetadata) -> FileType:
    if not os.path.isfile(filename):
        raise Exception('%s is not a file' % (filename))

    if lang == Language.UNKOWN:
        raise Exception('Unknown language')

    for pattern in metadata.test_patterns:
        if fnmatch(filename, pattern):
            return FileType.TEST

    for pattern in metadata.doc_patterns:
        if fnmatch(filename, pattern):
            return FileType.DOC

    test_regex = r'^(test_.+)|(.+\.test(\..+)?$)'
    if re.match(test_regex, os.path.basename(filename)):
        return FileType.TEST

    return FileType.CODE


def check_multiline_comment_token(line: str, lang: Language, in_comment: bool) -> MultileCommentToken:
    if lang in [Language.C, Language.CPP, Language.CSS, Language.JAVASCRIPT, Language.TYPESCRIPT, Language.JENKINS]:
        start = line.rfind('/*')
        end = line.rfind('*/')

        if end == -1:
            if start != -1:
                return MultileCommentToken.START
        else:
            if start == -1:
                return MultileCommentToken.END
            if start > end:
                return MultileCommentToken.START

    if lang in [Language.PYTHON]:
        token_count = 0  # todo
        search = -3
        while True:
            search = line.find('"""', search + 3)
            if search == -1:
                break
            token_count += 1

        if token_count > 0:
            if token_count % 2 == 0:
                return MultileCommentToken.START if in_comment else MultileCommentToken.END
            else:
                return MultileCommentToken.END if in_comment else MultileCommentToken.START

    return MultileCommentToken.NONE


def read_metadata(folder: str) -> FolderMetadata:
    return FolderMetadata()  # todo


def scan_folder(folder: str) -> FolderReport:
    if not os.path.isdir(folder):
        raise Exception('%s is not a folder' % (folder))

    metadata = read_metadata(folder)

    os.chdir(folder)
    cmd_output = subprocess.check_output(['git', 'ls-tree', '--full-tree', '-r', '--name-only', 'HEAD'])
    file_list = sorted([file.strip() for file in cmd_output.decode('utf8').split('\n') if file])
    report = FolderReport()

    for filename in file_list:
        try:
            report.files[filename] = scan_file(filename, metadata)
        except Exception as e:
            logging.debug('Skipping %s: %s' % (filename, e))
            report.skipped.append(filename)

    return report


def scan_file(filename: str, metadata: FolderMetadata) -> FileReport:
    if not os.path.isfile(filename):
        raise Exception('%s is not a file' % (filename))

    for exclude_pattern in metadata.exclude_patterns:
        if fnmatch(filename, exclude_pattern):
            raise Exception("Excluded")

    report = FileReport()
    report.language = get_language(filename, metadata)
    report.file_type = get_file_type(filename, report.language, metadata)

    with open(filename, 'r') as f:
        in_comment = False
        for line in f.readlines():
            multiline_comment_token = check_multiline_comment_token(line, report.language, in_comment)
            if multiline_comment_token == MultileCommentToken.START:
                in_comment = True
            elif multiline_comment_token == MultileCommentToken.END:
                in_comment = False

            report.lines[get_line_type(line, report.language, in_comment)] += 1

    return report


if __name__ == '__main__':
    report = scan_folder(sys.argv[1])
    report.print_summary()
