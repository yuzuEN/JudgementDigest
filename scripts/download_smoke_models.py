"""Download one immutable HF snapshot for the opt-in model smoke test."""
import argparse
import json
import re
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--latest", action="store_true", help="Resolve HF main once, then pin that SHA")
    args = parser.parse_args()
    spec = json.loads((ROOT / ".github/model-smoke.json").read_text())
    revision = HfApi().model_info(spec["repo_id"]).sha if args.latest else spec["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Smoke tests require an immutable full HF commit SHA")
    snapshot_download(spec["repo_id"], revision=revision, local_dir=args.output,
                      allow_patterns=[folder + "/**" for folder in spec["folders"]])
    # Missing bundles must fail here, rather than silently enabling mock/SVM fallbacks.
    for folder in spec["folders"]:
        if not (args.output / folder / "meta.json").is_file() and folder != "criminal_term":
            raise FileNotFoundError(folder + "/meta.json")
        required = "best.pt" if folder == "criminal_term" else ("index.joblib" if folder.startswith("retrieval_") else "model.joblib")
        if not (args.output / folder / required).is_file():
            raise FileNotFoundError(folder + "/" + required)
    (args.output / "smoke-revision.json").write_text(json.dumps({**spec, "revision": revision}, indent=2))
    print("Downloaded immutable HF revision:", revision)


if __name__ == "__main__":
    main()
