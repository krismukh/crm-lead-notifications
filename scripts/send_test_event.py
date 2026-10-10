"""Post a sample Close webhook event to the receiver.

Examples
    # deployed endpoint, with FUNCTION_URL and FUNCTION_KEY taken from .env
    python scripts/send_test_event.py --sample 2

    # same, but with a fresh lead_id so a new source file and message are created
    python scripts/send_test_event.py --url "..." --sample 2 --fresh

    # signed, for when VERIFY_SIGNATURE=true (key from .env or --key)
    python scripts/send_test_event.py --url "..." --sample 1 --sign

    # local host started with `func start` in src/
    python scripts/send_test_event.py --url http://localhost:7071/api/crm --sample 2
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "docs" / "samples"
sys.path.insert(0, str(REPO_ROOT / "src"))

from leadflow.verify import compute_signature  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url",
        default=None,
        help="receiver URL; defaults to FUNCTION_URL from .env, with FUNCTION_KEY appended",
    )
    parser.add_argument("--sample", choices=["1", "2"], default="2")
    parser.add_argument(
        "--fresh", action="store_true", help="replace lead_id and event id with new values"
    )
    parser.add_argument(
        "--sign",
        action="store_true",
        help="add Close-Sig headers using CLOSE_WEBHOOK_SIGNATURE_KEY",
    )
    parser.add_argument("--key", help="signature key (hex); overrides the environment")
    parser.add_argument("--action", default=None, help="override event.action, e.g. updated")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    url = args.url or os.environ.get("FUNCTION_URL", "")
    if not url:
        print("No URL: pass --url or set FUNCTION_URL in .env", file=sys.stderr)
        return 2
    key = os.environ.get("FUNCTION_KEY", "")
    if key and "code=" not in url:
        url += ("&" if "?" in url else "?") + "code=" + key
    event = json.loads(
        (SAMPLES / f"webhook_body_sample_{args.sample}.json").read_text(encoding="utf-8")
    )

    if args.fresh:
        suffix = secrets.token_hex(8)
        new_id = f"lead_test{suffix}"
        ev = event["event"]
        ev["lead_id"] = ev["object_id"] = ev["data"]["id"] = new_id
        ev["id"] = f"ev_test{suffix}"
        ev["data"]["display_name"] = f"Test Lead {suffix[:6]}"
    if args.action:
        event["event"]["action"] = args.action

    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Close Webhooks 2.0 (test)"}

    if args.sign:
        sig_key = args.key or os.environ.get("CLOSE_WEBHOOK_SIGNATURE_KEY", "")
        if not sig_key:
            print(
                "No signature key: pass --key or set CLOSE_WEBHOOK_SIGNATURE_KEY", file=sys.stderr
            )
            return 2
        ts = str(int(time.time()))
        headers["Close-Sig-Timestamp"] = ts
        headers["Close-Sig-Hash"] = compute_signature(sig_key, ts, body)

    print(f"POST {url.split('?')[0]}  lead_id={event['event']['lead_id']}  signed={args.sign}")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, text = response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        print(f"Could not reach the receiver: {exc.reason}", file=sys.stderr)
        return 1
    elapsed = int((time.perf_counter() - started) * 1000)
    print(f"HTTP {status} in {elapsed} ms")
    print(text)
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
