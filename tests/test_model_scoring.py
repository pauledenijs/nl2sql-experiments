import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from pathlib import Path

MODEL_ID = "meta-llama/Llama-3.2-3B"

def test_story_one_alignment_matches_scoring():
    words = []
    with Path("data/source/all_stories.tok").open(encoding="utf-8") as source:
        next(source)
        for line in source:
            word, zone, item = line.split()
            if item == "1":
                words.append(word)

    assert len(words) == 1073
    text = " ".join(words)

    tok = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)

    aligned = tok(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
    )
    aligned_ids = aligned["input_ids"]
    offsets = aligned["offset_mapping"]

    scoring = tok(text, return_tensors="pt", truncation=False)
    scoring_ids = scoring["input_ids"][0]

    assert scoring_ids[0].item() == tok.bos_token_id
    assert scoring_ids[1:].tolist() == aligned_ids

    group_sizes = []
    token_index = 0
    word_end = 0

    for index, word in enumerate(words):
        group_start = word_end
        word_end += len(word) + (1 if index else 0)
        group_size = 0

        while token_index < len(aligned_ids) and offsets[token_index][0] < word_end:
            start, end = offsets[token_index]
            assert group_start <= start <= end <= word_end
            group_size += 1
            token_index += 1

        assert group_size > 0
        group_sizes.append(group_size)

    assert token_index == len(aligned_ids)
    assert sum(group_sizes) == len(aligned_ids)

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, dtype=torch.float32, device_map="cuda"
    )
    model.eval()

    with torch.inference_mode():
        logits = model(**scoring.to("cuda")).logits[0, :-1]
        targets = scoring_ids[1:].to(logits.device)

        surprisal_nats = -logits.log_softmax(dim=-1).gather(dim=1, index=targets.unsqueeze(1)).squeeze(1)

        assert surprisal_nats.numel() == sum(group_sizes)
        assert torch.isfinite(surprisal_nats).all()

        word_surprisal_nats = torch.stack([
            group.sum()
            for group in surprisal_nats.split(group_sizes)
        ])

        assert word_surprisal_nats.numel() == len(words) == 1073
        torch.testing.assert_close(
            word_surprisal_nats.sum(),
            surprisal_nats.sum(),
        )

    print(
        f"Story 1: {len(words)} words, "
        f"{sum(group_sizes)} subtokens, "
        f"{surprisal_nats.numel()} surprisal values"
    )

def test_next_token_surprisal_shift_and_gather():
    tok = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, dtype=torch.float32, device_map="cuda"
    )
    model.eval()

    enc = tok("The quick brown fox", return_tensors="pt").to("cuda")
    ids = enc["input_ids"][0]

    assert tok.convert_ids_to_tokens(ids.tolist()) == [
        "<|begin_of_text|>", "The", "Ġquick", "Ġbrown", "Ġfox"
    ]
    assert ids[0].item() == tok.bos_token_id

    with torch.inference_mode():
        logits = model(**enc).logits

        assert tuple(logits.shape) == (1, 5, model.config.vocab_size)

        # Logits at BOS predict "The"; logits at "The" predict " quick".
        log_probs = logits[0, :-1].log_softmax(dim=-1) # [4, vocab]
        targets = ids[1:] # [4]

        surprisal_nats = -log_probs.gather(
            dim=1, index=targets.unsqueeze(1)
        ).squeeze(1) # [4]

        assert tuple(surprisal_nats.shape) == (4,)

        # Independently calculate surprisal for "The" from BOS's logits.
        manual_first = -logits[0, 0].log_softmax(dim=-1)[ids[1]]
        torch.testing.assert_close(surprisal_nats[0], manual_first)