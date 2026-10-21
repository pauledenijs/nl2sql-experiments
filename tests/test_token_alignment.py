from collections import defaultdict
from pathlib import Path
from transformers import AutoTokenizer

MODEL_ID = "meta-llama/Llama-3.2-3B"

def test_all_corpus_words_reconstruct():
    stories = defaultdict(list)

    with Path("data/source/all_stories.tok").open(encoding="utf-8") as source:
        next(source)
        for line in source:
            word, zone, item = line.split()
            stories[int(item)].append((int(zone), word))

    total_words = sum(len(rows) for rows in stories.values())
    assert len(stories) == 10
    assert total_words == 10_256

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
    assert tokenizer.is_fast

    failures = []
    story_failures = []

    for story, rows in sorted(stories.items()):
        words = [word for zone, word in rows]
        text = " ".join(words)

        encoded = tokenizer(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        ids = encoded["input_ids"]
        offsets = encoded["offset_mapping"]

        if tokenizer.decode(ids, clean_up_tokenization_spaces=False) != text:
            story_failures.append(f"story {story}: full text did not decode exactly")

        token_index = 0
        word_end = 0

        for index, (zone, word) in enumerate(rows):
            group_start = word_end
            word_end += len(word) + (1 if index else 0)
            group = []
            crosses_boundary = False

            while token_index < len(ids) and offsets[token_index][0] < word_end:
                start, end = offsets[token_index]
                if not (group_start <= start <= end <= word_end):
                    crosses_boundary = True
                group.append(ids[token_index])
                token_index += 1

            expected = (" " if index else "") + word
            actual = tokenizer.decode(
                group, clean_up_tokenization_spaces=False
            )

            if not group or crosses_boundary or actual != expected:
                failures.append(
                    f"{story}.{zone}: expected {expected!r}, "
                    f"decoded {actual!r}, crosses_boundary={crosses_boundary}"
                )

        if token_index != len(ids):
            story_failures.append(
                f"story {story}: {len(ids) - token_index} subtokens unassigned"
            )

    print(f"Word failures: {len(failures)} / {total_words}")
    print(f"Story failures: {len(story_failures)}")
    for failure in (story_failures + failures)[:25]:
        print(failure)

    assert not story_failures and not failures, (
        f"{len(failures)} word failures; {len(story_failures)} story failures. "
        "Run pytest with -s to see examples."
    )