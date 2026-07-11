import os
import re
import sqlite3
import json
import urllib.parse
import requests

def clean_html(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_lessons(html, category, base_url="https://primelessons.org/en/"):
    # Split the html by <h3> headings which represent the Units
    parts = re.split(r'(<h3[^>]*>.*?</h3>)', html, flags=re.IGNORECASE)
    
    lessons = []
    current_unit = "General"
    
    for part in parts:
        if part.lower().startswith("<h3"):
            unit_title = clean_html(part)
            current_unit = unit_title
        else:
            # Find all posts between begin/end comments
            posts = re.findall(r'<!--\s*begin\s+post\s*-->(.*?)<!--\s*end\s+post\s*-->', part, re.DOTALL | re.IGNORECASE)
            for post in posts:
                # Extract lesson title
                title_match = re.search(r'class="panel-title[^"]*"[^>]*>(.*?)</a>', post, re.DOTALL)
                title = clean_html(title_match.group(1)) if title_match else "Unknown Title"
                
                # Extract links
                links_matches = re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', post, re.DOTALL | re.IGNORECASE)
                pptx_urls = []
                pdf_urls = []
                other_links = []
                
                for href, text in links_matches:
                    href = href.strip()
                    if href.startswith('#') or href.startswith('javascript:') or not href:
                        continue
                    full_url = urllib.parse.urljoin(base_url, href)
                    text_clean = clean_html(text)
                    
                    parsed_path = urllib.parse.urlparse(full_url).path
                    ext = os.path.splitext(parsed_path)[1].lower()
                    
                    link_info = {"text": text_clean, "url": full_url}
                    if ext == ".pptx":
                        pptx_urls.append(full_url)
                    elif ext == ".pdf":
                        pdf_urls.append(full_url)
                    else:
                        other_links.append(link_info)
                
                # We expect at most one primary PPTX and PDF, but if there are multiple, we'll store them
                lessons.append({
                    "category": category,
                    "unit": current_unit,
                    "title": title,
                    "pptx_urls": pptx_urls,
                    "pdf_urls": pdf_urls,
                    "other_links": other_links
                })
                
    return lessons

def download_file(url, target_dir):
    parsed_url = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed_url.path)
    if not filename:
        return None
        
    local_path = os.path.join(target_dir, filename)
    
    # Check if already exists to prevent duplicate downloading
    if os.path.exists(local_path):
        print(f"  [SKIPPED] {filename} already exists.")
        return filename, os.path.relpath(local_path, start=os.path.dirname(target_dir))
        
    print(f"  [DOWNLOADING] {filename} ... ", end="", flush=True)
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print("OK")
        return filename, os.path.relpath(local_path, start=os.path.dirname(target_dir))
    except Exception as e:
        print(f"FAILED ({e})")
        return None

