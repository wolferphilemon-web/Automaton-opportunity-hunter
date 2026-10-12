import json, re, time, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

SOURCES = [
    ("Remote OK", "https://remoteok.com/api", "remoteok"),
    ("Arbeitnow", "https://www.arbeitnow.com/api/job-board-api", "arbeitnow"),
]
OUT = Path("output")
OUT.mkdir(exist_ok=True)

POS = {"entry level":9,"entry-level":9,"junior":8,"intern":7,"no experience":10,
       "trainee":7,"customer support":6,"customer service":6,"virtual assistant":8,
       "data entry":5,"content writer":6,"copywriter":6,"writing":4,"social media":6,
       "moderator":4,"transcription":5,"translation":5,"research assistant":6,
       "annotation":5,"data labeling":5,"qa tester":5,"canva":4,"graphic design":4,
       "freelance":4,"part-time":3,"part time":3,"worldwide":8,"anywhere":7,
       "africa":8,"kenya":10}
NEG = {"senior":5,"principal":7,"director":6,"10+ years":8,"8+ years":6,"5+ years":4,"phd required":5}
SCAM = ["pay to apply","application fee","registration fee","training fee","starter kit",
        "deposit required","send us cryptocurrency","guaranteed daily profit",
        "guaranteed returns","investment required","money mule","receive and forward money","reshipping"]
RISK = ["unpaid training","commission only","commission-only","must purchase","crypto payment only"]

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def clean(s):
    s = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\\s+", " ", s).strip()

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent":"AUTOMATON-personal-research/0.5","Accept":"application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read(6_000_000).decode("utf-8", "replace"))

def normalize(source, raw):
    rows=[]
    if source=="remoteok":
        records=raw if isinstance(raw,list) else []
        for x in records:
            if not isinstance(x,dict) or not x.get("position") or not x.get("url"): continue
            rows.append({"id":"remoteok:"+str(x.get("id") or x["url"]),
                "title":str(x["position"]),"company":str(x.get("company","Not listed")),
                "url":str(x["url"]),"location":str(x.get("location","")),
                "salary":str(x.get("salary") or ""),"published":str(x.get("date","")),
                "description":clean(str(x.get("description","")))[:1600],
                "tags":x.get("tags") or [],"source":"Remote OK"})
    else:
        records=raw.get("data",[]) if isinstance(raw,dict) else []
        for x in records:
            if not isinstance(x,dict) or not x.get("title") or not x.get("url"): continue
            pub=x.get("created_at","")
            if isinstance(pub,(int,float)):
                try: pub=datetime.fromtimestamp(pub,timezone.utc).isoformat(timespec="seconds")
                except (ValueError,OSError): pub=str(pub)
            rows.append({"id":"arbeitnow:"+str(x.get("slug") or x["url"]),
                "title":str(x["title"]),"company":str(x.get("company_name","Not listed")),
                "url":str(x["url"]),"location":str(x.get("location","")),
                "salary":str(x.get("salary") or ""),"published":str(pub),
                "description":clean(str(x.get("description","")))[:1600],
                "tags":x.get("tags") or [],"source":"Arbeitnow"})
    return rows

def evaluate(x):
    txt=" ".join(str(x.get(k,"")) for k in ("title","company","location","salary","description","tags")).lower()
    score=35; positives=[]; barriers=[]; scam=[]; risks=[]
    for term,pts in POS.items():
        if term in txt: score+=pts; positives.append(term)
    for term,pts in NEG.items():
        if term in txt: score-=pts; barriers.append(term)
    for term in SCAM:
        if term in txt: score-=30; scam.append(term)
    for term in RISK:
        if term in txt: score-=10; risks.append(term)
    if x.get("salary"): score+=5
    if not x.get("location"): score-=3
    if any(t in txt for t in ("worldwide","anywhere","africa","kenya","global remote")): score+=8
    score=max(0,min(100,score))
    x.update(score=score, positive_signals=positives[:8], experience_barriers=barriers[:5],
        scam_flags=scam, other_risks=risks,
        verdict=("HIGH RISK — inspect carefully; never pay" if scam else
                 "HIGHER PRIORITY — verify employer and Kenya eligibility" if score>=65 else
                 "REVIEW — suitability uncertain" if score>=45 else "LOW PRIORITY — likely poor fit"),
        checked_at=now())
    return x

def main():
    all_rows=[]; errors=[]
    for name,url,kind in SOURCES:
        try:
            raw=fetch(url); rows=normalize(kind,raw); all_rows.extend(rows)
            print(f"{name}: fetched {len(rows)} listings")
        except (urllib.error.URLError,TimeoutError,ValueError,OSError) as e:
            errors.append({"source":name,"error":type(e).__name__})
            print(f"{name}: failed ({type(e).__name__})")
        time.sleep(1)
    unique={x["id"]:evaluate(x) for x in all_rows}
    ranked=sorted(unique.values(),key=lambda x:(x["score"],x.get("published","")),reverse=True)
    report={"version":"0.5","generated_at":now(),"sources_checked":[x[0] for x in SOURCES],
            "listing_count":len(ranked),"source_errors":errors,"opportunities":ranked[:100]}
    (OUT/"opportunities.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    with (OUT/"top_opportunities.md").open("w",encoding="utf-8") as f:
        f.write("# AUTOMATON — Scheduled Opportunity Scan\n\n")
        f.write(f"Generated: {report['generated_at']}\n\n")
        f.write(f"Listings processed: {len(ranked)}. Scores are keyword-based fit estimates, not verified probabilities.\n\n")
        if errors: f.write("**Source errors:** "+", ".join(e["source"] for e in errors)+"\n\n")
        for i,x in enumerate(ranked[:20],1):
            f.write(f"## {i}. [{x['score']}/100] {x['title']}\n")
            f.write(f"- **Company:** {x['company']}\n- **Location:** {x.get('location') or 'Not specified'}\n")
            f.write(f"- **Salary:** {x.get('salary') or 'Not listed'}\n- **Source:** {x['source']}\n")
            f.write(f"- **Review listing:** {x['url']}\n- **Assessment:** {x['verdict']}\n")
            if x["scam_flags"]: f.write("- **Warning flags:** "+", ".join(x["scam_flags"])+"\n")
            if x["other_risks"]: f.write("- **Risk notes:** "+", ".join(x["other_risks"])+"\n")
            f.write("\n")
        f.write("\n## Safety\nNever pay to get a job or share OTPs, passwords, PINs, or banking logins. Verify the employer independently and confirm that applicants from Kenya are eligible. AUTOMATON does not apply, message, create accounts, or handle money.\n")
    print(f"Saved {len(ranked)} unique listings to output/.")
    print("Top 5:")
    for x in ranked[:5]:
        print(f"- [{x['score']}] {x['title']} — {x['company']} — {x['url']}")

if __name__=="__main__":
    main()
