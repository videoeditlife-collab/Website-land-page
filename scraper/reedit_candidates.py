#!/usr/bin/env python3
"""
Creators whose raw long-form footage can be re-edited into 60-second clips
for X, and the three videos of each worth cutting first. Driven by a niche
config such as niches/survival_camping_challenges.yaml.

    # the config's search queries, as a term file for discovery
    python reedit_candidates.py terms niches/survival_camping_challenges.yaml > reedit_terms.txt

    # after scoring with run_lead_generator.py --videos-out
    python reedit_candidates.py select niches/survival_camping_challenges.yaml \
        --leads "results/reedit_*_leads.csv" --videos "results/reedit_*.videos.jsonl" \
        --creators results/reedit_creators.csv --candidates results/reedit_candidates.csv

How the config is applied, where scraping differs from the API it was
written for:

  classifier   each sampled title is labelled with the config's labels by
               keyword (LABEL_WORDS below). Titles no keyword reaches are
               left unlabelled rather than counted as 'other', the same rule
               the main scorer uses: counting them pushed every channel under
               0.6. niche_consistency is the share of labelled titles whose
               label is in in_niche - the in-niche labels are one family, so
               a channel splitting between winter and solo camping still
               counts. The channel's most common label must also be in niche.
  long form    min_long_form_in_sample counts sampled videos of at least
               reedit_candidates.min_duration_seconds.
  views        rounded as YouTube publishes them ("12K views").
"""

import argparse
import csv
import glob
import json
import re
import sys
from collections import Counter

import yaml

from pick_sellers import load, normalise, to_int

# Keyword evidence for each config label. Anchored at a word start, like the
# main scorer, so 'camp' matches "camping" but nothing mid-word.
LABEL_WORDS = {
    'survival': ('survival', 'survive', 'surviving', 'stranded', 'lost in',
                 'no food', 'no water', 'shtf', 'prepper', 'bug out'),
    'bushcraft': ('bushcraft', 'primitive', 'shelter', 'debris hut', 'lean to',
                  'lean-to', 'bow drill', 'friction fire', 'ferro', 'axe',
                  'log cabin', 'dugout', 'woodcraft'),
    'solo_camping': ('solo camp', 'camping alone', 'alone in', 'solo overnight',
                     'wild camp', 'stealth camp', 'solo hike', 'by myself'),
    'winter_camping': ('winter camp', 'snow', 'blizzard', 'freezing', 'ice',
                       'hot tent', 'frozen', 'below zero', 'minus'),
    'car_camping': ('car camp', 'truck camp', 'suv camp', 'van camp',
                    'camping in my car', 'sleeping in my car', 'truck bed',
                    'rooftop tent', 'camper'),
    'wilderness_challenge': ('challenge', 'last to leave', '7 days', '24 hours',
                             '48 hours', '72 hour', '72 hours', '30 days',
                             'i spent', 'can i survive'),
    'outdoor_adventure_irl': ('camping', 'camp', 'hike', 'hiking', 'backpacking',
                              'overnight', 'wilderness', 'canoe', 'kayak',
                              'storm', 'rain', 'tent', 'hammock', 'forest',
                              'woods', 'mountain', 'backcountry', 'trail'),
    'gear_review_only': ('review', 'unboxing', 'tested', ' vs ', 'best budget',
                         'gear haul', 'buyers guide', "buyer's guide"),
    'hunting_fishing_only': ('hunting', 'hunt', 'fishing', 'fish', 'deer',
                             'elk', 'bass', 'trout', 'catch and', 'bowhunt',
                             'duck', 'turkey'),
    'gaming': ('minecraft', 'fortnite', 'gameplay', 'dayz', 'the forest',
               'sons of the forest', 'gaming', 'lets play', "let's play"),
    'vlog_general': ('vlog', 'day in my life', 'haul', 'grwm', 'q&a', 'qna'),
    'reaction': ('react', 'reacts', 'reaction', 'reacting'),
}

_RE_CACHE = {}


def hits(words, text):
    found = []
    for word in words:
        rx = _RE_CACHE.get(word)
        if rx is None:
            rx = _RE_CACHE[word] = re.compile(
                r'(?<![A-Za-z0-9])' + re.escape(word.strip()), re.IGNORECASE)
        if rx.search(text):
            found.append(word.strip())
    return found


def label_title(title, in_niche, off_niche):
    """The config label with most keyword hits; in-niche wins a tie."""
    best, score = None, 0
    for label in list(in_niche) + list(off_niche):
        count = len(hits(LABEL_WORDS.get(label, ()), title))
        if count > score:
            best, score = label, count
    # A gear review title that also names a trip ("Testing my tent in a
    # storm") is footage, not a review; let an in-niche hit win.
    if best in off_niche and best == 'gear_review_only':
        for label in in_niche:
            if hits(LABEL_WORDS.get(label, ()), title):
                return label
    return best


def classify(titles, in_niche, off_niche):
    labels = [label_title(t, in_niche, off_niche) for t in titles]
    labelled = [l for l in labels if l]
    if not labelled:
        return '', 0.0, labels
    top = Counter(labelled).most_common(1)[0][0]
    share = sum(1 for l in labelled if l in in_niche) / len(labelled)
    return top, round(share, 2), labels


def x_handles(description, links, patterns):
    reserved = {'intent', 'share', 'home', 'i', 'search', 'hashtag', 'login',
                'signup', 'explore', 'settings'}
    found = []
    for text in [description or ''] + list(links or []):
        for pattern in patterns:
            for handle in re.findall(pattern, text, re.IGNORECASE):
                if handle.lower() not in reserved and handle not in found:
                    found.append(handle)
    return found


