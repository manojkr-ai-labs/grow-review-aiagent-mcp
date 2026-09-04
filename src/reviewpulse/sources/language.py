"""Word counting and English-language detection for review text.

Detection is rule-based rather than model-based so that ingest stays
deterministic and auditable: the same review always yields the same verdict,
and a rejection can be explained by a concrete reason string.

Three signals, applied in order:

1. **Script.** Any meaningful share of non-Latin letters (Devanagari, Telugu,
   Tamil, Bengali, Arabic, CJK, ...) means the review is not English.
2. **Romanized Indic markers.** The dominant non-English case for an Indian
   app is Hinglish written in Latin script ("bahut accha app hai"), which no
   script check can catch. Marker words are chosen to be rare in English.
3. **English evidence.** Share of tokens recognised as common English words.
   Genuine English reviews of 8+ words clear this comfortably; transliterated
   text does not.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

WORD_PATTERN = re.compile(r"[A-Za-z']+(?:-[A-Za-z']+)*")
TOKEN_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)

# Unicode blocks that rule out English outright.
NON_LATIN_SCRIPTS: tuple[tuple[str, int, int], ...] = (
    ("devanagari", 0x0900, 0x097F),
    ("bengali", 0x0980, 0x09FF),
    ("gurmukhi", 0x0A00, 0x0A7F),
    ("gujarati", 0x0A80, 0x0AFF),
    ("odia", 0x0B00, 0x0B7F),
    ("tamil", 0x0B80, 0x0BFF),
    ("telugu", 0x0C00, 0x0C7F),
    ("kannada", 0x0C80, 0x0CFF),
    ("malayalam", 0x0D00, 0x0D7F),
    ("sinhala", 0x0D80, 0x0DFF),
    ("thai", 0x0E00, 0x0E7F),
    ("arabic", 0x0600, 0x06FF),
    ("hebrew", 0x0590, 0x05FF),
    ("greek", 0x0370, 0x03FF),
    ("cyrillic", 0x0400, 0x04FF),
    ("hiragana", 0x3040, 0x309F),
    ("katakana", 0x30A0, 0x30FF),
    ("cjk", 0x4E00, 0x9FFF),
    ("hangul", 0xAC00, 0xD7AF),
)

NON_LATIN_LETTER_RATIO = 0.10
MIN_ENGLISH_RATIO = 0.30
MIN_HINGLISH_MARKERS = 2
# A single marker is weak evidence on its own, but decisive when most of the
# remaining words are also unrecognised ("charges badhate ja rhe h").
MAX_UNKNOWN_RATIO_WITH_MARKER = 0.35

# Common Hindi/Urdu/Marathi/Punjabi words as reviewers transliterate them.
# Every entry must be rare in English review text: "hi", "ha", "mat", "hue",
# "tab", "lie", "log", "logo", "niche", "ache" and "fir" were all tried and
# removed because they collide with ordinary English usage.
ROMANIZED_INDIC_MARKERS = frozenset(
    """
    hai hain haii nahi nahin nahe nhi nhii
    kya kyu kyun kyo kiya kiye karo kar kro karna karne karta karte karti karvao
    kiu kaise kaisa kaisi kese kyunki kyuki
    bahut bohot bohut bhot bhut bahot buhat
    accha acha achha achcha acchi achi achaa
    sahi thik theek thk teek badhiya badiya bakwas bekar bekaar ganda gandi
    ghatiya faltu falto
    bhai bhaiya yaar yar dost
    paisa paise rupaye rupay rupaya paison
    mera meri mere mujhe muje mujhko humko hume hamko hamara hamari hamare
    apna apni apne aap aapka aapke aapki tum tumhara tumhare tumko
    raha rahe rahi rha rhe rhi hota hoti hote hona hua hui hoga hogi honge
    jab phir lekin magar liye wala wali wale walo
    kuch kuchh sab sabhi koi abhi jyada zyada jada
    matlab samajh samjh dekho dekha dekhne
    bola bolo bolte dena dete diya dijiye milega mila milta milti
    chahiye chaiye chahiya karke saal din mahina mahine
    logon baat baate kaam thoda thodi bilkul ekdum
    jaldi jldi turant kripya krupya dhanyawad shukriya
    bahar andar upar saath sath bina bhi bhii
    galat galti dhokha chor luta lutera
    badhate badhta badha ja rha gaya raha-hai
    tumhi ahe aani karun jhala kasa
    vadhiya sohna jinde henge greeb
    """.split()
)

# Function words plus review vocabulary. Coverage only needs to be good enough
# that a real English review of 8+ words clears MIN_ENGLISH_RATIO.
ENGLISH_LEXICON = frozenset(
    """
    a about above after again all almost also always am an and another any anyone anything are
    around as at back bad be because been before being below best better between big both but by
    call came can cannot cant could couldnt did didnt do does doesnt doing done dont down during
    each easy either else enough even ever every everything few find first for from get gets getting
    give given go goes going gone good got great had happen has have having he her here hers him his
    how however i if in into is isnt it its just keep kept know known last late later least less let
    like little long look looking lot made make makes making many may maybe me might mine more most
    much must my need needs never new next no none nor not nothing now of off often on once one only
    or other others our out over own part people per perhaps please put quite rather really right
    said same say says see seen several shall she should shouldnt since so some someone something
    soon still such sure take taken than that the their them then there these they thing things this
    those though through time to too try trying under until up upon us use used useful using very
    want wanted was wasnt way we well went were what when where whether which while who whom why will
    with within without wont worse worst would wouldnt yes yet you your yours
    add added adding against ago allow allowed already alright amazing annoying answer anymore
    apart apply applied appreciate ask asked asking available avoid aware awesome based behind
    believe benefit bit bring brought business change changed changes chance choose clear clearly
    close come coming compare compared complete completely contact continue correct create current
    currently decent decide definitely difficult disappointed disappointing drop due earn earning
    edit effort end enter entire especially excellent expect expected explain extra face facing
    fair family far feel feeling fine follow free friend friendly full future gain genuine
    government guys hand happy hard hate high higher highly hope horrible huge idea immediately
    important impossible improve include including increase increased individual information
    initial instead kind kindly large learn level life limit live lose loss lost love low lower
    mail main mention mind minute minutes mobile moment multiple nice normal note notice old
    online opinion opportunity overall pathetic patience perfect personal place plan point poor
    positive possible previous prompt proper properly provide quality question quickly raise reach
    read ready real reason recommend reduce regular related remove repeat reply report request
    require resolve resolved respond responsible result revert safe satisfied save saving second
    security select sense serious set setting settings simple single sir site situation small
    solution solve solved sometimes sorry space specific spend stop stopped straight submit
    suggest suggestion super thank thanks think third today told total totally touch track tried
    true turn twice type unable understand unfortunately uninstall unnecessary useless value
    various view wonderful worth wrong
    brokerage dividend equity growth holdings intraday mandate nifty nominee redeem sensex
    sector sectors targets watchlist
    account amount app application apps balance bank banking best broker brokerage buy buying
    cash charge charged charges chart charts check company complaint confirm crash crashed crashing
    credit customer data day days debit delay delayed deposit detail details device didnt digital
    documents down download easy error errors experience fail failed failing failure fast fee fees
    feature features feedback fix fixed fund funds good great help helpful history hold holding
    hours id improve improvement instant interest interface invest investing investment investments
    ipo issue issues kyc load loading login logout market money month months mutual name network
    notification notification number offer open opening option options order orders otp page password
    pay payment payments pending phone platform please portfolio price prices problem problems process
    processing product profile profit purchase quick rate rating redeem redemption refund register
    registration request response return returns review screen search sell selling send service
    services share shares show showing sip slow smooth speed staff start started statement statements
    stock stocks support system tax team terrible time trade trading transaction transactions transfer
    trust update updated updating upi user verification verify version wait waiting week weeks
    withdraw withdrawal withdrawn work working works worst year years zero
    """.split()
)


@dataclass(frozen=True)
class LanguageVerdict:
    language: str
    is_english: bool
    reason: str


def word_count(text: str) -> int:
    """Count Latin-script words; emoji, digits and punctuation don't count."""
    return len(WORD_PATTERN.findall(text))


