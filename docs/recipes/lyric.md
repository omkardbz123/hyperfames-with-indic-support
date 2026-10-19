# Lyric video (Marathi / Hindi / English)

## Inputs
- The song (licence known) and **the lyrics from the user** (best). Without lyrics: transcribe the vocal stem and flag low-confidence words for the user.
- Background: footage loops, photos, colour/gradient cards.

## Analysis
1. `uv run tools/separate.py <song> --quality` (BS-RoFormer vocals).
2. `uv run tools/transcribe.py <song> --lang mr --vocals --text-file lyrics.txt` → word timings within ~40 ms. Write numbers as words.
3. `analyze_audio.py` for sections/drops (big lines on the chorus, accents on hits).

## Structure
Verse lines small and calm; chorus lines big with accent colour; title card at the start (song, artist); credits at the end.

## Techniques → EDL
- Captions do the work: `"captions": {"src": "analysis/<id>/transcript.json", "offset": <music at - from>, "style": "kinetic"|"pill", "max_words": 4}`.
- For a full-screen look use `"text"` items with `"anim": "words"` and `"word_times"` from the transcript for hero lines.
- Background clips cut on downbeats or sections; slow `push_in`; `light-leak` shader between sections.
- Beat-reactive accents: `flashes` (low peak 0.3) on snares in the chorus.
- Fonts: Mukta/Baloo 2/Tiro Devanagari for Devanagari; Rozha One for traditional titles.

## Defaults
`format: reels` (or youtube 16:9), captions kinetic, grade `faded_matte`.

## QA specifics
- Every lyric word matches the user's text exactly; low-confidence alignments reviewed.
- Lines readable ≥ 0.8 s; no orphan single words at line ends.
