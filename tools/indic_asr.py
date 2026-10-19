"""Marathi / Hindi (and 25 more languages) speech-to-text: Indic-Transcribe-core on OpenVINO.

Usage:  uv run tools/indic_asr.py <audio|video> --lang mr|hi [--mode native|mixed|romanised]
                                  [--model core|flex] [--device ov-cpu|ov-gpu|official]
                                  [--weights int8|fp16] [--bench]

Model: bodhan-ai/indic-transcribe-core (Bodhan AI / AI4Bharat; Canary-1B-v2 architecture),
converted by tools/export_indic_ov.py from the official checkpoint to OpenVINO IR with NNCF
int8 weight-only compression (three graphs: encoder, cross-attention K/V, cached decoder step).
`official` runs the upstream PyTorch code unchanged (fp32, CPU) as the quality reference.
Front-end, prompt and long-audio handling are ported from the official repo for parity:
  - mel: pre-emphasis 0.97, STFT 512/160/400 (Hann from the checkpoint), power, checkpoint mel
    matrix, log(x + 2^-24), per-feature mean/unbiased-std normalisation; < 1 s padded centred
  - prompt: 10 tokens <|startofcontext|><|startoftranscript|><|emo:undefined|><|lang|><|lang|>
    <|pnc|><|noitn|/itn|><|noromanized|/romanized|><|notimestamp|><|nodiarize|>; greedy decode
  - long audio: cut at pauses into <= 30 s pieces (target 25 s); a piece whose output loops
    (4-gram repetition > 50 %) is split again, at most twice, then de-looped
The community int8 ONNX (adidsh/...-int8-onnx) was rejected: 43 % WER on the fixtures (W8A8
activation quantisation) and OpenVINO cannot load it. No timestamps: word timings come from
tools/align.py (MMS). Licence: Indic Open Model License v1.0; credit "Built with
Indic-Transcribe-Core from Bodhan AI / AI4Bharat."
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

MODELS = cfg.path("cache") / "models"
OFFICIAL = MODELS / "indic-transcribe-core"            # official repo (code, configs, fp32 weights)


def src_dir(model: str = "core") -> Path:
    """Official repo download: cache/models/indic-transcribe-<core|flex>."""
    return MODELS / f"indic-transcribe-{model}"


def ov_dir(weights: str = "int8", model: str = "core") -> Path:
    return MODELS / f"indic-transcribe-{model}-ov-{weights}"
SR = 16000
MODES = {"native": (False, False), "mixed": (True, False), "romanised": (False, True), "romanized": (False, True)}
LANGS = ("as", "bgc", "bhb", "bho", "bn", "brx", "doi", "en", "gu", "hi", "hne", "kn", "kok", "ks", "mai",
         "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "ta", "te", "ur")
LOOP_REPETITION, LOOP_MIN_WORDS, MAX_NEW_TOKENS = 0.5, 20, 512


# ------------------------------------------------------------------ tokenizer

class Tokenizer:
    def __init__(self, d: Path = OFFICIAL):  # a model dir with tokenizer_*.model
        import sentencepiece as spm
        self.spl = spm.SentencePieceProcessor(model_file=str(d / "tokenizer_spl_tokens.model"))
        self.multi = spm.SentencePieceProcessor(model_file=str(d / "tokenizer_multilingual.model"))
        self.spl_size = self.spl.get_piece_size()
        self.vocab = self.spl_size + self.multi.get_piece_size()
        tid = self.spl.piece_to_id
        self.pad, self.eos = tid("<pad>"), tid("<|endoftext|>")
        self.base = [tid(p) for p in ("<|startofcontext|>", "<|startoftranscript|>", "<|emo:undefined|>",
                                      "<|en|>", "<|en|>", "<|pnc|>", "<|noitn|>", "<|noromanized|>",
                                      "<|notimestamp|>", "<|nodiarize|>")]
        self.itn, self.rom = tid("<|itn|>"), tid("<|romanized|>")
        self._lang = tid

    def prompt(self, lang: str, mode: str = "native") -> list[int]:
        lid = self._lang(f"<|{lang}|>")
        if lid == 0:
            raise ValueError(f"unsupported language {lang!r}")
        p = list(self.base)
        p[3] = p[4] = lid
        itn, rom = MODES[mode]
        if itn:
            p[6] = self.itn
        if rom:
            p[7] = self.rom
        return p

    def decode(self, ids: list[int]) -> str:
        pieces = [self.spl.id_to_piece(i) if i < self.spl_size else self.multi.id_to_piece(i - self.spl_size)
                  for i in ids if 0 <= i < self.vocab]
        return "".join(pieces).replace("▁", " ").strip()


# ----------------------------------------------------------------- front-end

class Features:
    def __init__(self, d: Path = OFFICIAL):
        from safetensors.numpy import load_file
        t = load_file(str(d / "feature_extractor.safetensors"))
        self.fb = t["fb"].astype(np.float32)[0]          # (128, 257)
        self.window = t["window"].astype(np.float32)     # (400,)

    def __call__(self, wav: np.ndarray) -> np.ndarray:
        import torch
        n = len(wav)
        if n < SR:  # pad to 1 s, centred, like training
            buf = np.zeros(SR, np.float32)
            off = round((SR - n) / 2)
            buf[off:off + n] = wav
            wav, n = buf, SR
        x = torch.from_numpy(wav.astype(np.float32))[None]
        x = torch.cat((x[:, :1], x[:, 1:] - 0.97 * x[:, :-1]), dim=1)
        s = torch.stft(x, n_fft=512, hop_length=160, win_length=400, window=torch.from_numpy(self.window),
                       center=True, return_complex=True)
        p = torch.view_as_real(s).pow(2).sum(-1)               # |X|^2 (sqrt then pow 2 in the original)
        m = torch.log(torch.matmul(torch.from_numpy(self.fb), p) + 2.0 ** -24)
        t = n // 160 + 1
        m = m[..., :t]
        mean = m.mean(dim=2, keepdim=True)
        std = torch.sqrt(((m - mean) ** 2).sum(dim=2, keepdim=True) / (t - 1)) + 1e-5
        return ((m - mean) / std).numpy().astype(np.float32)   # (1, 128, T)


# ------------------------------------------------------------------ backends

class OVBackend:
    """OpenVINO IR from tools/export_indic_ov.py: encoder, cross K/V, cached decoder step."""

    def __init__(self, device: str = "ov-cpu", weights: str = "int8", model: str = "core"):
        import openvino as ov
        d = ov_dir(weights, model)
        if not (d / "decoder.xml").exists():
            raise FileNotFoundError(f"{d} missing; run: uv run tools/export_indic_ov.py --model {model} --weights {weights}")
        core = ov.Core()
        core.set_property({"CACHE_DIR": str(cfg.path("cache") / "openvino")})
        target = device.split("-", 1)[1].upper()
        conf = {"PERFORMANCE_HINT": "LATENCY"}
        self.enc = core.compile_model(str(d / "encoder.xml"), target, conf)
        self.ckv = core.compile_model(str(d / "cross_kv.xml"), target, conf)
        self.dec = core.compile_model(str(d / "decoder.xml"), target, conf)
        self.dec_req = self.dec.create_infer_request()
        c = json.loads((d / "config.json").read_text(encoding="utf-8"))
        self.L, self.H = c["decoder_layers"], c["decoder_attention_heads"]
        self.DK = c["d_model"] // self.H

    def greedy(self, feats: np.ndarray, prompt: list[int], stop: set[int], max_new: int) -> list[int]:
        states = self.enc(feats)[0]
        kv = self.ckv(states)
        ck, cv = kv[0], kv[1]
        pk = np.zeros((self.L, 1, self.H, 0, self.DK), np.float32)
        pv = pk.copy()
        out: list[int] = []
        feed_ids, pos = np.array([prompt], np.int64), 0
        for _ in range(max_new):
            r = self.dec_req.infer({"input_ids": feed_ids, "start_pos": np.array([pos], np.int64),
                                    "past_k": pk, "past_v": pv, "cross_k": ck, "cross_v": cv})
            logits, pk, pv = r[0], r[1], r[2]
            nxt = int(np.argmax(logits[0]))
            if nxt in stop or len(prompt) + len(out) >= 1023:
                break
            out.append(nxt)
            pos += feed_ids.shape[1]
            feed_ids = np.array([[nxt]], np.int64)
        return out


class OfficialBackend:
    """The upstream PyTorch code, fp32 CPU: the quality reference (slow, ~5 GB RAM)."""

    def __init__(self, model: str = "core"):
        sys.path.insert(0, str(src_dir(model)))
        import torch
        from indic_transcribe import IndicTranscribe  # reviewed code from the official repo
        self.asr = IndicTranscribe.from_pretrained(str(src_dir(model)), device="cpu", dtype=torch.float32)

    def transcribe_piece(self, wav: np.ndarray, lang: str, mode: str) -> str:
        import torch
        return self.asr.transcribe(torch.from_numpy(wav), lang=lang, mode=mode, max_new_tokens=MAX_NEW_TOKENS)


# --------------------------------------------------------------- transcriber

class IndicASR:
    def __init__(self, device: str | None = None, weights: str | None = None, model: str | None = None,
                 mode: str = "native"):
        c = cfg.load().get("indic_asr", {})
        self.device = device or c.get("device", "ov-cpu")
        self.weights = weights or c.get("weights", "int8")
        # which checkpoint: explicit, else per output mode from config (Flex is the one that
        # actually writes English words in Latin script; Core ignores the mode switch)
        self.model = model or c.get("model_native" if mode == "native" else "model_mixed", "core")
        d = ov_dir(self.weights, self.model)
        files = d if (d / "tokenizer_spl_tokens.model").exists() else src_dir(self.model)
        self.tok, self.fe = Tokenizer(files), Features(files)
        self.be = OfficialBackend(self.model) if self.device == "official" else \
            OVBackend(self.device, self.weights, self.model)

    def _decode_once(self, wav: np.ndarray, lang: str, mode: str, max_new: int = MAX_NEW_TOKENS) -> str:
        if isinstance(self.be, OfficialBackend):
            return self.be.transcribe_piece(wav, lang, mode)
        out = self.be.greedy(self.fe(wav), self.tok.prompt(lang, mode), {self.tok.eos, self.tok.pad}, max_new)
        return self.tok.decode(out)

    def _guarded(self, wav, lang, mode, depth=0) -> str:
        text = self._decode_once(wav, lang, mode)
        words = text.split()
        if not (len(words) >= LOOP_MIN_WORDS and _repetition(words) > LOOP_REPETITION):
            return text
        if depth >= 2 or len(wav) < 4 * SR:
            return " ".join(_collapse_repeats(words))
        half = len(wav) / SR / 2
        parts = split_on_silence(wav, target=half, hard_max=half + 2.0)
        if len(parts) < 2:
            m = len(wav) // 2
            parts = [(0, m), (m, len(wav))]
        return " ".join(t for t in (self._guarded(wav[a:b], lang, mode, depth + 1).strip()
                                    for a, b in parts if b - a >= 1600) if t)

    def transcribe(self, wav: np.ndarray, lang: str, mode: str = "native") -> dict:
        if lang not in LANGS:
            raise ValueError(f"lang must be one of {LANGS}")
        t0 = time.time()
        segs = split_on_silence(wav)
        texts = []
        for a, b in segs:
            if b - a >= 1600:
                texts.append({"start": round(a / SR, 3), "end": round(b / SR, 3),
                              "text": self._guarded(wav[a:b], lang, mode).strip()})
        dt = time.time() - t0
        return {"text": " ".join(t["text"] for t in texts if t["text"]), "chunks": texts, "language": lang,
                "mode": mode, "model": self.model,
                "device": self.device if self.device == "official" else f"{self.device}/{self.weights}",
                "seconds": round(dt, 2),
                "rtf": round(dt / max(len(wav) / SR, 1e-6), 3)}


def _repetition(words, n=4):
    grams = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    return (len(grams) - len(set(grams))) / max(1, len(grams))


def _collapse_repeats(words, keep=2, max_n=4):
    out = list(words)
    for n in range(1, max_n + 1):
        res, i = [], 0
        while i < len(out):
            gram, j, reps = out[i:i + n], i + n, 1
            while len(gram) == n and out[j:j + n] == gram:
                reps += 1
                j += n
            if reps > keep:
                res.extend(gram * keep)
                i = j
            else:
                res.append(out[i])
                i += 1
        out = res
    return out


def split_on_silence(wav: np.ndarray, target=25.0, hard_max=30.0, win_ms=30.0, rel_db=25.0, min_sil=0.25):
    """<= hard_max s pieces, cut at the middle of pauses near `target` (official long_form.py)."""
    n = len(wav)
    if n <= int(hard_max * SR):
        return [(0, n)]
    hop = max(1, int(SR * win_ms / 1000))
    fr = wav[: (n // hop) * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt(np.maximum((fr ** 2).mean(1), 1e-12)))
    quiet = db < db.max() - rel_db
    runs, start = [], None
    for i, q in enumerate(quiet):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(quiet)))
    cuts = [((a + b) // 2) * hop for a, b in runs if (b - a) >= int(min_sil * SR / hop)]
    segs, pos = [], 0
    while n - pos > int(hard_max * SR):
        lo, hi, ideal = pos + int(5 * SR), pos + int(hard_max * SR), pos + int(target * SR)
        usable = [c for c in cuts if lo < c < hi]
        cut = min(usable, key=lambda c: abs(c - ideal)) if usable else hi
        segs.append((pos, cut))
        pos = cut
    if pos < n:
        segs.append((pos, n))
    return segs


def load_audio(path: str | Path) -> np.ndarray:
    """Mono 16 kHz float32. Decodes at the native rate with the pinned ffmpeg, then resamples
    with torchaudio's sinc_interp_hann (the model's training resampler)."""
    import torch
    import torchaudio
    sr = int(json.loads(subprocess.run([cfg.ffprobe(), "-v", "error", "-select_streams", "a:0", "-show_entries",
                                        "stream=sample_rate", "-of", "json", str(path)], capture_output=True,
                                       text=True, check=True).stdout)["streams"][0]["sample_rate"])
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    wav = torch.from_numpy(np.frombuffer(raw, np.float32).copy())
    if sr != SR:
        wav = torchaudio.functional.resample(wav, sr, SR)
    return wav.numpy()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--mode", default="native", choices=sorted(MODES))
    ap.add_argument("--device", help="ov-cpu | ov-gpu | official (default: [indic_asr].device)")
    ap.add_argument("--weights", help="int8 | fp16 OpenVINO weights (default: [indic_asr].weights)")
    ap.add_argument("--model", choices=["core", "flex"], help="default: [indic_asr].model_native / model_mixed")
    ap.add_argument("--bench", action="store_true", help="time ov-cpu and ov-gpu on this file")
    a = ap.parse_args()
    wav = load_audio(a.file)
    devices = ["ov-cpu", "ov-gpu"] if a.bench else [a.device]
    for d in devices:
        t0 = time.time()
        try:
            asr = IndicASR(d, a.weights, a.model, a.mode)
        except Exception as e:  # noqa: BLE001
            print(f"{d}: failed to load ({str(e)[:200]})")
            continue
        load_s = time.time() - t0
        r = asr.transcribe(wav, a.lang, a.mode)
        print(f"[{r['model']} {r['device']}] load {load_s:.1f} s, {len(wav) / SR:.1f} s audio in {r['seconds']} s (RTF {r['rtf']})")
        print(r["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
