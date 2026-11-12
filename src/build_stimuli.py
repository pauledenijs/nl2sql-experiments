from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import csv

MODEL_ID = "meta-llama/Llama-3.2-3B"
SOURCE = Path("data/source/all_stories.tok")
OUTPUT = Path("data/generated/stimuli_all_stories.tsv")
OVERFLOW_POLICY = "error"

EXPECTED_WORD_COUNTS = {
    1: 1073,
    2: 990,
    3: 1040,
    4: 1085,
    5: 1013,
    6: 1099,
    7: 999,
    8: 980,
    9: 1038,
    10: 939,
}

def read_story(story_id):
    if story_id not in EXPECTED_WORD_COUNTS:
        raise ValueError(f"Unknown story ID: {story_id}")
    
    rows = []

    with SOURCE.open(encoding="utf-8") as source:
        header = source.readline().split()
        if header != ["word", "zone", "item"]:
            raise ValueError(f"Unexpected .tok header: {header}")

        for line in source:
            word, zone, item = line.split()
            if int(item) == story_id:
                rows.append((int(zone), word))

    expected = EXPECTED_WORD_COUNTS[story_id]

    if len(rows) != expected:
        raise ValueError(
            f"Story {story_id}: expected {expected} words, found {len(rows)}"
        )

    positions = [zone for zone, word in rows]
    if positions != list(range(1, expected + 1)):
        raise ValueError(f"Story {story_id}: zones are not sequential")

    return rows

def group_subtokens(rows, ids, offsets, tok):
    group_sizes = []
    token_index = 0
    word_end = 0

    for index, (zone, word) in enumerate(rows):
        group_start = word_end #includes the space before this word
        word_end += len(word) + (1 if index else 0)
        first_token = token_index

        while token_index < len(ids) and offsets[token_index][0] < word_end:
            start, end = offsets[token_index]
            if not (group_start <= start <= end <= word_end):
                raise ValueError(f"Token crosses word boundary at zone {zone}")
            token_index += 1

        group_ids = ids[first_token:token_index]
        if not group_ids:
            raise ValueError(f"No subtokens at zone {zone}")

        expected = (" " if index else "") + word
        actual = tok.decode(group_ids, clean_up_tokenization_spaces=False)
        if actual != expected:
            raise ValueError(
                f"Zone {zone}: expected {expected!r}, decoded {actual!r}"
            )
        
        group_sizes.append(len(group_ids))

    if token_index != (len(ids)):
        raise ValueError("Subtokens remained after the last word")

    return group_sizes

def score_subtokens(text, tok, aligned_ids, model):
    encoded = tok(text, return_tensors="pt", truncation=False)
    scoring_ids = encoded["input_ids"][0]

    if scoring_ids[0].item() != tok.bos_token_id:
        raise ValueError("Scoring input does not begin with BOS")

    if scoring_ids[1:].tolist() != aligned_ids:
        raise ValueError("Scoring tokens do not match alignment tokens")

    input_length = scoring_ids.numel()
    context_limit = model.config.max_position_embeddings

    if input_length > context_limit:
        raise ValueError(
            f"Input has {input_length} tokens including BOS; "
            f"context limit is {context_limit}. "
            f"overflow_policy={OVERFLOW_POLICY}"
        )

    encoded = encoded.to("cuda")

    with torch.inference_mode():
        logits = model(**encoded).logits[0, :-1]
        targets = encoded["input_ids"][0, 1:]

        surprisal_nats = -logits.log_softmax(dim=-1).gather(
            dim=1,
            index=targets.unsqueeze(1),
        ).squeeze(1)

    return surprisal_nats.cpu()

def write_stimuli(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow([
            "stimulus_id",
            "story_id",
            "sentence_num",
            "word_position",
            "word",
            "zipf_frequency",
            "surprisal_nats",
        ])

        for stimulus_id, (story_id, zone, word, surprisal) in enumerate(
            records, start=1
            ):
        
            writer.writerow([
                stimulus_id,
                story_id,
                1,      # provisional sentence number
                zone,
                word,
                r"\N",  # deferred frequency: SQL NULL
                surprisal,
            ])  

def main():
    tok = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)
    if not tok.is_fast:
        raise ValueError("A fast tokenizer is required for character offsets")

    # Load once, before processing any stories.
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.float32,
        device_map="cuda",
    )
    model.eval()

    context_limit = model.config.max_position_embeddings
    print(f"Model context limit: {context_limit} tokens")
    print(f"Overflow policy: {OVERFLOW_POLICY}")

    records = []

    for story_id in sorted(EXPECTED_WORD_COUNTS):
        rows = read_story(story_id)
        text = " ".join(word for zone, word in rows)

        aligned = tok(
            text,
            add_special_tokens=False,
            return_offsets_mapping=True,
            truncation=False,
        )
        ids = aligned["input_ids"]

        if tok.decode(ids, clean_up_tokenization_spaces=False) != text:
            raise ValueError(
                f"Story {story_id}: tokens did not reconstruct the input text"
            )
        
        group_sizes = group_subtokens(
            rows, ids, aligned["offset_mapping"], tok
        ) 

        print(
            f"Story {story_id}: {len(rows)} words, {len(ids)} subtokens, "
            f"{len(ids) + 1} input tokens including BOS",
            flush=True,
        )

        surprisal_nats = score_subtokens(text, tok, ids, model)

        if surprisal_nats.numel() != sum(group_sizes):
            raise ValueError(
                f"Story {story_id}: surprisal count does not match groups"
            )

        if not torch.isfinite(surprisal_nats).all().item():
            raise ValueError(
                f"Story {story_id}: non-finite subtoken surprisal"
            )

        word_surprisals = torch.stack([
            group.sum()
            for group in surprisal_nats.split(group_sizes)
        ])

        if word_surprisals.numel() != len(rows):
            raise ValueError(f"Story {story_id}: non-finite word surprisal")

        torch.testing.assert_close(
            word_surprisals.sum(),
            surprisal_nats.sum(),
        )

        records.extend(
            (story_id, zone, word, surprisal)
            for (zone, word), surprisal in zip(
                rows, word_surprisals.tolist(), strict=True
            )
        )

        print(f"Story {story_id}: scored {len(rows)} words")

    expected_total = sum(EXPECTED_WORD_COUNTS.values())
    if len(records) != expected_total:
        raise ValueError(
            f"Expected {expected_total} output rows, found {len(records)}"
        )

    write_stimuli(OUTPUT, records)
    print(f"Wrote {len(records)} rows to {OUTPUT}")
    print("All stories fit the context limit; overflow policy was not triggered.")


if __name__== "__main__":
    main()