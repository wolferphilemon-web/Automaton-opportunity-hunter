
import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from html import unescape

VERSION = "0.6"
OUT = Path("output")
OUT.mkdir(exist_ok=True)

SOURCES = [
    ("Remote OK", "https://remoteok.com/api", "remoteok"),
    ("Arbeitnow", "https://www.arbeitnow.com/api/job-board-api", "arbeitnow"),
]

POSITIVE = {
    "entry level": 12, "entry-level": 12, "junior": 9,
    "intern": 5, "internship": 6, "trainee": 7,
    "no experience": 10, "customer support": 7,
    "customer service": 6, "virtual assistant": 9,
    "data entry": 5, "content writer": 6, "copywriter": 6,
    "social media": 6, "transcription": 5, "translation": 5,
    "research assistant": 6, "data labeling": 7,
    "data annotation": 7, "qa tester": 5, "freelance": 4,
    "part-time": 3, "part time": 3, "worldwide": 10,
    "anywhere": 8, "africa": 8, "kenya": 12,
    "remote": 5, "work from home": 6,
}

NEGATIVE = {
    "senior": 7, "principal": 9, "director": 8,
    "lead engineer": 5, "10+ years": 10,
    "8+ years": 8, "5+ years": 5,
    "phd required": 8, "must be located in the us": 15,
    "us citizens only": 20, "must reside in the united states": 20,
}

SCAM_FLAGS = [
    "pay to apply", "application fee", "registration fee",
    "training fee", "starter kit", "deposit required",
    "guaranteed daily profit", "guaranteed returns",
    "investment required", "money mule",
    "receive and forward money", "reshipping fee",
    "pay for equipment before starting",
]

