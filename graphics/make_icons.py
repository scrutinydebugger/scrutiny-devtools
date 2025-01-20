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
    parser.add_argument('--file', default='default.json')
    parser.add_argument('--output', default='output')
    args = parser.parse_args()

    with open(args.file) as f:
        formats = cast(Dict[str, Format], json.load(f))

    os.makedirs(args.output, exist_ok=True)

    for name, config in formats.items():
        src_image = Image.open( os.path.join(os.path.dirname(args.file), config['src']))
        for format in config['formats']:
            assert len(format) == 2

            dst = src_image.copy()
            dst.thumbnail(tuple(format), Image.LANCZOS)
            dst.save(os.path.join(args.output, f"{name}_{format[0]}x{format[1]}.png"), "PNG")

if __name__ == '__main__':
    sys.exit(main())