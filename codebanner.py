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
import subprocess

from typing import List, Generator, TypedDict, Dict, Set

def get_edit_years(file:str) -> List[int]:
    years:Set[int] = set()
    p = subprocess.run(['git', 'log', '--follow', r'--format=%aI', '--date', 'default', file], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if p.returncode != 0:
        raise RuntimeError("Failed to get date.\n" + p.stderr.decode() )
    for line in p.stdout.decode('utf8').splitlines():
        dt = datetime.fromisoformat(line)
        years.add(dt.year)

    return sorted(list(years))

def get_first_edit_year(file:str) -> int:
    years = get_edit_years(file)
    if len(years) == 0:
        raise RuntimeError(f"Cannot find edit year of file {file}")
    return years[0]

class FileEntry(TypedDict, total=False):
    docstring: str
    add_shebang: bool
    author:str
    contributors:List[str]


class CodeBannerFileFormat(TypedDict):
    folders: List[str]
    include_patterns: List[str]
    exclude_patterns: List[str]
    project: str
    repo: str
    license: str
    copyright_owner: str
    copyright_start_date: str
    copyright_end_date: str
    files: Dict[str, FileEntry]
    authors:Dict[str,str]


class Language(enum.Enum):
    CPP = enum.auto()
    PYTHON = enum.auto()
    JAVASCRIPT = enum.auto()
    TYPESCRIPT = enum.auto()
    BASH = enum.auto()
    CMAKE = enum.auto()


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

        if 'authors' not in self.config:
            self.config['authors'] = {}

    def write_config(self) -> None:
        with open(self.banner_file, 'w', encoding='utf8') as f:
            json.dump(self.config, f, indent=4)

    def get_language(self, filename: str) -> Language:
        p = pathlib.Path(filename)
        extension = p.suffix.lower()

        if extension in ['.py', '.pyi']:
            return Language.PYTHON

        if extension in ['.c', '.cpp', '.h', '.hpp']:
            return Language.CPP

        if extension in ['.js']:
            return Language.JAVASCRIPT

        if extension in ['.ts']:
            return Language.TYPESCRIPT

        if extension in ['.sh']:
            return Language.BASH

        if extension in ['.cmake']:
            return Language.CMAKE
        
        if os.path.basename(filename) == 'CMakeLists.txt':
            return Language.CMAKE

        raise Exception(f'Unknown language for file:  {filename}')

    def scan_files(self) -> Generator[str, None, None]:
        folders_to_scan = self.config.get('folders',['.'])
        if len(folders_to_scan) == 0:
            folders_to_scan = ['.']

        for start_folder in folders_to_scan:
            for root, subdirs, files in os.walk(path.join(self.base_folder, start_folder)):
                included_files:Set[str] = set()
                for file in files:
                    filename = self.make_name(path.join(root, file))
                    for include_pattern in self.config.get('include_patterns', ''):
                        if fnmatch(filename, include_pattern):
                            excluded = False
                            for exclude_pattern in self.config.get('exclude_patterns', ''):
                                if fnmatch(filename, exclude_pattern):
                                    excluded = True
                            if not excluded:
                                included_files.add(filename)

                new_subdirs:List[str] = []
                for subdir in subdirs:
                    subdirname = self.make_name(path.join(root, subdir))
                    excluded = False
                    for exclude_pattern in self.config.get('exclude_patterns', ''):
                        if fnmatch(subdirname, exclude_pattern):
                            excluded = True

                    if not excluded:
                        new_subdirs.append(subdirname)

                subdirs = new_subdirs

                if len(included_files) == 0:
                    continue

                for filename in included_files:
                    yield filename.replace('\\', '/')

    def make_name(self, pathname:str) -> str:
        return path.relpath(path.abspath(path.normpath(pathname)), path.abspath(self.base_folder))

    def add_files(self, files: List[str], remove_not_present: bool = False) -> None:
        files_to_remove:List[str] = []

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
        # But I don't want to spend time on file parsing. There must be a tool that does that.

        language = self.get_language(filepath)
        docstring = file_entry['docstring']
        defaultadd_shebang = False
        if language == Language.BASH:
            defaultadd_shebang=True

        add_shebang = defaultadd_shebang if 'add_shebang' not in file_entry else file_entry['add_shebang']
        author="" if 'author' not in file_entry else file_entry['author']
        contributors=[] if 'contributors' not in file_entry else file_entry['contributors']


        if language == Language.CPP:
            skip_patterns = []
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = ''
        elif language == Language.JAVASCRIPT:
            skip_patterns = []
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = '#!/bin/node' if add_shebang else ''
        elif language == Language.TYPESCRIPT:
            skip_patterns = [r'\/\/\s*@ts-(no)?check']
            comment_pattern = [r'^\s*//(.*)', r'^\s+$']
            shebang = '#!/bin/node' if add_shebang else ''
        elif language == Language.PYTHON:
            skip_patterns = []
            comment_pattern = [r'^\s*#(.*)', r'^\s+$']
            shebang = '#!/usr/bin/env python3' if add_shebang else ''
        elif language == Language.BASH:
            skip_patterns = []
            comment_pattern = [r'^\s*#(.*)', r'^\s+$']
            shebang = '#!/bin/bash' if add_shebang else ''
        elif language == Language.CMAKE:
            skip_patterns = []
            comment_pattern = [r'^\s*#(.*)', r'^\s+$']
            shebang = ''
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

        double_date = True
        start_date = self.config['copyright_start_date']
        end_date = self.config['copyright_end_date']
        if not start_date:
            start_date = get_first_edit_year(filepath)
            double_date = False

        if not end_date:
            double_date = False

        if start_date == end_date:
            double_date = False
        
        if double_date:
            rendered_date = '%s-%s' % (start_date, end_date)
        else:
            rendered_date = start_date

        tab_space=4
        def tab(count:int) -> str:
            return ' '*(tab_space*count)
        if language in [Language.CPP, Language.JAVASCRIPT, language == Language.TYPESCRIPT]:
            comment_char="//"
        elif language in [Language.PYTHON, Language.BASH, Language.CMAKE]:
            comment_char="#"
        else:
            raise Exception('Unknown language %s' % language)

        new_header=""
        if add_shebang:
            new_header += f"{shebang}\n\n"
        new_header += f'{comment_char}{tab(1)}{path.basename(filepath)}\n'
        if len(docstring) > 0:
            formatted_docstring = self.format_docstring(docstring, comment_char, tab(2))
            new_header += f'{comment_char}{formatted_docstring}\n'

        new_header += f'{comment_char}\n'
        def make_list_item(indent:int, key:str, val:str) -> str:
            list_prefix = tab(indent)[:-1] + '-'
            return f'{comment_char}{list_prefix} {key} : {val}\n'
        
        if len(author) > 0:
            author_fullname = self.config['authors'][file_entry['author']]
            new_header += make_list_item(1, 'Author', author_fullname)
        
        if len(contributors) > 0:
            new_header += make_list_item(1, 'Contributors', "")
            for contributor in contributors:
                contributor_fullname = self.config['authors'][contributor]
                new_header += f'{comment_char}{tab(2)[:-1]}- {contributor_fullname}\n'
        
        new_header += make_list_item(1, 'License', self.config['license'])
        project_val = self.config['project']
        if 'repo' in self.config and len(self.config['repo']) > 0:
            project_val += f" ({self.config['repo']})"
        new_header += make_list_item(1, 'Project', project_val)
                    
        new_header += f'{comment_char}\n'
        new_header += f"{comment_char}{tab(1)}Copyright (c) {rendered_date} {self.config['copyright_owner']}\n"

        header_lines = new_header.split('\n')
        header_lines.reverse()

        for line_to_insert in header_lines:
            all_lines.insert(start_line, line_to_insert + '\n')

        with open(filepath, 'w', encoding='utf8') as f:
            f.writelines(all_lines)

    def format_docstring(self, docstring: str, comment_char:str, spacer:str):
        chunk_size = 80
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
            docstring = spacer + docstring

        docstring = docstring.replace('\n', f'\n{comment_char}' + spacer)
        
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
