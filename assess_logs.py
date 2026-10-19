#!/usr/bin/env python3
"""Prepare a public review packet or bind an independently authored P/A/E review."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent/'src'))
from pearl.evaluation.log_review import prepare, bind_review, dispatch_assignment, require_pass


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('prepare'); a.add_argument('log_dir', type=Path)
    a.add_argument('--output', type=Path, required=True); a.add_argument('--reviewer', required=True)
    b = sub.add_parser('bind'); b.add_argument('packet', type=Path); b.add_argument('--review', type=Path, required=True)
    b.add_argument('--require-pass', action='store_true')
    c = sub.add_parser('assignment'); c.add_argument('packet', type=Path)
    args = p.parse_args(argv)
    try:
        if args.command == 'prepare': value = prepare(args.log_dir, args.output, args.reviewer)
        elif args.command == 'assignment': value = dispatch_assignment(args.packet.resolve(), lambda a: a)
        else:
            value = bind_review(args.packet, args.review)
            if args.require_pass: require_pass(value)
        print(json.dumps(value, indent=2, allow_nan=False)); return 0
    except Exception as exc:
        print(f'Assessment stopped: {exc}', file=sys.stderr); return 1

if __name__ == '__main__':
    raise SystemExit(main())
