from pathlib import Path
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
import csv

MODEL_ID = "meta-llama/Llama-3.2-3B"

SOURCE = Path("data/source/all_stories.tok")

def read_story_one():
    rows = []

    with SOURCE.open(encoding="utf-8") as source:
        header = source.readline().split()
        if header != ["word", "zone", "item"]:
            raise ValueError(f"Unexpected .tok header: {header}")

        for line in source:
            word, zone, item = line.split()
            if item == "1":
                rows.append((int(zone), word))

    if len(rows) != 1073:
        raise ValueError(f"Expected 1073 story 1 words, found {len(rows)}")

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

def score_subtokens(text, tok, aligned_ids):
    encoded = tok(text, return_tensors="pt", truncation=False)
    scoring_ids = encoded["input_ids"][0]

    if scoring_ids[0].item() != tok.bos_token_id:
        raise ValueError("Scoring input does not begin with BOS")

    if scoring_ids[1:].tolist() != aligned_ids:
        raise ValueError("Scoring tokens do not match alignment tokens")

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        dtype=torch.float32,
        device_map="cuda",
    )
    model.eval()
    encoded = encoded.to("cuda")

    with torch.inference_mode():
        logits = model(**encoded).logits[0, :-1]
        targets = encoded["input_ids"][0, 1:]

        surprisal_nats = -logits.log_softmax(dim=-1).gather(
            dim=1,
            index=targets.unsqueeze(1),
        ).squeeze(1)

    return surprisal_nats.cpu()

def write_stimuli(path, rows, word_surprisals):
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

        for index, ((zone, word), surprisal) in enumerate(
            zip(rows, word_surprisals, strict=True), start=1
            ):
        
            writer.writerow([
                index,
                1,
                1,
                zone,
                word,
                r"\N",
                surprisal.item(),
            ])  

if __name__== "__main__":
    rows = read_story_one()
    text = " ".join(word for zone, word in rows)
    tok = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)

    aligned = tok(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )
    ids = aligned["input_ids"]
    group_sizes = group_subtokens(rows, ids, aligned["offset_mapping"], tok)    
    print(f"Grouped {len(group_sizes)} words from {sum(group_sizes)} subtokens")

    
    surprisal_nats = score_subtokens(text, tok, ids)
    if surprisal_nats.numel() != sum(group_sizes):
        raise ValueError("Surprisal count does not match grouped subtokens")

    if not torch.isfinite(surprisal_nats).all().item():
        raise ValueError("Surprisal contains a non-finte value")

    print(f"Scored {surprisal_nats.numel()} subtokens")

    word_surprisal_nats = torch.stack([
        group.sum()
        for group in surprisal_nats.split(group_sizes)
    ])

    if word_surprisal_nats.numel() != len(rows):
        raise ValueError("Word surprisal count does not match corpus rows")

    torch.testing.assert_close(
        word_surprisal_nats.sum(),
        surprisal_nats.sum(),
    )

    print(f"Computed {word_surprisal_nats.numel()} word surprisal values")
    
    if tok.decode(ids, clean_up_tokenization_spaces=False) != text:
        raise ValueError("Story 1 tokens did not reconstruct the input text")

    
    print(f"Story 1: {len(rows)} words, {len(ids)} subtokens")
    print(f"First: {rows[0]}")
    print(f"Last: {rows[-1]}")

    output_path = Path("data/generated/stimuli_story1.tsv")
    write_stimuli(output_path, rows, word_surprisal_nats)
    print(f"Wrote {len(rows)} rows to {output_path}")