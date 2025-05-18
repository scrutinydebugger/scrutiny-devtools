import enum
import os
from glob import glob
import re
import json
from datetime import datetime
import argparse
import pathlib
import sys
import logging
from fnmatch import fnmatch
from os import path

from typing import List, Generator, TypedDict, Dict


class FileEntry(TypedDict, total=False):
    docstring: str
    add_shebang: bool


class CodeBannerFileFormat(TypedDict):
    folders: str
    include_patterns: List[str]
    exclude_patterns: List[str]
    project: str
    repo: str
    license: str
    copyright_owner: str
    copyright_start_date: str
    copyright_end_date: str
    files: Dict[str, FileEntry]


class Language(enum.Enum):
    CPP = enum.auto()
    PYTHON = enum.auto()
    JAVASCRIPT = enum.auto()
    TYPESCRIPT = enum.auto()


class CodeBanner:

    config: CodeBannerFileFormat
    base_folder: str
    banner_file: str

    def __init__(self, folder: str = '.', filename: str = '.codebanner.json'):
        self.config = {}
        self.base_folder = folder

        if not path.isdir(self.base_folder):
            raise Exception('Folder %s does not exist' % self.base_folder)

        self.banner_file = path.join(self.base_folder, filename)

        if path.isfile(self.banner_file):
            with open(self.banner_file, 'r', encoding="utf8") as f:
                content = f.read()
                self.config = json.loads(content)

        self.init_config()

    def clear_config(self) -> None:
        self.config = {}
        self.init_config()

    def init_config(self) -> None:
        if 'folders' not in self.config:
            self.config['folders'] = []

        if 'include_patterns' not in self.config:
            self.config['include_patterns'] = []

        if 'exclude_patterns' not in self.config:
            self.config['exclude_patterns'] = []

        if 'project' not in self.config:
            self.config['project'] = ""

        if 'repo' not in self.config:
            self.config['repo'] = ""

        if 'license' not in self.config:
            self.config['license'] = ""

        if 'copyright_owner' not in self.config:
            self.config['copyright_owner'] = ""

        if 'copyright_start_date' not in self.config:
            self.config['copyright_start_date'] = datetime.now().strftime('%Y')

        if 'copyright_end_date' not in self.config:
            self.config['copyright_end_date'] = datetime.now().strftime('%Y')

        if 'files' not in self.config:
            self.config['files'] = {}

    def write_config(self) -> None:
        with open(self.banner_file, 'w', encoding='utf8') as f:
            json.dump(self.config, f, indent=4)

    def get_language(self, filename: str) -> Language:
        p = pathlib.Path(filename)
        extension = p.suffix.lower()

        if extension in ['.py']:
            return Language.PYTHON

        if extension in ['.c', '.cpp', '.h', '.hpp']:
            return Language.CPP

        if extension in ['.js']:
            return Language.JAVASCRIPT

        if extension in ['.ts']:
            return Language.TYPESCRIPT

        raise Exception('Unknown file extension ' + extension)

    def scan_files(self) -> Generator[str, None, None]:
        folders_to_scan = self.config['folders']
        if len(folders_to_scan) == 0:
            folders_to_scan = '.'

        for start_folder in folders_to_scan:
            for root, subdirs, files in os.walk(path.join(self.base_folder, start_folder)):
                included_files = set()
                for file in files:
                    filename = self.make_name(path.join(root, file))
                    for include_pattern in self.config['include_patterns']:
                        if fnmatch(filename, include_pattern):
                            excluded = False
                            for exclude_pattern in self.config['exclude_patterns']:
                                if fnmatch(filename, exclude_pattern):
                                    excluded = True
                            if not excluded:
                                included_files.add(filename)

                new_subdirs = []
                for subdir in subdirs:
                    subdirname = self.make_name(path.join(root, subdir))
                    excluded = False
                    for exclude_pattern in self.config['exclude_patterns']:
                        if fnmatch(subdirname, exclude_pattern):
                            excluded = True

                    if not excluded:
                        new_subdirs.append(subdirname)

                subdirs = new_subdirs

                if len(included_files) == 0:
                    continue

                for filename in included_files:
                    yield filename.replace('\\', '/')

    def make_name(self, pathname):
        return path.relpath(path.abspath(path.normpath(pathname)), path.abspath(self.base_folder))

    def add_files(self, files: List[str], remove_not_present: bool = False) -> None:
        files_to_remove = []

        if remove_not_present:
            for file in self.config['files']:
                if not file in files:
                    files_to_remove.append(file)

            for file in files_to_remove:
                del self.config['files'][file]

        for file in files:
            if file not in self.config['files']:
                self.config['files'][file] = {
                    'docstring': ''
                }

    def write_files(self):
        for file in self.config['files']:
            filepath = path.join(self.base_folder, file)
            if not path.isfile(filepath):
                logging.warning('File missing : %s' % file)
                continue

            self.write_docstring(filepath, self.config['files'][file])

    def write_docstring(self, filepath: str, file_entry: FileEntry) -> None:

        # TODO : Would be better to use """ in Python and /**/ in cpp.
        # But I don't want to spend time on file aprsing. There must be a tool that does that.

        language = self.get_language(filepath)
        docstring = file_entry['docstring']
        add_shebang = False if 'add_shebang' not in file_entry else file_entry['add_shebang']

        if language == Language.CPP:
            skip_patterns = []
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = ''
        elif language == Language.JAVASCRIPT:
            skip_patterns = []
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = '#!/bin/node\n\n' if add_shebang else ''
        elif language == Language.TYPESCRIPT:
            skip_patterns = [r'\/\/\s*@ts-(no)?check']
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = '#!/bin/node\n\n' if add_shebang else ''
        elif language == Language.PYTHON:
            skip_patterns = []
            comment_pattern = [r'^\s*#(.*)', r'^\s+$']
            shebang = '#!/usr/bin/env python3\n\n' if add_shebang else ''
        else:
            raise NotImplementedError('Unsupported language %s' % language)

        with open(filepath, 'r', encoding='utf8') as f:
            start_line = 0
            comment_lines = 0
            skip_done = False
            line_no = -1
            all_lines = []
            header_finished = False
            for line in f.readlines():
                line_no += 1
                all_lines.append(line)
                if header_finished:
                    continue

                skipped = False
                if not skip_done:
                    for pattern in skip_patterns:
                        if re.match(pattern, line):
                            start_line += 1
                            skipped = True
                            break

                if skipped:
                    continue

                for pattern in comment_pattern:
                    is_comment = False
                    if re.match(pattern, line):
                        is_comment = True
                        break
                if is_comment:
                    if skip_done == False:
                        start_line = line_no
                    skip_done = True
                    comment_lines += 1
                else:
                    header_finished = True

        for i in range(comment_lines):
            all_lines.pop(start_line)

        render_data = {}
        render_data['shebang'] = shebang

        render_data['docstring'] = self.format_docstring(docstring, language)
        render_data['license'] = self.config['license']
        render_data['project'] = self.config['project']
        render_data['repo'] = '(%s)' % self.config['repo'] if self.config['repo'] else ''

        double_date = True
        start_date = self.config['copyright_start_date']
        end_date = self.config['copyright_end_date']
        if not start_date:
            start_date = datetime.now().strftime('%Y')
            double_date = False

        if not end_date:
            double_date = False

        if start_date == end_date:
            double_date = False

        if double_date:
            render_data['date'] = '%s-%s' % (start_date, end_date)
        else:
            render_data['date'] = start_date
        render_data['copyright_owner'] = self.config['copyright_owner']

        if language == Language.CPP or language == Language.JAVASCRIPT or language == Language.TYPESCRIPT:
            render_data['filename'] = '//    ' + path.basename(filepath)
            new_header = """{shebang}{filename}{docstring}
//
//   - License : {license}.
//   - Project : {project} {repo}
//
//   Copyright (c) {date} {copyright_owner}
""".format(**render_data)

        elif language == Language.PYTHON:
            render_data['filename'] = '#    ' + path.basename(filepath)
            new_header = """{shebang}{filename}{docstring}
#
#   - License : {license}.
#   - Project :  {project} {repo}
#
#   Copyright (c) {date} {copyright_owner}
""".format(**render_data)
        else:
            raise Exception('Unknown language %s' % language)

        header_lines = new_header.split('\n')
        header_lines.reverse()

        for line_to_insert in header_lines:
            all_lines.insert(start_line, line_to_insert + '\n')

        with open(filepath, 'w', encoding='utf8') as f:
            f.writelines(all_lines)

    def format_docstring(self, docstring: str, language: Language):
        chunk_size = 80
        space = 8
        lines = []
        done = False
        while not done:
            next_line_break = docstring.find('\n')
            if len(docstring) <= chunk_size:
                done = True
                lines.append(docstring[0:].strip())
            elif next_line_break >= 0 and next_line_break <= chunk_size:
                lines.append(docstring[0:next_line_break + 1].strip())
                docstring = docstring[next_line_break + 1:]
            else:
                i = 0
                while True:
                    if len(docstring) <= chunk_size + i:
                        lines.append(docstring[0:])
                        done = True
                        break
                    elif docstring[chunk_size + i] in [' ', '\n']:
                        lines.append(docstring[0:chunk_size + i].strip())
                        docstring = docstring[chunk_size + i:]
                        break
                    else:
                        i += 1
        docstring = '\n'.join(lines)
        if docstring:
            docstring = '\n' + docstring

        if language == Language.CPP or language == language.JAVASCRIPT or language == Language.TYPESCRIPT:
            docstring = docstring.replace('\n', '\n//' + ' ' * space)
        elif language == Language.PYTHON:
            docstring = docstring.replace('\n', '\n#' + ' ' * space)
        else:
            raise NotImplementedError('Unsupported language %s' % language)
        return docstring


