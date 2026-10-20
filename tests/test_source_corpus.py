from pathlib import Path
from collections import Counter

def test_raw_corpus_has_ten_stories():
    with Path("data/source/all_stories.tok").open(encoding="utf-8") as file:
        header = file.readline().split()
        rows = [line.split() for line in file if line.strip()]

    assert header == ["word", "zone", "item"]
    assert all(len(row) == 3 for row in rows)
    assert {int(row[2]) for row in rows} == set(range(1, 11))

    counts = Counter(int(row[2]) for row in rows)
    assert counts == {
        1:1073, 2:990, 3:1040, 4: 1085, 5: 1013, 6: 1099, 7: 999, 8: 980, 9: 1038, 10:939,
    }

def test_spr_wordform_mismatches_are_visible():
    tok_words = {}
    with Path("data/source/all_stories.tok").open(encoding="utf-8") as source:
        next(source)
        for line in source:
            word, zone, item = line.split()
            position =  (int(item), int(zone))
            assert position not in tok_words
            tok_words[position] = word

    whole_words = {}
    with Path("data/source/words.tsv").open(encoding="utf-8") as source:
        for line in source:
            code, separator, word = line.rstrip("\n").partition("\t")
            if not code.endswith(".whole"):
                continue

            assert separator, f"No tab in row: {line!r}"
            item, zone, _ = code.split(".")
            position = (int(item), int(zone))
            assert position not in whole_words

            whole_words[position] = "".join(word.split())

    assert len(tok_words) == 10_256
    assert tok_words.keys() == whole_words.keys()

    mismatches = [
        (position, tok_words[position], whole_words[position])
        for position in sorted(tok_words)
        if tok_words[position] != whole_words[position]
    ]

    assert mismatches == [((2, 749), "peaked", "peeked")]

    print(f"\nWordform mismatches: {len(mismatches)}")
    for position, displayed, annotated in mismatches[:25]:
        print(f"{position}: .tok={displayed!r}, .whole={annotated!r}")