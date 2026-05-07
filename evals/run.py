import json
import asyncio
from pathlib import Path

from app.tools.classify_rounds import classify_rounds

GOLDEN_DIR = Path(__file__).parent / "golden"


async def run_evals():
    results = []
    for f in sorted(GOLDEN_DIR.glob("*.json")):
        case = json.loads(f.read_text())
        predicted = await classify_rounds(case["jd"])
        expected = set(case["expected"])
        got = set(predicted)
        passed = expected.issubset(got)
        results.append((f.stem, passed, expected, got))
    return results


if __name__ == "__main__":
    results = asyncio.run(run_evals())
    ok = all(r[1] for r in results)
    for name, passed, expected, got in results:
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name}: expected={expected} got={got}")
    exit(0 if ok else 1)
