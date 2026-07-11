# Prime Lessons Reference Database

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
