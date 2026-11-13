from app.services.chunking import chunk_sections
from app.services.parsers import Section


def test_short_text_is_single_chunk():
    chunks = chunk_sections([Section("Hello world.", page=3)], chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].text == "Hello world."
    assert chunks[0].page == 3


def test_chunks_respect_size_and_keep_all_content():
    paragraphs = [f"Paragraph {i} " + "word " * 40 for i in range(30)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_sections([Section(text)], chunk_size=500, overlap=100)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    joined = "\n".join(c.text for c in chunks)
    for i in range(30):
        assert f"Paragraph {i} " in joined


def test_overlap_carries_context_between_chunks():
    sentences = " ".join(f"Sentence number {i} is here." for i in range(60))
    chunks = chunk_sections([Section(sentences)], chunk_size=300, overlap=80)
    assert len(chunks) > 2
    for prev, nxt in zip(chunks, chunks[1:]):
        last_sentence = prev.text.split("\n")[-1]
        assert last_sentence in nxt.text


def test_giant_token_is_hard_split():
    chunks = chunk_sections([Section("x" * 2500)], chunk_size=1000, overlap=0)
    assert [len(c.text) for c in chunks] == [1000, 1000, 500]


def test_pages_are_not_merged():
    chunks = chunk_sections([Section("Page one.", 1), Section("Page two.", 2)])
    assert [(c.text, c.page) for c in chunks] == [("Page one.", 1), ("Page two.", 2)]


def test_empty_sections_are_dropped():
    assert chunk_sections([Section("   \n\n  "), Section("")]) == []
