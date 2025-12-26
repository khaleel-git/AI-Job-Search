# -*- coding: utf-8 -*-
"""similarity-search.ipynb
"""
import re
import numpy as np
from typing import List, Dict
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer

# -------------------------
# Text preprocessing
# -------------------------
def clean_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> List[str]:
    return list(set(clean_text(text).split()))


# -------------------------
# Keyword matching
# -------------------------
def keyword_match(job_desc: str, cv_text: str) -> Dict:
    job_tokens = tokenize(job_desc)
    cv_tokens = tokenize(cv_text)

    matched = sorted(set(job_tokens) & set(cv_tokens))
    missing = sorted(set(job_tokens) - set(cv_tokens))

    match_pct = (len(matched) / max(len(job_tokens), 1)) * 100

    return {
        "matched_keywords": matched,
        "missing_keywords": missing,
        "matched_count": len(matched),
        "total_keywords": len(job_tokens),
        "match_percentage": round(match_pct, 2)
    }


# -------------------------
# Semantic similarity
# -------------------------
def semantic_similarity(text1: str, text2: str, model) -> float:
    embeddings = model.encode([text1, text2])
    score = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
    return round(score * 100, 2)


# -------------------------
# Job title matching
# -------------------------
def title_match(job_title: str, ai_roles: List[str], model) -> Dict:
    job_title_clean = clean_text(job_title)

    scores = []
    for role in ai_roles:
        score = semantic_similarity(job_title_clean, role, model)
        scores.append((role, score))

    best_role, best_score = max(scores, key=lambda x: x[1])

    return {
        "title_matched": best_score >= 70,
        "best_role": best_role,
        "title_similarity_percentage": best_score
    }


# -------------------------
# Final scoring
# -------------------------
def final_score(semantic_pct: float, keyword_pct: float, title_pct: float) -> float:
    score = (
        0.45 * semantic_pct +
        0.35 * keyword_pct +
        0.20 * title_pct
    )
    return round(score, 2)


# -------------------------
# Main function
# -------------------------
def main(
    job_title: str,
    job_description: str,
    cv_text: str,
    ai_roles: List[str]
) -> Dict:

    model = SentenceTransformer("all-MiniLM-L6-v2")

    # Clean text
    job_desc_clean = clean_text(job_description)
    cv_clean = clean_text(cv_text)

    # Keyword matching
    keyword_result = keyword_match(job_desc_clean, cv_clean)

    # Semantic similarity
    semantic_pct = semantic_similarity(job_desc_clean, cv_clean, model)

    # Title matching
    title_result = title_match(job_title, ai_roles, model)

    # Final score
    overall_score = final_score(
        semantic_pct,
        keyword_result["match_percentage"],
        title_result["title_similarity_percentage"]
    )

    return {
        "overall_similarity_percentage": overall_score,
        "semantic_similarity_percentage": semantic_pct,
        "keyword_match": keyword_result,
        "title_match": title_result
    }

# -------------------------
# Example usage
# -------------------------
if __name__ == "__main__":
    job_title1 = "Machine Learning Engineer"
    job_description1 = """
    We are looking for an ML Engineer with experience in Python, PyTorch,
    NLP, transformers, vector databases, and production ML systems.
    """

    job_title = "Data Engineer"
    job_description = """
    We are looking for an Data Engineer with experience in Python, pyspark, monogodb,
    aws, and production data systems.
    """

    cv_text = """
    Experienced AI Engineer working with Python, transformers,
    sentence embeddings, vector databases, and deployed ML pipelines.
    """

    my_preferred_roles = [
        "Machine Learning Engineer",
        "AI Engineer",
        "Data Scientist",
        "NLP Engineer",
        "LLM Engineer"
    ]

    result = main(job_title, job_description, cv_text, my_preferred_roles)

    for k, v in result.items():
        print(f"\n{k.upper()}")
        print(v)

