import sys
import argparse
from PIL import Image
import os
import json

from typing import Dict, TypedDict, List, cast  

class Format(TypedDict):
    src:str
    formats:List[List[int]]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('theme', choices=['light', 'dark'])
    parser.add_argument('--output', default='output')
    args = parser.parse_args()

    os.chdir(os.path.join(os.path.dirname(__file__)))
    
    common_file = 'common.json'
    theme_file = args.theme + '.json'
    with open(common_file) as f:
        common_formats = cast(Dict[str, Format], json.load(f))
    with open(theme_file) as f:
        theme_formats = cast(Dict[str, Format], json.load(f))

    for name in theme_formats.keys():
        if name in common_formats:
            del common_formats[name]

    os.makedirs(args.output, exist_ok=True)

    for format_dict in [common_formats, theme_formats]:
        for name, config in format_dict.items():
            src_image = Image.open( config['src'] )
            for format in config['formats']:
                assert len(format) == 2

                dst = src_image.copy()
                dst.thumbnail(tuple(format), Image.LANCZOS)
                dst.save(os.path.join(args.output, f"{name}_{format[0]}x{format[1]}.png"), "PNG")

if __name__ == '__main__':
    sys.exit(main())