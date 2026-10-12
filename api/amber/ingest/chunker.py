"""Text chunking using LangChain and tiktoken (sizes come from Admin > Settings; default ~800 tokens, 15% overlap)."""

from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter


def chunk_document_blocks(
    blocks: list[dict[str, Any]], chunk_size: int = 800, chunk_overlap: int = 120
) -> list[dict[str, Any]]:
    """Splits parsed document blocks into chunks with token counts and metadata. Sizes are in tokens."""
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    chunks = []
    for block in blocks:
        text = block["content"]
        page = block.get("page", 1)
        section_title = block.get("section_title")

        texts = splitter.split_text(text)
        for sub_text in texts:
            if sub_text.strip():
                # Estimate token count or use len/tokenizer
                token_count = len(sub_text) // 4  # rough estimate or exact via tiktoken if desired
                chunks.append(
                    {
                        "content": sub_text,
                        "token_count": token_count,
                        "section_title": section_title,
                        "metadata": {
                            "page": page,
                            "section": section_title,
                        },
                    }
                )
    return chunks