def classify(text: str) -> LanguageVerdict:
    """Decide whether review text is English, and if not, what it looks like."""
    stripped = text.strip()
    if not stripped:
        return LanguageVerdict("unknown", False, "empty")

    script, ratio = _dominant_non_latin_script(stripped)
    if script and ratio >= NON_LATIN_LETTER_RATIO:
        return LanguageVerdict(script, False, f"non_latin_script:{script}")

    words = [w.lower().strip("'") for w in WORD_PATTERN.findall(stripped)]
    words = [w for w in words if w]
    if not words:
        return LanguageVerdict("unknown", False, "no_latin_words")

    markers = {w for w in words if w in ROMANIZED_INDIC_MARKERS}
    if len(markers) >= MIN_HINGLISH_MARKERS:
        return LanguageVerdict("hinglish", False, f"romanized_indic:{len(markers)}")

    english_hits = sum(1 for w in words if w in ENGLISH_LEXICON)
    english_ratio = english_hits / len(words)

    if markers:
        unknown = sum(
            1
            for w in words
            if w not in ENGLISH_LEXICON and w not in ROMANIZED_INDIC_MARKERS
        )
        if unknown / len(words) >= MAX_UNKNOWN_RATIO_WITH_MARKER:
            return LanguageVerdict("hinglish", False, "romanized_indic:1+unknown")

    if english_ratio < MIN_ENGLISH_RATIO:
        return LanguageVerdict(
            "unknown", False, f"low_english_ratio:{english_ratio:.2f}"
        )

    return LanguageVerdict("en", True, "english")


def is_english(text: str) -> bool:
    return classify(text).is_english


def _dominant_non_latin_script(text: str) -> tuple[str | None, float]:
    letters = 0
    counts: dict[str, int] = {}

    for char in text:
        if not char.isalpha():
            continue
        letters += 1
        code = ord(char)
        for name, start, end in NON_LATIN_SCRIPTS:
            if start <= code <= end:
                counts[name] = counts.get(name, 0) + 1
                break
        else:
            if not _is_latin(char):
                counts["other"] = counts.get("other", 0) + 1

    if not letters or not counts:
        return None, 0.0

    script = max(counts, key=lambda key: counts[key])
    return script, counts[script] / letters


def _is_latin(char: str) -> bool:
    try:
        return "LATIN" in unicodedata.name(char)
    except ValueError:
        return False
