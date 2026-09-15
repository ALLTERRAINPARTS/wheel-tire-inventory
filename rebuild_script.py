import csv
import json
import re
import sys
from datetime import date

CSV_PATH = "inventory.csv"
OLD_HTML_PATH = "old.html"
NEW_HTML_PATH = "new.html"

ALLOWED_CATS = {"WHL", "TIR", "ATR", "DTR", "BAT", "PLG"}

LOCATION_MAP = {
    "AllTerrain": "Grand Junction",
    "Rifle": "Rifle",
}

def strip_nuls(s):
    return s.replace("\x00", "")

def parse_price(raw):
    raw = (raw or "").strip()
    if raw == "":
        return None
    try:
        return float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return None

def parse_qty(raw):
    raw = (raw or "").strip()
    try:
        return int(float(raw))
    except ValueError:
        return 0

def main():
    with open(CSV_PATH, "rb") as f:
        raw_bytes = f.read()
    raw_bytes = raw_bytes.replace(b"\x00", b"")
    text = raw_bytes.decode("utf-8", errors="replace")

    reader = csv.reader(text.splitlines())
    rows = list(reader)
    header = [h.strip() for h in rows[0]]
    ncols = len(header)

    records = []
    skipped_footer = 0
    skipped_cat = 0
    skipped_price = 0

    for row in rows[1:]:
        if not row or all((c.strip() == "" for c in row)):
            continue
        row = [strip_nuls(c).strip() for c in row]
        # pad/truncate to header length defensively
        if len(row) < ncols:
            row = row + [""] * (ncols - len(row))
        elif len(row) > ncols:
            row = row[:ncols]
        d = dict(zip(header, row))

        cat = d.get("Category", "").strip()
        if cat not in ALLOWED_CATS:
            skipped_footer += 1
            continue

        price = parse_price(d.get("Retail Price", ""))

        if cat == "WHL":
            if price is not None and price < 60:
                skipped_price += 1
                continue

        store = d.get("Store-Store Name", "").strip()
        if store in LOCATION_MAP:
            location = LOCATION_MAP[store]
        elif store:
            location = store
        else:
            location = "Unknown"

        rec = {
            "qty": parse_qty(d.get("Available", "")),
            "cat": cat,
            "location": location,
            "description": d.get("Description", "").strip(),
            "partNum": d.get("Part Number", "").strip(),
            "secondary": d.get("Secondary", "").strip(),
            "mfrPart": d.get("Manufacturer Part", "").strip(),
            "manufacturer": d.get("Manufacturer", "").strip(),
            "supplier": d.get("Supplier Name", "").strip(),
            "upc": d.get("UPC Code", "").strip(),
            "price": price if price is not None else 0,
            "lastReceived": d.get("Last Received", "").strip(),
        }
        records.append(rec)

    print(f"Parsed {len(rows)-1} data rows -> kept {len(records)} records "
          f"(excluded {skipped_footer} non-matching-category/footer rows, "
          f"{skipped_price} WHL rows under $60)", file=sys.stderr)

    # ---- Load old HTML, extract DATA for photo enrichment ----
    old_content = open(OLD_HTML_PATH, encoding="utf-8").read()

    data_start_marker = "const DATA = "
    i = old_content.find(data_start_marker)
    if i == -1:
        raise RuntimeError("could not find 'const DATA = ' in old HTML")
    today_idx = old_content.find("const TODAY", i)
    if today_idx == -1:
        raise RuntimeError("could not find 'const TODAY' after DATA")
    stmt_end = old_content.rfind(";", i, today_idx)
    if stmt_end == -1:
        raise RuntimeError("could not find terminating ';' for DATA statement")
    old_json_str = old_content[i + len(data_start_marker):stmt_end]
    old_data = json.loads(old_json_str)

    image_map = {}
    old_image_count = 0
    for rec in old_data:
        pn = rec.get("partNum")
        if pn and "image" in rec:
            old_image_count += 1
            image_map[pn] = {
                "image": rec["image"],
                "imageConfidence": rec.get("imageConfidence"),
            }

    new_image_count = 0
    for rec in records:
        enrich = image_map.get(rec["partNum"])
        if enrich:
            rec["image"] = enrich["image"]
            if enrich.get("imageConfidence") is not None:
                rec["imageConfidence"] = enrich["imageConfidence"]
            new_image_count += 1

    print(f"Photo enrichment: old had {old_image_count} images, "
          f"new has {new_image_count} images", file=sys.stderr)

    if old_image_count > 0 and new_image_count == 0:
        raise RuntimeError("Photo enrichment merge produced 0 images from "
                            f"{old_image_count} in old data -- aborting, merge likely broken")

    # ---- Build new DATA json ----
    new_json_str = json.dumps(records, separators=(",", ":"))
    json.loads(new_json_str)  # round-trip validation

    # ---- Splice into HTML ----
    content = old_content

    # 1. DATA statement
    data_stmt_start = content.find(data_start_marker)
    today_idx2 = content.find("const TODAY", data_stmt_start)
    data_stmt_end = content.rfind(";", data_stmt_start, today_idx2)
    new_data_statement = data_start_marker + new_json_str + ";"
    content = content[:data_stmt_start] + new_data_statement + content[data_stmt_end + 1:]

    # 2. const TODAY = new Date('YYYY-MM-DD');
    today = date.today()
    iso_today = today.isoformat()
    month_day_year = today.strftime("%B %d, %Y")

    m = re.search(r"const TODAY = new Date\('(\d{4}-\d{2}-\d{2})'\);", content)
    if not m:
        raise RuntimeError("could not find const TODAY statement to replace")
    old_iso = m.group(1)
    content = content[:m.start()] + f"const TODAY = new Date('{iso_today}');" + content[m.end():]

    # 3. title date
    m2 = re.search(r"(<title>[^<]*?)(\w+ \d{1,2}, \d{4})(</title>)", content)
    if not m2:
        raise RuntimeError("could not find title date")
    old_title_date = m2.group(2)
    content = content[:m2.start(2)] + month_day_year + content[m2.end(2):]

    # 4. header-date div
    m3 = re.search(r'(<div class="header-date">)(\w+ \d{1,2}, \d{4})(</div>)', content)
    if not m3:
        raise RuntimeError("could not find header-date div")
    old_header_date = m3.group(2)
    content = content[:m3.start(2)] + month_day_year + content[m3.end(2):]

    with open(NEW_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Old dates: iso={old_iso} title/header={old_title_date}/{old_header_date}", file=sys.stderr)
    print(f"New dates: iso={iso_today} title/header={month_day_year}", file=sys.stderr)
    print(f"DATA unchanged: {old_json_str == new_json_str}", file=sys.stderr)
    print(f"Old HTML size: {len(old_content)}  New HTML size: {len(content)}", file=sys.stderr)

if __name__ == "__main__":
    main()