def main():
    parser = argparse.ArgumentParser(prog=__file__)
    parser.add_argument('action', help='Action to execute',
                        choices=['init', 'scan', 'write'])
    parser.add_argument('--folder', help='Work folder', default='.')
    parser.add_argument(
        '--config_file', help='Name of the configuration file', default='.codebanner.json')

    args, subcommand_args = parser.parse_known_args(sys.argv[1:])

    codebanner = CodeBanner(args.folder, args.config_file)

    if args.action == 'init':
        codebanner.clear_config()
        codebanner.write_config()

    elif args.action == 'scan':
        parser = argparse.ArgumentParser(prog=__file__)
        parser.add_argument('--update', choices=['no', 'merge', 'full'],
                            help='How to update the code banner config', default='no')
        subargs = parser.parse_args(subcommand_args)

        files = list(codebanner.scan_files())

        if subargs.update == 'no':
            for file in files:
                print(file)
        elif subargs.update == 'merge':
            codebanner.add_files(files, remove_not_present=False)
            codebanner.write_config()
        elif subargs.update == 'full':
            codebanner.add_files(files, remove_not_present=True)
            codebanner.write_config()

    elif args.action == 'write':
        codebanner.write_files()

    else:
        raise Exception('Unknown action %s' % args.action)


if __name__ == '__main__':
    main()
