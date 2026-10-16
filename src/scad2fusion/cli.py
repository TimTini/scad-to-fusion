"""Command-line entry point; output scripts execute separately inside Fusion."""
import argparse
import json
import sys

from .generator import generate_package


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='OpenSCAD source file')
    parser.add_argument('--output', required=True, help='New output folder, named with a Python identifier')
    parser.add_argument('-D', dest='definitions', action='append', default=[], metavar='NAME=VALUE')
    args = parser.parse_args(argv)
    try:
        overrides = {}
        for definition in args.definitions:
            name, separator, raw = definition.partition('=')
            if not separator or not name:
                raise ValueError('Expected -D NAME=VALUE')
            value = json.loads(raw)
            if not isinstance(value, (int, float, bool, str, list)):
                raise ValueError('Override must be a JSON number, boolean, string or array: ' + name)
            overrides[name] = value
        report = generate_package(args.input, args.output, overrides)
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print('Generated: ' + args.output + '; Fusion runtime: ' + report['validation']['fusion_runtime'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
