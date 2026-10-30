"""Collect all scheduled international flights to/from Taiwan for the next N days
from TDX, and attach the terminal for each flight number.

Usage:
  TDX_CLIENT_ID=xxx TDX_CLIENT_SECRET=yyy python3 -I tdx_flights.py OUT_DIR [--days 60]
  python3 -I tdx_flights.py OUT_DIR --from-json schedule.json      # offline, reuse a saved response

Terminal resolution (terminal_source column):
  tdx        TDX record carries a terminal field
  tpe_exact  same flight number + direction seen in Taoyuan's a_flight_v4.txt
  tpe_route  same airline + outstation seen in a_flight_v4.txt (one terminal only)
  tpe_airline same airline seen in a_flight_v4.txt in one terminal only
  fixed      TSA/KHH/RMQ etc. have a single international terminal
  unknown    could not be determined
"""
import argparse, csv, datetime as dt, json, os, sys, urllib.parse, urllib.request
from collections import defaultdict

TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
SCHED_URL = "https://tdx.transportdata.tw/api/basic/v2/Air/GeneralSchedule/International"
TPE_FILE_URL = "https://www.taoyuan-airport.com/uploads/flightx/a_flight_v4.txt"
TW_AIRPORTS = {"TPE", "TSA", "KHH", "RMQ", "TNN", "CYI", "HUN", "TTT", "KNH", "MZG", "LZN", "MFK", "PIF", "TXG"}
FIXED_TERMINAL = {"TSA": "T1(國際線)", "KHH": "國際線航廈", "RMQ": "國際線航廈", "TNN": "國際線", "HUN": "國際線", "TTT": "國際線", "KNH": "國際線", "MZG": "國際線"}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WD_ZH = "一二三四五六日"


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def get_token():
    cid, secret = os.environ.get("TDX_CLIENT_ID"), os.environ.get("TDX_CLIENT_SECRET")
    if not cid or not secret:
        sys.exit("TDX_CLIENT_ID / TDX_CLIENT_SECRET not set")
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": secret}).encode()
    return json.loads(http(TOKEN_URL, body, {"content-type": "application/x-www-form-urlencoded"}))["access_token"]


def fetch_schedule(token):
    out, skip, page = [], 0, 5000
    while True:
        q = urllib.parse.urlencode({"$top": page, "$skip": skip, "$format": "JSON"})
        rows = json.loads(http(f"{SCHED_URL}?{q}", headers={"authorization": f"Bearer {token}", "accept": "application/json"}))
        out.extend(rows)
        print(f"  fetched {len(rows)} (total {len(out)})", file=sys.stderr)
        if len(rows) < page:
            return out
        skip += page


def norm_no(airline, no):
    s = str(no or "").strip().upper().replace(" ", "")
    if s.startswith(airline):
        s = s[len(airline):]
    return airline + (s.lstrip("0") or "0")


def load_tpe(path):
    """Build lookups from Taoyuan's official 3-day flight file (Big5, no header)."""
    exact, route, airline = {}, defaultdict(set), defaultdict(set)
    with open(path, encoding="cp950", errors="replace") as f:
        for r in csv.reader(f):
            if len(r) < 15:
                continue
            r = [c.strip() for c in r]
            term, ad, al, no, other = "T" + r[0], r[1], r[2], r[4], r[10]
            exact[(norm_no(al, no), ad)] = term
            route[(al, other)].add(term)
            airline[al].add(term)
    return exact, route, airline


def pick(rec, *names):
    for n in names:
        v = rec.get(n)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def resolve_terminal(rec, tw_airport, direction, fno, outstation, tpe):
    if direction == "出境":
        t = pick(rec, "DepartureTerminal", "Terminal")
    else:
        t = pick(rec, "ArrivalTerminal", "Terminal")
    if t:
        return (f"T{t}" if t.isdigit() else t), "tdx"
    if tw_airport in FIXED_TERMINAL:
        return FIXED_TERMINAL[tw_airport], "fixed"
    if tw_airport != "TPE":
        return "", "unknown"
    exact, route, airline = tpe
    ad = "D" if direction == "出境" else "A"
    if (fno, ad) in exact:
        return exact[(fno, ad)], "tpe_exact"
    al = rec.get("AirlineID", "")
    if len(route.get((al, outstation), ())) == 1:
        return next(iter(route[(al, outstation)])), "tpe_route"
    if len(airline.get(al, ())) == 1:
        return next(iter(airline[al])), "tpe_airline"
    return "", "unknown"


