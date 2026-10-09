"""UMLSSynonymExpander is shared by Agent 2's parallel workers (get_umls_expander singleton)."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from src.agents.agent2.umls_synonym_expander import UMLSSynonymExpander


def _fixture_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE mrconso (cui TEXT, lat TEXT, ts TEXT, lui TEXT, stt TEXT, sui TEXT, ispref TEXT,"
        " aui TEXT, saui TEXT, scui TEXT, sdui TEXT, sab TEXT, tty TEXT, code TEXT, str TEXT,"
        " srl TEXT, suppress TEXT, cvf TEXT)"
    )
    conn.execute("CREATE TABLE mrsty (cui TEXT, tui TEXT, sty TEXT)")
    rows = []
    for i in range(200):
        cui = f"C{i:07d}"
        for j in range(5):
            rows.append((cui, "ENG", "P", "", "", "", "Y" if j == 0 else "N", "", "", "", "",
                         "SNOMEDCT_US", "PT", "", f"term {i} variant {j}", "", "N", ""))
        conn.execute("INSERT INTO mrsty VALUES (?, ?, ?)", (cui, "T047", "Disease or Syndrome"))
    conn.executemany(f"INSERT INTO mrconso VALUES ({','.join('?' * 18)})", rows)
    conn.commit()
    conn.close()


def test_should_return_serial_results_when_queried_from_many_threads(tmp_path):
    db = tmp_path / "mrconso.sqlite"
    _fixture_db(db)
    expander = UMLSSynonymExpander(db_path=str(db))
    queries = [f"term {i} variant 0" for i in range(200)]

    def lookup(q):
        cuis = expander.get_cuis(q, domain_hint="Condition")
        return cuis, [expander.get_synonyms_for_cui(c) for c in cuis]

    expected = [lookup(q) for q in queries]
    with ThreadPoolExecutor(max_workers=16) as pool:
        for _ in range(5):
            assert list(pool.map(lookup, queries)) == expected
