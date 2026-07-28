"""
summarizer.py
Extrae texto de PDFs, artículos web y vídeos de YouTube, y genera un resumen
usando un algoritmo extractivo (TextRank) - sin llamadas a ninguna API de pago.
"""
import re
import pdfplumber
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
from sumy.nlp.stemmers import Stemmer
from sumy.utils import get_stop_words

LANGUAGE = "spanish"

MAX_PAGES_FREE = 15
MAX_YOUTUBE_MINUTES_FREE = 20
MAX_PAGES_PREMIUM = 100
MAX_YOUTUBE_MINUTES_PREMIUM = 90


class ExtractionError(Exception):
    pass


def extract_from_pdf(file_path: str, is_premium: bool) -> str:
    max_pages = MAX_PAGES_PREMIUM if is_premium else MAX_PAGES_FREE
    text_parts = []
    with pdfplumber.open(file_path) as pdf:
        if len(pdf.pages) > max_pages:
            raise ExtractionError(
                f"El PDF tiene {len(pdf.pages)} páginas. El límite es {max_pages}."
            )
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    text = "\n".join(text_parts).strip()
    if not text:
        raise ExtractionError("No se pudo extraer texto de este PDF (puede ser escaneado/imagen).")
    return text


def extract_from_url(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ExtractionError("No se pudo acceder a esa URL.")
    text = trafilatura.extract(downloaded)
    if not text:
        raise ExtractionError("No se pudo extraer texto legible de esa página.")
    return text.strip()


def _extract_youtube_id(url: str) -> str:
    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"v=([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ExtractionError("No pude reconocer el enlace de YouTube.")


def extract_from_youtube(url: str, is_premium: bool) -> str:
    video_id = _extract_youtube_id(url)
    max_minutes = MAX_YOUTUBE_MINUTES_PREMIUM if is_premium else MAX_YOUTUBE_MINUTES_FREE
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["es", "en"])
    except Exception as e:
        raise ExtractionError(
            "Este vídeo no tiene subtítulos disponibles (automáticos o manuales)."
        ) from e

    duration_seconds = transcript[-1]["start"] + transcript[-1].get("duration", 0)
    if duration_seconds > max_minutes * 60:
        raise ExtractionError(
            f"El vídeo dura más de {max_minutes} minutos, que es el límite actual."
        )
    text = " ".join(chunk["text"] for chunk in transcript)
    return text.strip()


def summarize_text(text: str, sentence_count: int = 6) -> str:
    if len(text.split()) < 40:
        return text # demasiado corto para resumir, se devuelve tal cual
    parser = PlaintextParser.from_string(text, Tokenizer(LANGUAGE))
    stemmer = Stemmer(LANGUAGE)
    summarizer = TextRankSummarizer(stemmer)
    summarizer.stop_words = get_stop_words(LANGUAGE)
    sentences = summarizer(parser.document, sentence_count)
    summary = "\n\n".join(f"• {str(s)}" for s in sentences)
    return summary if summary else text[:1000]


def summarize_as_flashcards(text: str, count: int = 8) -> str:
    """Versión simple de 'flashcards': frases clave numeradas como pregunta implícita."""
    parser = PlaintextParser.from_string(text, Tokenizer(LANGUAGE))
    stemmer = Stemmer(LANGUAGE)
    summarizer = TextRankSummarizer(stemmer)
    summarizer.stop_words = get_stop_words(LANGUAGE)
    sentences = summarizer(parser.document, count)
    cards = [f"{i+1}. {str(s)}" for i, s in enumerate(sentences)]
    return "\n".join(cards)