RISK_FLAGS = [
    "unpaid training", "commission only", "commission-only",
    "must purchase", "crypto payment only",
]

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def clean(value):
    value = unescape(str(value or ""))
    value = re.sub(
        r"(?is)<(script|style).*?>.*?</\1>", " ", value
    )
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def fetch(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AUTOMATON-personal-research/0.6",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(6_000_000)
    return json.loads(data.decode("utf-8", "replace"))

def normalize(source, raw):
    rows = []

    if source == "remoteok":
        records = raw if isinstance(raw, list) else []
        for item in records:
            if not isinstance(item, dict):
                continue
            if not item.get("position") or not item.get("url"):
                continue

            rows.append({
                "id": "remoteok:" + str(
                    item.get("id") or item["url"]
                ),
                "title": str(item["position"]),
                "company": str(item.get("company") or "Not listed"),
                "url": str(item["url"]),
                "location": str(item.get("location") or ""),
                "salary": str(item.get("salary") or ""),
                "published": str(item.get("date") or ""),
                "description": clean(
                    item.get("description", "")
                )[:2000],
                "tags": item.get("tags") or [],
                "source": "Remote OK",
            })

    else:
        records = raw.get("data", []) if isinstance(raw, dict) else []
        for item in records:
            if not isinstance(item, dict):
                continue
            if not item.get("title") or not item.get("url"):
                continue

            published = item.get("created_at", "")
            if isinstance(published, (int, float)):
                try:
                    published = datetime.fromtimestamp(
                        published, timezone.utc
                    ).isoformat(timespec="seconds")
                except (ValueError, OSError, OverflowError):
                    published = str(published)

            rows.append({
                "id": "arbeitnow:" + str(
                    item.get("slug") or item["url"]
                ),
                "title": str(item["title"]),
                "company": str(
                    item.get("company_name") or "Not listed"
                ),
                "url": str(item["url"]),
                "location": str(item.get("location") or ""),
                "salary": str(item.get("salary") or ""),
                "published": str(published),
                "description": clean(
                    item.get("description", "")
                )[:2000],
                "tags": item.get("tags") or [],
                "source": "Arbeitnow",
            })

    return rows

def evaluate(item):
    text = " ".join(
        str(item.get(key, ""))
        for key in (
            "title", "company", "location",
            "salary", "description", "tags"
        )
    ).lower()

    score = 35
    positive_hits = []
    experience_barriers = []
    scam_hits = []
    risk_hits = []

    for term, points in POSITIVE.items():
        if term in text:
            score += points
            positive_hits.append(term)

    for term, points in NEGATIVE.items():
        if term in text:
            score -= points
            experience_barriers.append(term)

    for term in SCAM_FLAGS:
        if term in text:
            score -= 35
            scam_hits.append(term)

    for term in RISK_FLAGS:
        if term in text:
            score -= 10
            risk_hits.append(term)

    if item.get("salary"):
        score += 5
    else:
        score -= 2

    location_text = str(item.get("location", "")).lower()
    if any(term in text for term in (
        "worldwide", "anywhere", "africa", "kenya",
        "global remote", "work from anywhere"
    )):
        score += 8

    location_restrictions = [
        "us citizens only",
        "must reside in the united states",
        "must be located in the us",
        "uk residents only",
        "eu citizens only",
    ]
    restrictions = [
        term for term in location_restrictions
        if term in text
    ]
    if restrictions:
        score -= 20

    score = max(0, min(100, score))

    if scam_hits:
        verdict = "HIGH RISK — do not pay; verify independently"
    elif restrictions:
        verdict = "LOCATION RESTRICTED — likely unsuitable"
    elif score >= 65:
        verdict = "HIGHER PRIORITY — verify pay and Kenya eligibility"
    elif score >= 45:
        verdict = "REVIEW — suitability or payment unclear"
    else:
        verdict = "LOW PRIORITY — likely a weaker match"

    item.update({
        "score": score,
        "positive_signals": positive_hits[:10],
        "experience_barriers": experience_barriers,
        "scam_flags": scam_hits,
        "other_risks": risk_hits,
        "location_restrictions": restrictions,
        "verdict": verdict,
        "checked_at": now(),
    })

    return item

def main():
    all_rows = []
    errors = []

    for name, url, kind in SOURCES:
        try:
            rows = normalize(kind, fetch(url))
            all_rows.extend(rows)
            print(f"{name}: fetched {len(rows)} listings")
        except (
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as error:
            errors.append({
                "source": name,
                "error": type(error).__name__,
            })
            print(f"{name}: failed ({type(error).__name__})")
        time.sleep(1)

    unique = {}
    for item in all_rows:
        key = item["url"].strip().rstrip("/")
        if key and key not in unique:
            unique[key] = evaluate(item)

    ranked = sorted(
        unique.values(),
        key=lambda item: (
            item["score"],
            bool(item.get("salary")),
            item.get("published", ""),
        ),
        reverse=True,
    )

    report = {
        "version": VERSION,
        "generated_at": now(),
        "sources_checked": [source[0] for source in SOURCES],
        "listing_count": len(ranked),
        "source_errors": errors,
        "opportunities": ranked[:100],
    }

    (OUT / "opportunities.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with (OUT / "top_opportunities.md").open(
        "w", encoding="utf-8"
    ) as file:
        file.write("# AUTOMATON v0.6 — Opportunity Scan\n\n")
        file.write(f"Generated: {report['generated_at']}\n\n")
        file.write(
            f"Listings processed: {len(ranked)}. "
            "Scores are keyword-based estimates, not verified "
            "probabilities or proof of legitimacy.\n\n"
        )

        if errors:
            file.write(
                "**Sources that failed:** "
                + ", ".join(error["source"] for error in errors)
                + "\n\n"
            )

        if not ranked:
            file.write(
                "No listings were retrieved. Check source "
                "availability and workflow logs before concluding "
                "that no opportunities exist.\n\n"
            )

        for number, item in enumerate(ranked[:25], 1):
            file.write(
                f"## {number}. [{item['score']}/100] "
                f"{item['title']}\n"
            )
            file.write(f"- **Company:** {item['company']}\n")
            file.write(
                f"- **Location:** "
                f"{item.get('location') or 'Not specified'}\n"
            )
            file.write(
                f"- **Salary:** "
                f"{item.get('salary') or 'Not listed'}\n"
            )
            file.write(f"- **Source:** {item['source']}\n")
            file.write(f"- **Assessment:** {item['verdict']}\n")
            file.write(f"- **Listing:** {item['url']}\n")

            if item["positive_signals"]:
                file.write(
                    "- **Matching signals:** "
                    + ", ".join(item["positive_signals"])
                    + "\n"
                )
            if item["scam_flags"]:
                file.write(
                    "- **Warning flags:** "
                    + ", ".join(item["scam_flags"])
                    + "\n"
                )
            if item["other_risks"]:
                file.write(
                    "- **Other risks:** "
                    + ", ".join(item["other_risks"])
                    + "\n"
                )
            if item["location_restrictions"]:
                file.write(
                    "- **Location restrictions:** "
                    + ", ".join(item["location_restrictions"])
                    + "\n"
                )
            file.write("\n")

        file.write(
            "## Safety\n\n"
            "Never pay to obtain a job or share passwords, PINs, "
            "OTPs, or banking logins. Verify the employer and "
            "confirm applicants from Kenya are eligible. A missing "
            "scam flag does not prove a listing is safe. AUTOMATON "
            "does not apply, message employers, create accounts, "
            "or handle payments.\n"
        )

    print(f"Saved {len(ranked)} unique listings to output/.")
    print("Top 5:")
    for item in ranked[:5]:
        print(
            f"- [{item['score']}] {item['title']} — "
            f"{item['company']} — {item['url']}"
        )

if __name__ == "__main__":
    main()