def stakes_score(title, keywords):
    matched = []
    low = (title or '').lower()
    for word in keywords:
        word = str(word).lower()
        if word.startswith('-') and word[1:].isdigit():
            # "-20" means a temperature: match -20, -20°, -20F, not 2020-21.
            if re.search(r'(?<![\d])' + re.escape(word) + r'(?!\d)', low):
                matched.append(word)
        elif hits([word], low):
            matched.append(word)
    return matched


def load_videos(patterns):
    by_channel = {}
    for pattern in patterns:
        for path in sorted(glob.glob(pattern)):
            with open(path, encoding='utf-8') as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    key = normalise(record.get('channel_url'))
                    if key:
                        by_channel[key] = record      # newest line wins
    return by_channel


def select(cfg, leads, videos, exclude):
    niche = cfg['niche']
    in_niche = niche['classifier_labels']['in_niche']
    off_niche = niche['classifier_labels']['off_niche']
    f = cfg['filters']
    rc = cfg['reedit_candidates']
    weights = rc['score']
    patterns = cfg['extra_columns']['x_handle']['patterns']

    creators, candidates, reasons = [], [], Counter()
    for row in leads:
        key = normalise(row.get('Channel Link'))
        if key in exclude:
            reasons['excluded'] += 1
            continue
        record = videos.get(key)
        if not record:
            reasons['no video data (scored without --videos-out)'] += 1
            continue
        subs = to_int(row.get('Subscriber Count'))
        median = to_int(row.get('median_views'))
        days = row.get('days_since_last_upload')
        days = to_int(days) if str(days or '').strip() else 999
        sample = record.get('videos') or []
        long_form = [v for v in sample
                     if (v.get('seconds') or 0) >= rc['min_duration_seconds']]

        label, share, _ = classify([v.get('title', '') for v in sample],
                                   in_niche, off_niche)
        checks = [
            (subs >= f['subscriber_min'], 'under subscriber_min'),
            (subs <= f['subscriber_max'], 'over subscriber_max'),
            (median >= f['median_views_min'], 'median views too low'),
            (len(long_form) >= f['min_long_form_in_sample'], 'too few long videos'),
            (days <= f['max_days_since_upload'], 'no recent upload'),
            (label in in_niche and share >= 0.6, 'off niche'),
        ]
        failed = [why for ok, why in checks if not ok]
        if failed:
            reasons[failed[0]] += 1
            continue

        ranked = []
        for v in long_form:
            ratio = round((v.get('views') or 0) / median, 2) if median else 0.0
            matched = stakes_score(v.get('title', ''), rc['stakes_keywords'])
            score = (ratio * weights['views_vs_channel_median_weight']
                     + len(matched) * weights['stakes_keyword_weight'])
            ranked.append((score, ratio, matched, v))
        ranked.sort(key=lambda r: -r[0])
        picks = ranked[:rc['per_creator']]

        handles = x_handles(record.get('description'), record.get('links'),
                            patterns)
        out = {
            'Creator Name': row.get('Creator Name', ''),
            'Channel Link': row.get('Channel Link', ''),
            'Subscriber Count': subs,
            'median_views': median,
            'days_since_last_upload': days,
            'long_form_in_sample': len(long_form),
            'niche_label': label,
            'niche_consistency': share,
            'Email': row.get('Email', ''),
            'x_handle': handles[0] if handles else '',
            'x_handle_source': 'channel links' if handles else 'manual',
            'x_handles_all': ' '.join(handles),
            'reedit_status': 'not_started',
            'reedit_post_url': '',
        }
        for rank, (score, ratio, matched, v) in enumerate(picks, 1):
            out[f'clip_{rank}_url'] = f"https://www.youtube.com/watch?v={v['id']}"
            out[f'clip_{rank}_title'] = v.get('title', '')
            candidates.append({
                'Creator Name': out['Creator Name'],
                'Channel Link': out['Channel Link'],
                'x_handle': out['x_handle'],
                'rank': rank,
                'score': round(score, 2),
                'video_id': v['id'],
                'video_url': f"https://www.youtube.com/watch?v={v['id']}",
                'title': v.get('title', ''),
                'duration_seconds': v.get('seconds'),
                'view_count': v.get('views'),
                'views_vs_channel_median': ratio,
                'stakes_keywords_matched': '; '.join(matched),
            })
        creators.append(out)

    creators.sort(key=lambda r: -r['median_views'])
    return creators, candidates, reasons


def write(path, rows):
    if not rows:
        return
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    with open(path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    t = sub.add_parser('terms', help="print the config's search queries")
    t.add_argument('config')
    s = sub.add_parser('select', help='filter creators and rank clips')
    s.add_argument('config')
    s.add_argument('--leads', action='append', required=True)
    s.add_argument('--videos', action='append', required=True)
    s.add_argument('--exclude', action='append', default=[])
    s.add_argument('--creators', required=True)
    s.add_argument('--candidates', required=True)
    args = parser.parse_args()

    with open(args.config, encoding='utf-8') as handle:
        cfg = yaml.safe_load(handle)

    if args.command == 'terms':
        print('\n'.join(cfg['niche']['search_queries']))
        return 0

    from pick_sellers import channel_keys
    exclude = set()
    for pattern in args.exclude:
        for path in sorted(glob.glob(pattern)):
            exclude |= channel_keys(path)

    creators, candidates, reasons = select(
        cfg, load(args.leads), load_videos(args.videos), exclude)
    write(args.creators, creators)
    write(args.candidates, candidates)
    print(f"{len(creators)} creators kept, {len(candidates)} clip candidates")
    for why, n in reasons.most_common():
        print(f"  set aside: {why}: {n}")
    print(f"-> {args.creators}\n-> {args.candidates}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
