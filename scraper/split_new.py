#!/usr/bin/env python3
"""
Turn a discovered channel list into scoring batches of channels not seen before.

Discovery returns many channels that an earlier pass already found and
scored. Scoring them again wastes an hour of runner time and, worse, lets an
old prospect come back looking new. This removes every channel named in the
exclusion files, then splits what is left into parts small enough to score
in one run each (about 150 channels takes 35-40 minutes).

    python split_new.py results/discovered_survival.txt \
        --exclude results/already_scored.txt \
        --exclude "results/*_leads.csv" \
        --prefix results/survival_new --size 150

writes results/survival_new_1.txt, results/survival_new_2.txt, ... and prints
how many channels each holds. Feed each part to run_lead_generator.py (or to
the Lead generator workflow) separately, in parallel if you like.
"""

import argparse
import glob
import sys

from pick_sellers import channel_keys, normalise


def read_list(path):
    """URLs from a discovered .txt list or a CSV, normalised, in order."""
    if path.lower().endswith('.csv'):
        return sorted(channel_keys(path))
    urls = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if line.strip() and not line.startswith('#'):
                key = normalise(line)
                if key:
                    urls.append(key)
    return urls


def split(urls, size):
    """Even parts of at most about `size`, rather than N full parts and a stub."""
    if not urls:
        return []
    parts = max(1, round(len(urls) / size))
    per = -(-len(urls) // parts)
    return [urls[i * per:(i + 1) * per] for i in range(parts)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', nargs='+',
                        help='Discovered lists (.txt) or CSVs of channels')
    parser.add_argument('--exclude', action='append', default=[],
                        help='CSV or txt of channels to drop, repeatable, '
                             'globs ok. Use every file of channels already '
                             'scored or already sent.')
    parser.add_argument('--prefix', required=True,
                        help='Output path prefix: PREFIX_1.txt, PREFIX_2.txt ...')
    parser.add_argument('--size', type=int, default=150,
                        help='Target channels per part (default: 150)')
    args = parser.parse_args()

    excluded = set()
    for pattern in args.exclude:
        for path in sorted(glob.glob(pattern)):
            excluded |= channel_keys(path)

    seen, fresh, total = set(), [], 0
    for pattern in args.sources:
        for path in sorted(glob.glob(pattern)):
            for key in read_list(path):
                total += 1
                if key in excluded or key in seen:
                    continue
                seen.add(key)
                fresh.append(key)

    print(f"{total} channels read, {len(excluded)} excluded, "
          f"{len(fresh)} new")
    if not fresh:
        print("nothing new to score", file=sys.stderr)
        return 1
    for number, part in enumerate(split(fresh, args.size), 1):
        path = f"{args.prefix}_{number}.txt"
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(part) + '\n')
        print(f"  {path}: {len(part)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
