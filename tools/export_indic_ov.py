"""Convert the official Indic-Transcribe-core checkpoint to OpenVINO IR with int8 weights.

Usage:  uv run tools/export_indic_ov.py [--model core|flex] [--weights int8|int4|fp16] [--out DIR]

Reads cache/models/indic-transcribe-<model> (the official bodhan-ai repo, its own reviewed model
code) and writes three graphs to cache/models/indic-transcribe-<model>-ov-<weights>/:
  encoder.xml     feats (1, 128, T)                      -> states (1, T/8, 1024)
  cross_kv.xml    states                                 -> cross K, V (24, 1, 8, T/8, 128) each
  decoder.xml     input_ids (1, n), start_pos (1,), past K/V (24, 1, 8, P, 128),
                  cross K/V                              -> last logits (1, 7152), new K/V (P+n)
so decoding reuses the self-attention cache and computes cross-attention K/V once per clip.
Weights are compressed with NNCF (weight-only: activations stay fp32/fp16, which keeps
accuracy; measured in tests/eval_indic_asr.py). Licence of the result: Indic Open Model
License v1.0 (a derivative; local use only, credit Bodhan AI / AI4Bharat).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()

import torch  # noqa: E402

MODELS = cfg.path("cache") / "models"
SRC = MODELS / "indic-transcribe-core"   # set from --model in main()
NEG_INF = -10000.0


def load_official():
    sys.path.insert(0, str(SRC))
    from modeling_indic_canary import IndicCanaryForConditionalGeneration  # noqa: E402  (reviewed code)
    m = IndicCanaryForConditionalGeneration.from_pretrained(str(SRC), dtype=torch.float32).eval()
    return m


class Encoder(torch.nn.Module):
    """Batch-1, unpadded encoder. The upstream relative-position table is grown with Python-level
    size checks (traced as a constant, so the graph only worked at the example length); here it
    is precomputed for up to MAX_T frames and sliced by the actual length. With one unpadded clip
    the attention/pad masks are all False, so passing None is exact."""

    MAX_T = 1024  # encoder frames after 8x subsampling (~82 s); chunks are <= 30 s

    def __init__(self, m):
        super().__init__()
        self.enc = m.model.encoder
        pos = self.enc.pos_enc
        pos.extend_pe(self.MAX_T, torch.device("cpu"), torch.float32)
        self.register_buffer("pe", pos.pe.clone())
        self.center = self.pe.shape[1] // 2 + 1

    def forward(self, feats):
        x = feats.transpose(1, 2)
        x, _ = self.enc.pre_encode(x, torch.zeros(1, dtype=torch.int64))
        t = x.shape[1]
        pos_emb = self.pe[:, self.center - t: self.center + t - 1]
        for layer in self.enc.layers:
            x = layer(x, None, pos_emb, None)
        return x


class CrossKV(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.layers = m.model.decoder.layers

    def forward(self, states):
        ks, vs = [], []
        for layer in self.layers:
            k, v = layer.second_sub_layer.project_kv(states)
            ks.append(k)
            vs.append(v)
        return torch.stack(ks), torch.stack(vs)


class DecoderStep(torch.nn.Module):
    """One cached decoding call for n new tokens after P cached ones (n=10 prompt, then n=1)."""

    def __init__(self, m):
        super().__init__()
        self.dec = m.model.decoder
        self.lm_head = m.lm_head

    def forward(self, input_ids, start_pos, past_k, past_v, cross_k, cross_v):
        d = self.dec
        n = input_ids.shape[1]
        pos = start_pos + torch.arange(n, dtype=torch.long).unsqueeze(0)
        emb = d.embedding
        hidden = emb.layer_norm(emb.token_embedding(input_ids) + torch.embedding(emb.position_embedding.pos_enc, pos))
        p = past_k.shape[3]
        # causal mask over [past | new]: new token i may see past + new tokens <= i
        q_idx = torch.arange(n).unsqueeze(1) + p
        k_idx = torch.arange(p + n).unsqueeze(0)
        mask = torch.where(k_idx > q_idx, torch.tensor(NEG_INF), torch.tensor(0.0)).view(1, 1, n, p + n)
        new_k, new_v = [], []
        for i, layer in enumerate(d.layers):
            res = hidden
            normed = layer.layer_norm_1(hidden)
            k_new, v_new = layer.first_sub_layer.project_kv(normed)
            k = torch.cat([past_k[i], k_new], dim=2)
            v = torch.cat([past_v[i], v_new], dim=2)
            new_k.append(k)
            new_v.append(v)
            hidden = res + layer.first_sub_layer.attend(normed, k, v, mask, sdpa=False)
            res = hidden
            normed = layer.layer_norm_2(hidden)
            hidden = res + layer.second_sub_layer.attend(normed, cross_k[i], cross_v[i], None, sdpa=False)
            hidden = hidden + layer.third_sub_layer(layer.layer_norm_3(hidden))
        hidden = d.final_layer_norm(hidden)
        logits = self.lm_head(hidden[:, -1, :])
        return logits, torch.stack(new_k), torch.stack(new_v)


def parity(m) -> None:
    """The wrappers must reproduce the upstream model on a different length than the example."""
    feats = torch.randn(1, 128, 523)
    ref_states = m.model.encoder(feats).last_hidden_state
    states = Encoder(m)(feats)
    e = float((states - ref_states).abs().max())
    ids = torch.tensor([[7, 4, 8, 134, 134, 5, 6, 9, 10, 11]])
    ref = m(input_features=feats, decoder_input_ids=ids, use_cache=False).logits[:, -1]
    ck, cv = CrossKV(m)(states)
    L, H = len(m.model.decoder.layers), m.config.decoder_attention_heads
    dk = m.config.d_model // H
    empty = torch.zeros(L, 1, H, 0, dk)
    logits, k, v = DecoderStep(m)(ids, torch.zeros(1, dtype=torch.long), empty, empty, ck, cv)
    d1 = float((logits - ref).abs().max())
    nxt = logits.argmax(-1, keepdim=True)
    ref2 = m(input_features=feats, decoder_input_ids=torch.cat([ids, nxt], 1), use_cache=False).logits[:, -1]
    logits2, _, _ = DecoderStep(m)(nxt, torch.tensor([ids.shape[1]]), k, v, ck, cv)
    d2 = float((logits2 - ref2).abs().max())
    print(f"parity vs upstream: encoder {e:.2e}, prompt logits {d1:.2e}, cached step logits {d2:.2e}")
    assert e < 1e-3 and d1 < 1e-2 and d2 < 1e-2, "wrapper does not match the upstream model"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="core", choices=["core", "flex"])
    ap.add_argument("--weights", default="int8", choices=["int8", "int4", "fp16"])
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    import nncf
    import openvino as ov
    global SRC
    SRC = MODELS / f"indic-transcribe-{a.model}"
    if not (SRC / "model.safetensors").exists():
        sys.exit(f"{SRC} has no model.safetensors; download bodhan-ai/indic-transcribe-{a.model} first")
    out = a.out or MODELS / f"indic-transcribe-{a.model}-ov-{a.weights}"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    m = load_official()
    L, H, DK = len(m.model.decoder.layers), m.config.decoder_attention_heads, m.config.d_model // m.config.decoder_attention_heads
    feats = torch.randn(1, 128, 801)
    with torch.no_grad():
        states = Encoder(m)(feats)
        ck, cv = CrossKV(m)(states)
        parity(m)
    t_enc = states.shape[1]
    graphs = {
        "encoder": (Encoder(m), (feats,), {"feats": [1, 128, -1]}),
        "cross_kv": (CrossKV(m), (states,), {"states": [1, -1, m.config.d_model]}),
        "decoder": (DecoderStep(m), (torch.zeros(1, 10, dtype=torch.long), torch.zeros(1, dtype=torch.long),
                                     torch.zeros(L, 1, H, 3, DK), torch.zeros(L, 1, H, 3, DK), ck, cv),
                    {"input_ids": [1, -1], "start_pos": [1], "past_k": [L, 1, H, -1, DK],
                     "past_v": [L, 1, H, -1, DK], "cross_k": [L, 1, H, -1, DK], "cross_v": [L, 1, H, -1, DK]}),
    }
    for name, (mod, ex, shapes) in graphs.items():
        t1 = time.time()
        with torch.no_grad():
            ovm = ov.convert_model(mod, example_input=ex, input=[(k, ov.PartialShape(v)) for k, v in shapes.items()])
        for i, o in enumerate(ovm.outputs):
            o.get_tensor().set_names({["logits", "new_k", "new_v"][i] if name == "decoder" else
                                      (["k", "v"][i] if name == "cross_kv" else "states")})
        if a.weights == "int8":
            ovm = nncf.compress_weights(ovm, mode=nncf.CompressWeightsMode.INT8_ASYM)
        elif a.weights == "int4":
            ovm = nncf.compress_weights(ovm, mode=nncf.CompressWeightsMode.INT4_ASYM, ratio=0.9, group_size=128)
        ov.save_model(ovm, out / f"{name}.xml", compress_to_fp16=(a.weights == "fp16"))
        print(f"{name}: converted + {a.weights} in {time.time() - t1:.0f} s")
    for f in ("feature_extractor.safetensors", "tokenizer_spl_tokens.model", "tokenizer_multilingual.model",
              "config.json", "Bodhan_AI_Open_Model_License.md", "indic-open-license.md"):
        shutil.copy(SRC / f, out / f)
    (out / "SOURCE.txt").write_text(
        f"Converted by tools/export_indic_ov.py from bodhan-ai/indic-transcribe-{a.model} "
        f"(official checkpoint) with OpenVINO {ov.__version__} + NNCF {nncf.__version__}, weights {a.weights}.\n"
        f"Licence: Indic Open Model License v1.0. Credit: \"Built with Indic-Transcribe-{a.model.title()} from Bodhan AI / "
        "AI4Bharat.\" Base: Canary-1B-v2 (NVIDIA, CC-BY-4.0). Local use only.\n", encoding="utf-8")
    size = sum(f.stat().st_size for f in out.glob("*.bin")) / 1e9
    print(f"wrote {out} ({size:.2f} GB weights) in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
