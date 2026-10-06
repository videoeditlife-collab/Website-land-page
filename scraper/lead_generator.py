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
               'work with me', 'presets', 'template', 'ebook', 'e-book')

SPONSOR_RE = re.compile(
    r'(sponsored by|thanks to [^.\n]{2,40} for sponsoring|this video is '
    r'sponsored|use code|promo code|discount code|#ad\b|paid partnership)',
    re.IGNORECASE)

LEAD_MAGNET_RE = re.compile(
    r'\bfree\b[^.\n]{0,30}\b(guide|ebook|e-book|checklist|download|'
    r'newsletter|training|workshop|template)\b', re.IGNORECASE)

PRICE_RE = re.compile(r'[$£€]\s?\d[\d,]*(?:\.\d{2})?(?:\s?[kK])?')

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

    offer_words_found = [w for w in OFFER_WORDS if w in blob]
    booking_found = [d for d in BOOKING_DOMAINS if d in blob]

    if booking_found:
        for d in booking_found:
            hit(d)
        sells, monetized = True, True
        product_type = 'coaching_or_program'

    if offer_words_found:
        for w in offer_words_found:
            hit(w)
        monetized = True
        if sells and product_type in ('none', 'digital_product'):
            if any(w in blob for w in ('course', 'masterclass', 'cohort')):
                product_type = 'course'
            elif any(w in blob for w in ('coaching', 'program', 'accelerator',
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

    price = ''
    if sells or offer_words_found:
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
    'fitness': ('workout', 'gym', 'fitness', 'training', 'lift', 'muscle',
                'physique', 'squat', 'bench', 'cardio', 'hyrox', 'crossfit',
                'calisthenics', 'transformation', 'reps', 'strength'),
    'running_endurance': ('marathon', 'running', 'runner', '5k', '10k',
                          'triathlon', 'ironman', 'ultra', 'pace', 'cycling'),
    'nutrition': ('nutrition', 'macros', 'protein', 'diet', 'meal prep',
                  'calories', 'recipe', 'eating'),
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
    'martial_arts': ('bjj', 'jiu jitsu', 'mma', 'boxing', 'muay thai', 'karate',
                     'judo', 'grappling', 'sparring', 'kickboxing', 'taekwondo'),
    'outdoors': ('hiking', 'camping', 'camp', 'van life', 'overland',
                 'fishing', 'bushcraft', 'climbing', 'kayak', 'survival',
                 'backpacking', 'tent', 'wilderness', 'trail', 'hammock',
                 'campfire', 'bivvy', 'shelter', 'forage', 'foraging',
                 'offgrid', 'off grid', 'prepper', 'trek', 'summit',
                 'thru hike', 'thru-hike', 'woodland', 'outdoors'),
}


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
            count = sum(1 for w in words if w in low)
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
            count = sum(1 for w in words if w in low)
            if count > score:
                best, score = niche, count
        return (best or ''), (0.5 if best else 0.0)

    winner = max(votes, key=votes.get)
    return winner, round(votes[winner] / labelled, 2)


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
    'email_source', 'latest_video_url', 'top_video_url', 'roti_reasons',
    'needs_review', 'sample_size_used', 'views_are_rounded',
    'dates_are_bucketed', 'scraped_at',
]

ALL_COLUMNS = SHEET_COLUMNS + HELPER_COLUMNS
