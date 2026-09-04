"""Top-term extraction for cluster diagnostics and label anchoring.

Embeddings on this corpus separate by sentiment more than by topic
(implementation-plan.md §4.2 F2), so clusters get keyword anchors that the label
prompt must use to name a product surface. The stop list therefore drops
sentiment words ("worst", "best") and the app name as well as ordinary English
function words — they describe how a reviewer felt, not what they were using.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_WORD_RE = re.compile(r"[a-z][a-z'&/-]+")

STOPWORDS = frozenset(
    """
a an the and or but if then than so to of in on for with without at by from as is are was were be
been being it its this that these those i we you they he she my our your their me us them not no nor
do does did doing done have has had having will would can could should shall may might must am very
much more most too also just only even still yet about into over under again once here there when
where why how all any both each few other some such own same now what which who whom whose
app apps application groww grow please give given want need needs make made use using used get got
go going one two three time times day days week weeks month months year years thing things lot
it's don't i'm can't isn't doesn't didn't won't they're that's there's you're
good nice best great fine ok okay super awesome excellent amazing beautiful love loved like liked
bad worst poor terrible horrible pathetic useless waste
thanks thank sir team pls plz hai hi bhi kya
"""
    .split()
)


def tokenize(text: str) -> list[str]:
    return [
        word
        for word in _WORD_RE.findall(text.lower())
        if len(word) > 2 and word not in STOPWORDS
    ]


def top_terms(texts: Iterable[str], limit: int = 10) -> list[str]:
    """Most widespread terms in a cluster, counted once per review.

    Document frequency rather than raw frequency, so one ranting review cannot
    define a theme by repeating a word.
    """
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(set(tokenize(text)))
    return [term for term, _ in counter.most_common(limit)]


def distinctive_terms(
    cluster_texts: list[str],
    corpus_texts: list[str],
    limit: int = 10,
) -> list[str]:
    """Terms over-represented in the cluster relative to the whole corpus.

    Plain frequency surfaces the same generic vocabulary in every cluster; the
    lift ratio is what makes a label like "charts and scalper button" possible.
    """
    if not cluster_texts:
        return []

    cluster_df: Counter[str] = Counter()
    for text in cluster_texts:
        cluster_df.update(set(tokenize(text)))
    corpus_df: Counter[str] = Counter()
    for text in corpus_texts:
        corpus_df.update(set(tokenize(text)))

    n_cluster = len(cluster_texts)
    n_corpus = max(len(corpus_texts), 1)
    scored: list[tuple[float, int, str]] = []
    for term, count in cluster_df.items():
        # Require the term in at least two reviews, or 10% of a tiny cluster.
        if count < max(2, int(0.1 * n_cluster)):
            continue
        cluster_rate = count / n_cluster
        corpus_rate = corpus_df.get(term, 0) / n_corpus
        lift = cluster_rate / corpus_rate if corpus_rate else cluster_rate
        scored.append((lift, count, term))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [term for _, _, term in scored[:limit]]
