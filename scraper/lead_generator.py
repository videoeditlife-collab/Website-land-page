#!/usr/bin/env python3
"""
Lead Generator — Widget 18 spec.

Scores creators for return on time investment. Columns 1-17 match the Lead
Generator sheet in order, so the CSV pastes straight in; helper columns follow.

The spec is written against the YouTube Data API v3. No API key is available
here, so fields come from scraping instead. That changes the precision of three
things and nothing else, but the differences matter when reading a rating:

  view counts     the Videos tab publishes "12K views", not 12,431, so avg and
                  median are rounded to 2-3 significant figures
  upload dates    relative ("3 weeks ago"), so days_since_last_upload and
                  uploads_90d are bucketed rather than exact
  Shorts          filtered on duration text from the grid; a video with no
                  duration shown cannot be classified and is kept

Every rounded field is marked in the output so a rating is never read as more
precise than its inputs.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median


# ============================================================================
# CONFIG — values tagged [lesson] come from Widget 18, [default] are tunable
# ============================================================================

@dataclass
class Config:
    # sample
    sample_size: int = 15                  # [default]
    shorts_max_seconds: int = 180          # [default]
    min_video_age_days: int = 14           # [default]

    # rating
    high_min_views: int = 3000             # [lesson]
    use_median: bool = True                # [default] False for the lesson's exact rule
    consistent_min_uploads_90d: int = 10   # [default] weekly with some slack
    stale_after_days: int = 30             # [default]
    low_max_uploads_90d: int = 2           # [default]
    low_max_views: int = 1000              # [default]
    clear_niche_min: float = 0.6           # [default]
    low_traits_override: int = 3           # [default]

    # review flags
    outlier_ratio: float = 2.0             # [default] mean more than 2x median
    cold_audience_ratio: float = 0.03      # [default] avg views under 3% of subs


@dataclass
class Creator:
    """One row. Defaults let a partially-collected creator still be rated."""
    creator_name: str = ''
    channel_url: str = ''
    channel_id: str = ''
    email: str = ''
    email_source: str = 'manual'
    sells_product: bool = False
    product_type: str = 'none'
    niche: str = ''
    avg_views: int = 0
    median_views: int = 0
    subscriber_count: int = 0
    uploads_90d: int = 0
    days_since_last_upload: int = None
    views_trend: float = None
    niche_consistency: float = 0.0
    # The per-title labels behind the verdict, so a borderline consistency
    # score can be checked against what produced it.
    niche_evidence: str = ''
    has_monetization: bool = False
    has_sponsors: bool = False
    monetization_signals: list = field(default_factory=list)
    product_price_seen: str = ''
    latest_video_url: str = ''
    top_video_url: str = ''
    sample_size_used: int = 0
    views_are_rounded: bool = True
    dates_are_bucketed: bool = True

    @property
    def views_to_subs(self):
        if not self.subscriber_count:
            return None
        return round(self.avg_views / self.subscriber_count, 4)


# ============================================================================
# RATING — the spec's decision order, unchanged
# ============================================================================

def rate_roti(c, cfg=Config()):
    reasons, review = [], False
    views = c.median_views if cfg.use_median else c.avg_views
    stale = (c.days_since_last_upload is None
             or c.days_since_last_upload > cfg.stale_after_days)
    consistent = c.uploads_90d >= cfg.consistent_min_uploads_90d and not stale
    clear_niche = c.niche_consistency >= cfg.clear_niche_min

    # review flags, independent of the rating
    if c.median_views and c.avg_views > cfg.outlier_ratio * c.median_views:
        reasons.append("one video is carrying the average")
        review = True
    if c.subscriber_count and c.avg_views / c.subscriber_count < cfg.cold_audience_ratio:
        reasons.append("views are low for the subscriber count")
        review = True

    # High
    if c.sells_product and consistent and clear_niche and views >= cfg.high_min_views:
        reasons.append("sells a product, uploads consistently, clear niche, "
                       "views over threshold")
        # quality, overwhelm and growth can't be scraped, so every High gets a look
        return "High", reasons, True

    # Low
    low_traits = {
        "rare uploads": c.uploads_90d <= cfg.low_max_uploads_90d,
        "stale channel": stale,
        "no clear niche": not clear_niche,
        "low views": views < cfg.low_max_views,
    }
    hits = [name for name, hit in low_traits.items() if hit]
    if (not c.has_monetization and hits) or len(hits) >= cfg.low_traits_override:
        if not c.has_monetization:
            reasons.append("no monetization found")
        return "Low", reasons + hits, review

    # Mid
    if c.has_monetization:
        reasons.append("monetized but missing at least one High criterion")
    else:
        reasons.append("no monetization found, check link hubs and the About "
                       "page by hand")
        review = True
    return "Mid", reasons, review


# ============================================================================
# MONETIZATION AND PRODUCT DETECTION
# ============================================================================

CHECKOUT_DOMAINS = (
    'stan.store', 'gumroad.com', 'mykajabi.com', 'kajabi.com', 'teachable.com',
    'thinkific.com', 'podia.com', 'payhip.com', 'lemonsqueezy.com',
    'myshopify.com', 'samcart.com', 'circle.so', 'whop.com',
)
COMMUNITY_DOMAINS = ('skool.com', 'patreon.com', 'ko-fi.com/memberships')
MERCH_WORDS = ('merch', 'spring.com', 'teespring', 'fourthwall', 'represent.com')
AFFILIATE_SIGNALS = ('amzn.to', 'amazon.com/shop', 'geni.us', 'affiliate',
                     'i earn a commission', 'commission on', 'shopmy', 'ltk.')
BOOKING_DOMAINS = ('calendly.com', 'cal.com', 'acuityscheduling', 'tidycal')
OFFER_WORDS = ('course', 'program', 'coaching', 'masterclass', 'accelerator',
               'cohort', 'bootcamp', 'mentorship', 'apply now', 'book a call',
               # Singular forms included: 'presets' alone missed "preset pack".
               # These are what photography and filmmaking creators sell, and
               # the pipeline had no term for any of them.
               'work with me', 'preset', 'template', 'ebook', 'e-book',
               'lut pack', 'luts', 'lightroom preset', 'brush pack',
               'sound pack', 'transition pack', 'overlay pack')

SPONSOR_RE = re.compile(
    r'(sponsored by|thanks to [^.\n]{2,40} for sponsoring|this video is '
    r'sponsored|use code|promo code|discount code|#ad\b|paid partnership)',
    re.IGNORECASE)

LEAD_MAGNET_RE = re.compile(
    r'\bfree\b[^.\n]{0,30}\b(guide|ebook|e-book|checklist|download|'
    r'newsletter|training|workshop|template)\b', re.IGNORECASE)

PRICE_RE = re.compile(r'[$£€]\s?\d[\d,]*(?:\.\d{2})?(?:\s?[kK])?')

# A store path on the creator's own site. Peter McKinnon sells presets and an
# e-book from petermckinnon.com, and the detector read him as affiliate_only:
# offer words set has_monetization but never sells_product, which only a
# checkout DOMAIN could set. That under-counts every creator who sells from
# their own domain rather than through Gumroad or Stan - most established ones.
STORE_PATHS = ('/shop', '/store', '/products', '/product/', '/presets',
               '/collections', '/merch', '/pricing', '/checkout')

# Storefronts on these are other people's products earning a commission, so a
# store path on one proves nothing about what the creator sells.
AFFILIATE_HOSTS = ('amazon.', 'amzn.to', 'ebay.', 'aliexpress.', 'rstyle.me',
                   'shareasale', 'awin1.com', 'impact.com', 'sovrn.com',
                   'bhphotovideo.com', 'adorama.com')

# Phrases that contain an offer word without being an offer. Travel channels
# say "loyalty program" and "of course" constantly; stripping these before the
# offer words are looked for keeps them from counting at all.
OFFER_DECOYS = (
    'of course', 'golf course', 'race course', 'racecourse', 'obstacle course',
    'crash course', 'course of', 'loyalty program', 'rewards program',
    'points program', 'frequent flyer program', 'frequent flier program',
    'tv program', 'affiliate program', 'partner program', 'referral program',
    'travel program', 'exchange program',
)

# How close a price has to sit to an offer word to be its price.
OFFER_PRICE_WINDOW = 60


def _strip_decoys(blob):
    for phrase in OFFER_DECOYS:
        blob = blob.replace(phrase, ' ')
    return blob


def offer_price(blob, words):
    """
    A price that belongs to an offer: on the same line as an offer word and
    within OFFER_PRICE_WINDOW characters of it, or '' if there is none.

    The first version accepted a price anywhere in the text, and re-scoring the
    channels it was meant to recover showed what that does. Eat Sleep Disney
    read as selling an e-book at $4,500 - the cost of a Disney trip - and
    LifeWithUsTV an e-book at $510. Eat Sleep Cruise and Travel Tips by Laurie
    were credited with a "program" that was a cruise or airline loyalty
    programme. An offer and its price sit together on one line of a
    description; a gear list puts each item on a line of its own, so a camera
    price rarely shares a line with a preset pack.

    Known limit: a gear price and an offer word on the same short line will
    still match.
    """
    for line in (blob or '').split('\n'):
        word_at = [i for w in words for i in _positions(line, w)]
        if not word_at:
            continue
        for match in PRICE_RE.finditer(line):
            if min(abs(match.start() - i) for i in word_at) <= OFFER_PRICE_WINDOW:
                return match.group(0).strip()
    return ''


def _positions(text, word):
    start, out = 0, []
    while True:
        i = text.find(word, start)
        if i < 0:
            return out
        out.append(i)
        start = i + 1

LINK_HUBS = ('linktr.ee', 'beacons.ai', 'komi.io', 'stan.store', 'linkin.bio',
             'milkshake.app', 'bio.link', 'flowcode', 'linkpop')


def detect_monetization(text, links):
    """
    Work out what a creator sells from their own description and links.

    sells_product means a paid offer they own. has_monetization is anything
    that earns or feeds a funnel - the spec keeps these apart because the
    lesson's Mid examples (affiliate links, a free e-book) monetize without
    selling anything.
    """
    blob = f"{text or ''} {' '.join(links or [])}".lower()
    signals = []
    sells = False
    product_type = 'none'
    monetized = False
    sponsors = False

    def hit(label):
        if label not in signals:
            signals.append(label)

    for domain in CHECKOUT_DOMAINS:
        if domain in blob:
            hit(domain)
            sells, monetized = True, True
            product_type = 'digital_product'

    for domain in COMMUNITY_DOMAINS:
        if domain in blob:
            hit(domain)
            sells, monetized = True, True
            product_type = 'community_or_membership'

    for word in MERCH_WORDS:
        if word in blob:
            hit(word)
            sells, monetized = True, True
            if product_type == 'none':
                product_type = 'merch'

    offer_blob = _strip_decoys(blob)
    offer_words_found = [w for w in OFFER_WORDS if w in offer_blob]
    nearby_price = offer_price(offer_blob, offer_words_found)
    booking_found = [d for d in BOOKING_DOMAINS if d in blob]

    if booking_found:
        for d in booking_found:
            hit(d)
        sells, monetized = True, True
        product_type = 'coaching_or_program'

    # A store path on a domain that is not an affiliate marketplace.
    own_store = []
    for link in (links or []):
        low_link = link.lower()
        if any(host in low_link for host in AFFILIATE_HOSTS):
            continue
        if any(path in low_link for path in STORE_PATHS):
            own_store.append(link)
    if own_store:
        hit('own storefront')
        sells, monetized = True, True
        if product_type == 'none':
            product_type = 'digital_product'

    if offer_words_found:
        for w in offer_words_found:
            hit(w)
        monetized = True
        # An offer word next to a price is a paid offer, wherever it is sold.
        # Without the price it stays unproven: "my free presets" is a lead
        # magnet, and the spec's own Mid example is a free e-book.
        if nearby_price and not sells:
            sells = True
            if product_type in ('none', 'affiliate_only', 'sponsors_only',
                                'lead_magnet_only'):
                product_type = 'digital_product'
        if sells and product_type in ('none', 'digital_product'):
            if any(w in offer_blob for w in ('course', 'masterclass', 'cohort')):
                product_type = 'course'
            elif any(w in offer_blob for w in ('coaching', 'program', 'accelerator',
                                               'mentorship', 'bootcamp')):
                product_type = 'coaching_or_program'

    for signal in AFFILIATE_SIGNALS:
        if signal in blob:
            hit(signal)
            monetized = True
            if not sells:
                product_type = 'affiliate_only'

    if SPONSOR_RE.search(blob):
        hit('sponsor read')
        monetized, sponsors = True, True
        if not sells and product_type == 'none':
            product_type = 'sponsors_only'

    if LEAD_MAGNET_RE.search(blob):
        hit('free lead magnet')
        monetized = True
        if not sells and product_type in ('none',):
            product_type = 'lead_magnet_only'

    # A link hub usually hides the real offer, so flag it rather than guess.
    hubs = [h for h in LINK_HUBS if h in blob]
    for h in hubs:
        hit(f"link hub: {h}")

    # The offer's own price where one was found. Otherwise, only for a sale
    # proven some other way, the first price in the text - which is a guess,
    # and the reason the field must not be read as the product's price
    # without a look.
    price = nearby_price
    if not price and sells:
        found = PRICE_RE.search(text or '')
        if found:
            price = found.group(0).strip()

    return {
        'sells_product': sells,
        'product_type': product_type,
        'has_monetization': monetized,
        'has_sponsors': sponsors,
        'monetization_signals': signals,
        'product_price_seen': price,
        'has_link_hub': bool(hubs),
    }


# ============================================================================
# NICHE
#
# The spec calls for an LLM classifier over a fixed niche list. No model call is
# available inside the runner, so this is keyword voting over the same list.
# It is weaker on titles that name no topic word, which pushes niche_consistency
# down and can cost a channel its "clear niche" criterion - so a Mid produced by
# a low consistency score is worth checking by hand.
# ============================================================================

NICHE_KEYWORDS = {
    'travel': ('travel', 'trip', 'destination', 'vacation', 'holiday', 'cruise',
               'resort', 'hotel', 'flight', 'airport', 'itinerary', 'abroad',
               'backpack', 'road trip', 'city guide', 'visit', 'national park',
               'island', 'beach', 'places', 'country', 'countries', 'airline',
               'airbnb', 'hostel', 'expat', 'living in', 'moved to', 'worth it',
               'tourist', 'sightseeing', 'passport', 'luggage', 'packing'),
    # Strongman and powerlifting vocabulary is folded in here rather than
    # given a niche of its own. A separate strength_sports label would compete
    # with fitness on the same channel - a strongman titles videos "Training
    # Chest" as well as "Atlas Stone PR" - and split the vote, landing the
    # channel at 0.5 and under the 0.6 clear-niche gate. That is exactly how
    # the martial arts pass held back Tim Welch at 70,000 median views. A
    # less precise label that gates correctly beats a precise one that does
    # not, because the gate is what the shortlist is built on.
    # Bare 'lift' is gone: substring matching put it inside "Uplifting
    # Stories From The Road" and inside the British sense of a lift as an
    # elevator, both of which are travel titles. The specific compounds below
    # carry the niche without it.
    'fitness': ('workout', 'gym', 'fitness', 'training', 'muscle', 'lift',
                'physique', 'squat', 'bench', 'cardio', 'hyrox', 'crossfit',
                'calisthenics', 'transformation', 'reps', 'strength',
                'strongman', 'strongest man', 'powerlifting', 'powerlifter',
                'deadlift', 'atlas stone', 'log press', 'yoke walk',
                'farmers walk', 'overhead press', 'tire flip', 'truck pull',
                'sandbag', 'grip strength', 'barbell', 'dumbbell',
                'kettlebell', 'hypertrophy', 'bulking', 'one rep max', '1rm',
                'lifting belt', 'knee sleeves', 'highland games',
                'arm wrestling', 'personal record', 'weightlifting',
                'powerlift', 'lifting weights', 'lift heavy', 'heavy lifting',
                'olympic lifting', 'bodybuilding'),
    'running_endurance': ('marathon', 'running', 'runner', '5k', '10k',
                          'triathlon', 'ironman', 'ultra', 'pace', 'cycling'),
    'nutrition': ('nutrition', 'macros', 'protein', 'diet', 'meal prep',
                  'calories', 'eating'),
    'finance': ('money', 'budget', 'invest', 'stocks', 'savings', 'debt',
                'retire', 'income', 'tax', 'wealth'),
    # 'review' and 'setup' were here and are far too generic - every niche
    # reviews things, so gear-testing outdoors channels classified as tech.
    'tech': ('iphone', 'android', 'smartphone', 'laptop', 'pc build', 'gpu',
             'keyboard', 'headphones', 'gadget', 'software', 'tech review',
             'unboxing tech', 'ai tools'),
    'business': ('business', 'client', 'freelance', 'agency', 'marketing',
                 'startup', 'entrepreneur', 'sales'),
    'lifestyle_vlog': ('vlog', 'day in my life', 'week in my life', 'routine',
                       'apartment', 'morning', 'life update', 'moving'),
    'food': ('cooking', 'recipe', 'bake', 'kitchen', 'restaurant', 'food',
             'eat', 'street food'),
    # Split deliberately into two labels. A stills photographer and a
    # filmmaker are different prospects for an editing service - the
    # filmmaker's editing IS their product - so they must not share a label.
    'photography': ('photography', 'photographer', 'photo', 'portrait',
                    'lightroom', 'editing photos', 'wedding photography',
                    'street photography', 'landscape photography', 'headshot',
                    'studio lighting', 'lighting setup', 'composition',
                    'prime lens', 'shutter', 'aperture', 'exposure',
                    'raw file', 'photoshoot', 'shoot with me', 'film stock',
                    'darkroom', 'medium format', 'client gallery'),
    'filmmaking': ('filmmaking', 'filmmaker', 'cinematic', 'cinematography',
                   'b-roll', 'broll', 'colour grading', 'color grading',
                   'colour grade', 'color grade', 'davinci resolve',
                   'premiere pro', 'final cut', 'lut', 'short film',
                   'video editing', 'editing tutorial', 'gimbal', 'drone shot',
                   'camera movement', 'sound design', 'storyboard',
                   'documentary style', 'camera rig', 'camera settings'),
    # Widened for the martial arts pass. The belt colours and the technique
    # words matter most: a channel's titles are far more often "Escaping side
    # control" or "Blue belt mistakes" than they are the name of the art, so
    # the eleven-keyword list left real martial arts channels below the 0.6
    # consistency gate and out of High.
    'martial_arts': ('bjj', 'jiu jitsu', 'jiujitsu', 'mma', 'boxing', 'boxer',
                     'muay thai', 'karate', 'judo', 'grappling', 'grapple',
                     'sparring', 'spar', 'kickboxing', 'taekwondo', 'wing chun',
                     'krav maga', 'wrestling', 'takedown', 'submission',
                     'armbar', 'triangle choke', 'rear naked', 'guard pass',
                     'side control', 'half guard', 'open guard', 'leg lock',
                     'heel hook', 'kimura', 'no gi', 'nogi', 'gi review',
                     'white belt', 'blue belt', 'purple belt', 'brown belt',
                     'black belt', 'self defence', 'self defense',
                     'martial arts', 'fight camp', 'combat sports', 'dojo',
                     'clinch', 'pad work', 'heavy bag', 'shadow boxing',
                     # Kept as compounds rather than bare words. 'roll' and
                     # 'striking' both match at a word start in travel titles
                     # ("Rolling Coasters", "striking views"), so anchoring
                     # does not save them. ('kata' was listed here as being
                     # inside "Kathmandu" - it is not; that claim was wrong.)
                     'rolling session', 'open mat', 'bjj drilling'),
    'outdoors': ('hiking', 'camping', 'camp', 'van life', 'overland',
                 'fishing', 'bushcraft', 'climbing', 'kayak', 'survival',
                 'backpacking', 'tent', 'wilderness', 'trail', 'hammock',
                 'campfire', 'bivvy', 'shelter', 'forage', 'foraging',
                 'offgrid', 'off grid', 'prepper', 'trek', 'summit',
                 'thru hike', 'thru-hike', 'woodland', 'outdoors',
                 # Added for the solo wild camping pass. Matching is anchored
                 # at a word start, so 'tarp' cannot reach "Starpoint".
                 'tarp', 'bothy', 'canoe', 'backcountry', 'wild camp',
                 'stealth camp', 'overnight in the woods'),
}


# Keyword matching is anchored to the start of a word, not a bare substring.
# Four separate false positives came from plain `keyword in text`: 'eat' inside
# "greatest", "theatre", "treating" and - worst, because it is in so many
# creator titles - "creating"; 'lift' inside "uplifting" and "shoplifting";
# 'roll' inside "controlling"; 'review' inside nothing, but generic enough to
# steal every niche. Each was patched by deleting the keyword, which lost the
# real matches with it.
#
# Anchoring at a word start fixes the class instead, and keeps the suffixes
# that matter: 'camp' still matches "camping" and "campfire", 'lift' still
# matches "lifting", 'eat' still matches "eating", while none of them match
# mid-word any more.
_KEYWORD_RE_CACHE = {}


def keyword_hits(words, text):
    """Which of `words` appear in `text`, matched at a word start."""
    low = text or ''
    found = []
    for word in words:
        pattern = _KEYWORD_RE_CACHE.get(word)
        if pattern is None:
            pattern = re.compile(r'\b' + re.escape(word), re.IGNORECASE)
            _KEYWORD_RE_CACHE[word] = pattern
        if pattern.search(low):
            found.append(word)
    return found


def classify_niche(titles, description=''):
    """
    Dominant niche, plus how consistently the classifiable titles agree.

    The spec defines consistency as the share of all titles carrying the
    dominant label, which assumes the LLM classifier it asks for - that labels
    every title, including "All 9 California National Parks Ranked". Keyword
    voting cannot, and counting an unlabelled title as off-niche pushed every
    channel to 0.5 and blocked all 25 product sellers from High.

    So the denominator is the titles that matched something. That measures
    whether a channel sticks to one topic, which is the criterion, rather than
    whether its titles happen to contain topic words. The share of titles that
    could be labelled at all is returned too, so a thin signal is visible.
    """
    titles = [t for t in (titles or []) if t]
    if not titles:
        return '', 0.0

    votes = {}
    labelled = 0

    for title in titles:
        low = title.lower()
        best, score = None, 0
        for niche, words in NICHE_KEYWORDS.items():
            count = len(keyword_hits(words, low))
            if count > score:
                best, score = niche, count
        if best:
            votes[best] = votes.get(best, 0) + 1
            labelled += 1

    if not votes:
        # Fall back to the channel description so a channel whose titles are
        # all bare place names is not automatically "no niche".
        low = (description or '').lower()
        best, score = None, 0
        for niche, words in NICHE_KEYWORDS.items():
            count = len(keyword_hits(words, low))
            if count > score:
                best, score = niche, count
        return (best or ''), (0.5 if best else 0.0)

    winner = max(votes, key=votes.get)
    return winner, round(votes[winner] / labelled, 2)


def niche_evidence(titles, limit=10):
    """
    Per-title labels behind a niche verdict, for diagnosing one afterwards.

    The martial arts pass held four channels back on niche consistency while
    they beat most of the ones it passed on measured engagement - Tim Welch
    at 70,000 median views and 29 uploads per 90 days was rated Mid on a 0.5
    consistency. Whether that was a misclassification or a fair read of his
    titles could not be settled, because only the verdict was recorded and
    not what produced it. This records the working.
    """
    out = []
    for title in [t for t in (titles or []) if t][:limit]:
        low = title.lower()
        best, score = None, 0
        for niche, words in NICHE_KEYWORDS.items():
            count = len(keyword_hits(words, low))
            if count > score:
                best, score = niche, count
        hits = keyword_hits(NICHE_KEYWORDS.get(best, ()), low) if best else []
        out.append(f"{best or 'none'}[{','.join(hits[:3])}]: {title[:60]}")
    return ' | '.join(out)


# ============================================================================
# SAMPLE STATISTICS
# ============================================================================

def view_stats(view_counts):
    """avg, median and the trend of the last 5 against the 10 before them."""
    counts = [v for v in (view_counts or []) if isinstance(v, int) and v >= 0]
    if not counts:
        return 0, 0, None

    avg = int(sum(counts) / len(counts))
    med = int(median(counts))

    trend = None
    if len(counts) >= 7:
        recent = counts[:5]
        older = counts[5:15]
        if older and median(older):
            trend = round(median(recent) / median(older), 2)

    return avg, med, trend


def to_row(c, roti, reasons, review, cfg=Config()):
    """One output row: sheet columns 1-17 in order, then the helpers."""
    return {
        'Creator Name': c.creator_name,
        'Channel Link': c.channel_url,
        'Email': c.email,
        'Do They Sell a Product': 'Yes' if c.sells_product else 'No',
        'Product Type': c.product_type,
        'Niche': c.niche,
        'Average Views Per Video': c.avg_views,
        'Subscriber Count': c.subscriber_count or '',
        'Value Rating': roti,
        'Editing Weak Spots': '',
        'Editing Strengths': '',
        'Personality Type / On-Camera Presence': '',
        'Outreach Sent': '',
        'Reply Received': '',
        'Meeting Booked': '',
        'Deal Closed': '',
        'Rate / Retainer Value': '',
        'channel_id': c.channel_id,
        'uploads_90d': c.uploads_90d,
        'days_since_last_upload': ('' if c.days_since_last_upload is None
                                   else c.days_since_last_upload),
        'median_views': c.median_views,
        'views_trend': '' if c.views_trend is None else c.views_trend,
        'views_to_subs': '' if c.views_to_subs is None else c.views_to_subs,
        'has_monetization': c.has_monetization,
        'has_sponsors': c.has_sponsors,
        'monetization_signals': '; '.join(c.monetization_signals),
        'product_price_seen': c.product_price_seen,
        'niche_consistency': c.niche_consistency,
        'niche_evidence': c.niche_evidence,
        'email_source': c.email_source,
        'latest_video_url': c.latest_video_url,
        'top_video_url': c.top_video_url,
        'roti_reasons': '; '.join(reasons),
        'needs_review': review,
        'sample_size_used': c.sample_size_used,
        'views_are_rounded': c.views_are_rounded,
        'dates_are_bucketed': c.dates_are_bucketed,
        'scraped_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }


SHEET_COLUMNS = [
    'Creator Name', 'Channel Link', 'Email', 'Do They Sell a Product',
    'Product Type', 'Niche', 'Average Views Per Video', 'Subscriber Count',
    'Value Rating', 'Editing Weak Spots', 'Editing Strengths',
    'Personality Type / On-Camera Presence', 'Outreach Sent', 'Reply Received',
    'Meeting Booked', 'Deal Closed', 'Rate / Retainer Value',
]

HELPER_COLUMNS = [
    'channel_id', 'uploads_90d', 'days_since_last_upload', 'median_views',
    'views_trend', 'views_to_subs', 'has_monetization', 'has_sponsors',
    'monetization_signals', 'product_price_seen', 'niche_consistency',
    'niche_evidence', 'email_source', 'latest_video_url', 'top_video_url', 'roti_reasons',
    'needs_review', 'sample_size_used', 'views_are_rounded',
    'dates_are_bucketed', 'scraped_at',
]

ALL_COLUMNS = SHEET_COLUMNS + HELPER_COLUMNS
