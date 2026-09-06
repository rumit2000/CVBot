# ingestion.py
import os
import json
from pathlib import Path

def _extract_pdf_snippet(pdf_path: Path, limit: int = 500) -> str:
    try:
        from pypdf import PdfReader
        if not pdf_path.exists():
            return ""
        reader = PdfReader(str(pdf_path))
        buf = []
        for page in reader.pages[:3]:
            t = (page.extract_text() or "").strip()
            if t:
                buf.append(t)
        text = "\n".join(buf).strip()
        if len(text) > limit:
            text = text[:limit].rstrip() + "…"
        return text
    except Exception:
        return ""


def _normalize_faq_topics(topics):
    """Convert generated FAQ items to the schema consumed by bot.py."""
    normalized = []
    used_keys = set()

    for index, item in enumerate(topics, start=1):
        if not isinstance(item, dict):
            continue

        question = str(item.get("q") or "").strip()
        label = str(item.get("label") or question).strip()
        full = str(item.get("full") or question or label).strip()
        reply = str(item.get("reply") or item.get("a") or "").strip()
        if not label or not full or not reply:
            continue

        raw_key = str(item.get("key") or "").strip().lower()
        key = "".join(char for char in raw_key if char.isascii() and (char.isalnum() or char in "_-"))
        key = key[:32] or f"faq_{index}"
        base_key = key
        suffix = 2
        while key in used_keys:
            key = f"{base_key[:28]}_{suffix}"
            suffix += 1
        used_keys.add(key)

        normalized.append({
            "key": key,
            "label": label,
            "full": full,
            "reply": reply,
        })

    return normalized


def _build_rag_index(pdf_path: Path) -> None:
    # Не падаем, если API rag.py изменился.
    try:
        import rag
        paths = [str(pdf_path)]

        called = False
        for fname in ["ingest", "build_index", "build_index_from_files", "build", "index_files"]:
            if hasattr(rag, fname):
                try:
                    info = getattr(rag, fname)(paths)
                    print(f"[INGEST] RAG index: {info}")
                    called = True
                    break
                except Exception as e:
                    print(f"[INGEST] RAG '{fname}' error: {e}")
        if not called:
            print("[INGEST] RAG: suitable function not found, skipped.")
    except Exception as e:
        print(f"[INGEST] RAG import/build error: {e}")


def _generate_faq(snippet: str, about_text: str):
    faq_payload = {"topics": []}
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[INGEST] OPENAI_API_KEY not set; skipping FAQ generation")
        return faq_payload

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        system = (
            "Ты пишешь JSON-объект с часто задаваемыми вопросами по резюме. "
            'Строго верни JSON-объект формата {"topics":[{"key":"short_ascii_key",'
            '"label":"...","full":"...","reply":"..."}]} без пояснений.'
        )
        user = (
            "Сгенерируй 5 лаконичных Q&A на русском по резюме ниже. "
            "label — короткий текст кнопки, full — полный вопрос, "
            "reply — ответ в 1–3 предложениях. Текст резюме:\n\n"
            + (snippet or about_text)
        )

        # Используем Chat Completions (надёжнее в разных версиях SDK).
        chat = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL_JSON", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
        )
        raw = (chat.choices[0].message.content or "").strip()

        # Извлекаем JSON, даже если модель вернула блок ```json.
        candidate = raw
        if "```" in raw:
            parts = raw.split("```")
            for i in range(len(parts) - 1):
                block = parts[i + 1]
                if block.strip().startswith("json"):
                    candidate = block.split("\n", 1)[1] if "\n" in block else ""
                    break

        parsed = json.loads(candidate) if candidate else {}
        if isinstance(parsed, list):
            parsed = {"topics": parsed}
        topics = parsed.get("topics", []) if isinstance(parsed, dict) else []
        if isinstance(topics, list):
            faq_payload = {"topics": _normalize_faq_topics(topics)}
        else:
            print("[INGEST] model returned non-list topics, keeping empty list")
    except Exception as e:
        print(f"[INGEST] JSON parse error from model: {e}")

    return faq_payload


def main() -> None:
    print("[INGEST] start")

    data_dir = Path("data")
    pdf_path = data_dir / "CVTimurAsyaev.pdf"
    about_path = data_dir / "about_cache.txt"
    faq_path = data_dir / "faq_cache.json"

    # 1) Построение RAG-индекса.
    _build_rag_index(pdf_path)

    # 2) about/faq: гарантированный формат и устойчивость.
    data_dir.mkdir(parents=True, exist_ok=True)
    snippet = _extract_pdf_snippet(pdf_path)
    default_about = (
        "Краткая выжимка профиля из резюме Тимура Асяева. "
        "Этот текст используется ботом как 'about' до уточнения моделью."
    )
    about_text = snippet or default_about

    try:
        about_path.write_text(about_text, encoding="utf-8")
        print(f"[INGEST] wrote: {about_path} ({len(about_text)} bytes)")
    except Exception as e:
        print(f"[INGEST] about write error: {e}")

    faq_payload = _generate_faq(snippet, about_text)
    try:
        serialized = json.dumps(faq_payload, ensure_ascii=False, indent=2)
        faq_path.write_text(serialized, encoding="utf-8")
        print(f"[INGEST] wrote: {faq_path} ({len(serialized)} bytes)")
    except Exception as e:
        print(f"[INGEST] faq write error: {e}")

    print("[INGEST] done")


if __name__ == "__main__":
    main()