def split_time(t):
    """'02:00+1' -> ('02:00', 1). TDX weekdays/dates are departure-day based."""
    t = (t or "").strip()
    return t[:5], int(t[5:]) if len(t) > 5 else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--from-json")
    ap.add_argument("--tpe-file", help="local a_flight_v4.txt (downloaded if omitted)")
    ap.add_argument("--data-dir", default="data", help="where the CSVs are written")
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.data_dir, exist_ok=True)

    if a.from_json:
        sched = json.load(open(a.from_json, encoding="utf-8"))
    else:
        print("fetching TDX schedule...", file=sys.stderr)
        sched = fetch_schedule(get_token())
        json.dump(sched, open(os.path.join(a.out_dir, "tdx_schedule_raw.json"), "w", encoding="utf-8"), ensure_ascii=False)

    tpe_path = a.tpe_file or os.path.join(a.out_dir, "a_flight_v4.txt")
    if not a.tpe_file:
        open(tpe_path, "wb").write(http(TPE_FILE_URL))
    tpe = load_tpe(tpe_path)

    today = dt.date.today()
    end = today + dt.timedelta(days=a.days)
    flights, daily, seen = [], [], set()
    for s in sched:
        key = json.dumps({k: v for k, v in s.items() if k not in ("UpdateTime", "VersionID")}, sort_keys=True)
        if key in seen:
            continue  # TDX contains exact duplicate records
        seen.add(key)
        dep, arr = s.get("DepartureAirportID", "").upper(), s.get("ArrivalAirportID", "").upper()
        if (dep in TW_AIRPORTS) == (arr in TW_AIRPORTS):
            continue  # not a Taiwan international leg
        start_d = dt.date.fromisoformat((s.get("ScheduleStartDate") or today.isoformat())[:10])
        end_d = dt.date.fromisoformat((s.get("ScheduleEndDate") or end.isoformat())[:10])
        # departure dates may precede the Taiwan-side date by up to 2 days (+2 arrivals)
        lo, hi = max(start_d, today - dt.timedelta(2)), min(end_d, end)
        if lo > hi:
            continue
        days = [i for i, w in enumerate(WEEKDAYS) if s.get(w)]
        dates = [lo + dt.timedelta(n) for n in range((hi - lo).days + 1)]
        dates = [d for d in dates if d.weekday() in days]
        if not dates:
            continue
        al = s.get("AirlineID", "")
        direction = "出境" if dep in TW_AIRPORTS else "入境"
        tw, other = (dep, arr) if direction == "出境" else (arr, dep)
        fno = norm_no(al, s.get("FlightNumber"))
        term, src = resolve_terminal(s, tw, direction, fno, other, tpe)
        codeshares = [norm_no(c.get("AirlineID", ""), c.get("FlightNumber")) for c in (s.get("CodeShare") or []) if isinstance(c, dict)]
        dep_t, dep_off = split_time(s.get("DepartureTime"))
        arr_t, arr_off = split_time(s.get("ArrivalTime"))
        row = {
            "tw_airport": tw, "terminal": term, "terminal_source": src, "direction": direction,
            "flight_no": fno, "airline_iata": al, "dep": dep, "arr": arr,
            "dep_time": dep_t, "arr_time": arr_t, "arr_day_offset": arr_off - dep_off,
            "weekdays_by_dep": "".join(WD_ZH[i] for i in days),
            "dep_valid_from": lo.isoformat(), "dep_valid_to": hi.isoformat(), "flight_days": len(dates),
            "codeshare_flights": ";".join(codeshares),
        }
        flights.append(row)
        for d in dates:
            dep_d, arr_d = d + dt.timedelta(dep_off), d + dt.timedelta(arr_off)
            tw_d = dep_d if direction == "出境" else arr_d
            if not today <= tw_d <= end:
                continue
            for no, op in [(fno, "")] + [(c, fno) for c in codeshares]:
                daily.append({
                    "tw_date": tw_d.isoformat(),
                    "tw_time": dep_t if direction == "出境" else arr_t,
                    "tw_airport": tw, "terminal": term, "direction": direction,
                    "flight_no": no, "operating_flight": op, "dep": dep, "arr": arr,
                    "dep_date": dep_d.isoformat(), "dep_time": dep_t, "arr_date": arr_d.isoformat(), "arr_time": arr_t,
                })

    flights.sort(key=lambda r: (r["tw_airport"], r["airline_iata"], r["flight_no"], r["dep_valid_from"]))
    daily.sort(key=lambda r: (r["tw_date"], r["tw_time"], r["tw_airport"], r["flight_no"]))
    # flight number -> terminal lookup; flags numbers whose terminal changes within the window
    look = {}
    for r in daily:
        e = look.setdefault((r["flight_no"], r["direction"]), {
            "flight_no": r["flight_no"], "direction": r["direction"], "tw_airport": r["tw_airport"],
            "operating_flight": r["operating_flight"], "route": f'{r["dep"]}-{r["arr"]}',
            "terminals": set(), "first_date": r["tw_date"], "last_date": r["tw_date"], "flight_days": 0})
        e["terminals"].add(r["terminal"])
        e["last_date"] = max(e["last_date"], r["tw_date"])
        e["flight_days"] += 1
    lookup = []
    for e in sorted(look.values(), key=lambda e: (e["flight_no"], e["direction"])):
        lookup.append({**e, "terminals": "/".join(sorted(e["terminals"])), "terminal_changes": "Y" if len(e["terminals"]) > 1 else ""})

    for name, rows in (("tw_intl_flights_by_schedule.csv", flights), ("tw_intl_flights_daily.csv", daily), ("tw_intl_flight_terminal_lookup.csv", lookup)):
        with open(os.path.join(a.data_dir, name), "w", encoding="utf-8-sig", newline="") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)

    src_count = defaultdict(int)
    for r in flights:
        src_count[r["terminal_source"]] += 1
    print(f"schedule rows: {len(sched)}; TW intl schedules in window: {len(flights)}; daily flights: {len(daily)}")
    print("terminal_source:", dict(src_count))
    unknown = sorted({(r["tw_airport"], r["flight_no"]) for r in flights if r["terminal_source"] == "unknown"})
    print("unknown terminal:", unknown[:40], "..." if len(unknown) > 40 else "")
    print("sample record keys:", sorted(sched[0].keys()) if sched else [])


if __name__ == "__main__":
    main()
