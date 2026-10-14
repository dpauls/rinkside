#!/usr/bin/env python3
"""
CLI tool and Antigravity helper to extract tournament rules, period lengths,
overtime formats, and tiebreakers from an official rules PDF or URL.

Usage:
    python3 scripts/extract_rules.py --pdf https://etobicokedolphins.ca/Public/Documents/Pink_the_Rink_XV_Tournament_RULES_2026.pdf
    python3 scripts/extract_rules.py --pdf path/to/rules.pdf
"""
import argparse
import json
import logging
import os
import re
import sys
import zlib
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from src.llm.gemini import GeminiProvider

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def fetch_pdf_bytes(source: str) -> bytes:
    """Load PDF bytes from local path or remote URL."""
    if source.startswith("http://") or source.startswith("https://"):
        log.info(f"Downloading PDF from {source}...")
        resp = requests.get(source, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
        return resp.content
    return Path(source).read_bytes()


def extract_text_from_pdf(content: bytes) -> str:
    """Robust fallback extractor for PDF text using FlateDecode streams and CMap tables."""
    # Try pypdf first if installed
    try:
        import pypdf
        import io
        reader = pypdf.PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if len(text.strip()) > 100:
            return text
    except ImportError:
        pass

    # Direct PDF stream extraction
    def get_stream(obj_num):
        pattern = rb'\b' + str(obj_num).encode() + rb'\s+0\s+obj(.*?)stream\r?\n(.*?)\r?\nendstream'
        m = re.search(pattern, content, re.DOTALL)
        if not m: return b''
        header, s = m.group(1), m.group(2)
        if b'/FlateDecode' in header:
            try:
                return zlib.decompress(s)
            except Exception:
                return s
        return s

    # Parse CMaps if present
    cmaps = {}
    for m in re.finditer(rb'(\d+)\s+0\s+obj.*?/CMapName.*?stream\r?\n(.*?)\r?\nendstream', content, re.DOTALL):
        cid = int(m.group(1))
        stream_bytes = m.group(2)
        try:
            dec = zlib.decompress(stream_bytes).decode('latin1', 'ignore')
        except Exception:
            dec = stream_bytes.decode('latin1', 'ignore')
        cmap = {}
        for src, dst in re.findall(r'<([0-9a-fA-F]{4})>\s*<([0-9a-fA-F]{4})>', dec):
            cmap[int(src, 16)] = chr(int(dst, 16))
        cmaps[cid] = cmap

    # If CMaps found, decode text streams
    decoded_chunks = []
    text_streams = re.findall(rb'stream\r?\n(.*?)\r?\nendstream', content, re.DOTALL)
    for s in text_streams:
        try:
            decomp = zlib.decompress(s)
            # Find Tj and TJ operators
            for chunk in re.findall(rb'\[(.*?)\]\s*TJ', decomp, re.DOTALL):
                parts = re.findall(rb'\(([^\)]*)\)', chunk)
                decoded_chunks.append(''.join([p.decode('latin1', 'ignore') for p in parts]))
            for chunk in re.findall(rb'\(([^\)]*)\)\s*Tj', decomp):
                decoded_chunks.append(chunk.decode('latin1', 'ignore'))
        except Exception:
            pass

    extracted = ' '.join(decoded_chunks)
    # Collapse spaced letters (e.g. 'T e a m s' -> 'Teams')
    clean = re.sub(r'(?<=\b\w)\s(?=\w\b)', '', extracted)
    clean = re.sub(r' +', ' ', clean)
    return clean


EXTRACTION_PROMPT = """You are an expert hockey tournament director and tournament software analyst.
Analyze the following official tournament rules document and extract the tournament specifications into a clean JSON structure.

Document Text:
\"\"\"
{document_text}
\"\"\"

Produce a valid JSON object with EXACTLY this structure:
{{
  "game_rules": {{
    "source_name": "<Full official name of tournament rules document>",
    "source_url": "<URL or PDF source if provided>",
    "round_robin": {{
      "title": "Round Robin Format",
      "periods": "<e.g. 3 periods (10-10-12 min) stop time>",
      "warmup": "<e.g. 3-minute warm-up>",
      "overtime": "<e.g. No overtime in round robin (games can tie)>",
      "timeouts": "<e.g. No timeouts allowed in round robin>",
      "mercy_rule": "<e.g. 5-goal spread in 3rd period initiates run-time>",
      "jerseys": "<e.g. Home team wears dark jerseys>"
    }},
    "elimination": {{
      "title": "Playoff / Elimination Format (Semis & Final)",
      "periods": "<e.g. 3 periods (10-10-12 min) stop time>",
      "timeouts": "<e.g. One 30-second timeout per team>",
      "overtime": "<e.g. 5-minute sudden-victory 4-on-4 (teams do not change ends)>",
      "shootout": "<e.g. Best-of-3 simultaneous shootout from centre ice. Full roster rule.>"
    }},
    "consolation": {{
      "title": "Consolation Games",
      "matchups": "<e.g. A3 vs B3, A4 vs B4>",
      "periods": "<e.g. 3 periods (10-10-12 min) stop time>",
      "timeouts": "<e.g. One 30-second timeout per team>"
    }}
  }},
  "tiebreakers": {{
    "source_name": "<Specific rule header, e.g. Pink the Rink XV Tournament Rules (Rule 16)>",
    "source_url": "<URL if provided>",
    "description": "<Ordered summary of tiebreakers in order>",
    "rules": [
      "<one of: 'wins', 'head_to_head', 'head_to_head_two_way_only', 'goal_diff', 'fewest_goals_against', 'fewest_pim', 'coin_flip'>"
    ],
    "allow_reversion": false
  }}
}}

Pay careful attention to:
1. Head-to-Head: Does it apply to all tied teams, or ONLY if exactly two teams are tied ('head_to_head_two_way_only')?
2. Goal Differential: Is it GF - GA ('goal_diff'), or GF / (GF + GA) percentage?
3. Reversion: Once a rule is applied or not applicable, can it be used again (reversion), or is it strictly sequential with no reversion ('allow_reversion': false)?
4. Overtime in playoffs: Is it 3-on-3 or 4-on-4? How many minutes?
5. Shootout: Simultaneous or alternating? Best of 3 or 5? Full roster rule?

Output ONLY raw JSON with no markdown fences, no preambles, and no conversational filler.
"""


def extract_tournament_rules(source: str) -> dict:
    content = fetch_pdf_bytes(source)
    text = extract_text_from_pdf(content)
    if len(text.strip()) < 50:
        raise ValueError(f"Could not extract meaningful text from {source}.")

    log.info(f"Extracted {len(text)} characters of rules text. Querying Gemini reasoning engine...")
    provider = GeminiProvider()
    prompt = EXTRACTION_PROMPT.format(document_text=text[:12000])
    resp = provider.generate(prompt, purpose="tournament_digest", thinking_level="high", max_tokens=1500)
    if not resp:
        raise RuntimeError("LLM failed to return extraction response.")

    clean_json = re.sub(r'^```json\s*', '', resp.strip())
    clean_json = re.sub(r'\s*```$', '', clean_json)
    data = json.loads(clean_json)

    if source.startswith("http"):
        data.setdefault("game_rules", {})["source_url"] = source
        data.setdefault("tiebreakers", {})["source_url"] = source

    return data


def main():
    parser = argparse.ArgumentParser(description="Extract tournament rules & tiebreakers from official PDF")
    parser.add_argument("--pdf", required=True, help="Path or URL to tournament rules PDF")
    parser.add_argument("--out", help="Optional output JSON path")
    args = parser.parse_args()

    result = extract_tournament_rules(args.pdf)
    json_str = json.dumps(result, indent=2)
    print("\n=== EXTRACTED TOURNAMENT SPECIFICATION ===")
    print(json_str)

    if args.out:
        Path(args.out).write_text(json_str)
        log.info(f"Saved extracted specification to {args.out}")


if __name__ == "__main__":
    main()
