import requests


def search_factchecks(query: str, *, api_key: str = "", timeout: int = 20, limit: int = 8) -> list[dict]:
    """Google Fact Check Tools: published reviews of claims similar to `query`."""
    if not api_key:
        return []
    response = requests.get(
        "https://factchecktools.googleapis.com/v1alpha1/claims:search",
        params={"query": query, "languageCode": "en", "key": api_key, "pageSize": limit},
        timeout=timeout,
    )
    response.raise_for_status()
    results = []
    for claim in response.json().get("claims", []):
        for review in claim.get("claimReview", []):
            results.append({
                "claim": claim.get("text", ""), "claimant": claim.get("claimant", ""),
                "publisher": review.get("publisher", {}).get("name", ""),
                "rating": review.get("textualRating", ""), "url": review.get("url", ""),
                "title": review.get("title", ""), "review_date": review.get("reviewDate", ""),
            })
    return results[:limit]