def main():
    base_dir = r"d:\aioonbot"
    files_dir = os.path.join(base_dir, "files")
    
    os.makedirs(files_dir, exist_ok=True)
    
    urls = {
        "Word Blocks": "https://primelessons.org/en/Lessons.html",
        "Python": "https://primelessons.org/en/PyLessons.html"
    }
    
    all_lessons = []
    
    # 1. Scraping pages
    for category, url in urls.items():
        print(f"Fetching and parsing {category} lessons from {url}...")
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            lessons = parse_lessons(r.text, category)
            print(f"Found {len(lessons)} lessons in {category}.")
            all_lessons.extend(lessons)
        except Exception as e:
            print(f"Error processing {category}: {e}")
            
    print(f"\nTotal lessons parsed: {len(all_lessons)}")
    
    # Collect all unique file URLs to download
    unique_urls = set()
    for lesson in all_lessons:
        for u in lesson["pptx_urls"] + lesson["pdf_urls"]:
            unique_urls.add(u)
            
    print(f"Total unique slide files to download: {len(unique_urls)}")
    
    # 2. Download files
    downloaded_map = {}
    print("\nStarting downloads...")
    for idx, url in enumerate(sorted(unique_urls), 1):
        print(f"[{idx}/{len(unique_urls)}] ", end="")
        result = download_file(url, files_dir)
        if result:
            filename, rel_path = result
            downloaded_map[url] = {
                "filename": filename,
                "local_path": rel_path
            }
            
    # 3. Create SQLite Database
    db_path = os.path.join(base_dir, "lessons.db")
    print(f"\nCreating SQLite database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("DROP TABLE IF EXISTS lessons")
    cursor.execute("""
        CREATE TABLE lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            unit TEXT,
            title TEXT,
            pptx_filename TEXT,
            pptx_local_path TEXT,
            pptx_remote_url TEXT,
            pdf_filename TEXT,
            pdf_local_path TEXT,
            pdf_remote_url TEXT,
            other_links TEXT
        )
    """)
    
    # 4. Insert data and prepare JSON data
    json_lessons = []
    
    for lesson in all_lessons:
        pptx_url = lesson["pptx_urls"][0] if lesson["pptx_urls"] else None
        pdf_url = lesson["pdf_urls"][0] if lesson["pdf_urls"] else None
        
        pptx_info = downloaded_map.get(pptx_url, {})
        pdf_info = downloaded_map.get(pdf_url, {})
        
        pptx_filename = pptx_info.get("filename")
        pptx_local_path = pptx_info.get("local_path")
        
        pdf_filename = pdf_info.get("filename")
        pdf_local_path = pdf_info.get("local_path")
        
        other_links_json = json.dumps(lesson["other_links"])
        
        cursor.execute("""
            INSERT INTO lessons (
                category, unit, title, 
                pptx_filename, pptx_local_path, pptx_remote_url,
                pdf_filename, pdf_local_path, pdf_remote_url,
                other_links
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            lesson["category"],
            lesson["unit"],
            lesson["title"],
            pptx_filename,
            pptx_local_path,
            pptx_url,
            pdf_filename,
            pdf_local_path,
            pdf_url,
            other_links_json
        ))
        
        json_lessons.append({
            "category": lesson["category"],
            "unit": lesson["unit"],
            "title": lesson["title"],
            "pptx": {
                "filename": pptx_filename,
                "local_path": pptx_local_path,
                "remote_url": pptx_url
            } if pptx_url else None,
            "pdf": {
                "filename": pdf_filename,
                "local_path": pdf_local_path,
                "remote_url": pdf_url
            } if pdf_url else None,
            "other_links": lesson["other_links"]
        })
        
    conn.commit()
    conn.close()
    
    # Write JSON Database
    json_path = os.path.join(base_dir, "lessons.json")
    print(f"Writing JSON database to {json_path}...")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_lessons, f, indent=2, ensure_ascii=False)
        
    # Write README.md
    readme_path = os.path.join(base_dir, "README.md")
    print(f"Writing README.md to {readme_path}...")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("""# Prime Lessons Reference Database

This folder contains a reference database of Scratch Word Blocks and Python programming lessons parsed from [primelessons.org](https://primelessons.org).

## Folder Structure

- `lessons.db`: SQLite 3 database containing the parsed lessons metadata.
- `lessons.json`: JSON document list of all lessons.
- `files/`: Contains the downloaded PPTX and PDF slide files.
- `README.md`: This documentation file.
- `scrape_primelessons.py`: Scraper script used to build and update this database.

## Database Schema (`lessons`)

The SQLite database `lessons.db` contains a table named `lessons` with the following columns:

| Column Name | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-incrementing primary key |
| `category` | TEXT | Programming language category (`Word Blocks` or `Python`) |
| `unit` | TEXT | Unit name |
| `title` | TEXT | Lesson title |
| `pptx_filename` | TEXT | Filename of local PPTX file |
| `pptx_local_path` | TEXT | Relative path to local PPTX file |
| `pptx_remote_url` | TEXT | Original URL of PPTX file |
| `pdf_filename` | TEXT | Filename of local PDF file |
| `pdf_local_path` | TEXT | Relative path to local PDF file |
| `pdf_remote_url` | TEXT | Original URL of PDF file |
| `other_links` | TEXT | JSON string array of other associated resources |

## Quick SQLite Query Example

You can query the database using SQLite, for example:

```sql
SELECT category, unit, title, pdf_filename FROM lessons WHERE category = 'Python' LIMIT 5;
```
""")

    print("\n[SUCCESS] Scrape and database generation complete!")

if __name__ == "__main__":
    main()
