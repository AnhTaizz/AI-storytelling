"""Append public Syosetu episodes to the local Angel Next Door web-novel corpus.

Run with --apply to download missing chapters. Existing text is never replaced.
The historical 30-chapter corpus and tracked source manifest remain unchanged.
The new raw files use UTF-8, title + main body, with author notes in sidecars.
Source HTML and checkpoints are saved under .local/web_novel_ingest/n8440fe/.
syosetu_local/ holds the chapter index, provenance and completion reports.
The generated LIGHT_NOVEL_SOURCE_MANIFEST_LATEST_LOCAL.json is compatible with
light_novel_adapter_v0.py using --source-root data/sample/otonari_no_tenshi/wn_jp.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "https://ncode.syosetu.com/n8440fe/"
CORPUS = ROOT / "data/sample/otonari_no_tenshi/wn_jp"
STAGING = ROOT / ".local/web_novel_ingest/n8440fe"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def save_json(path, data):
    atomic(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def has(self, cls):
        return cls in self.attrs.get("class", "").split()

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self):
        if self.tag in {"rt", "rp", "script", "style"}:
            return ""
        if self.tag == "br":
            return "\n"
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)


class Document(HTMLParser):
    def __init__(self, data):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(data.decode("utf-8", errors="strict"))
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def one(nodes, label):
    if len(nodes) != 1:
        raise ValueError(f"expected exactly one {label}, got {len(nodes)}")
    return nodes[0]


def parse_index(body, page_url):
    nodes = list(Document(body).root.walk())
    one([n for n in nodes if n.tag == "h1" and n.has("p-novel__title")], "series title")
    episodes, pages = {}, set()
    for n in nodes:
        if n.tag != "a":
            continue
        url = urljoin(page_url, n.attrs.get("href", ""))
        match = re.fullmatch(re.escape(SOURCE) + r"(\d+)/", url)
        if match and n.has("p-eplist__subtitle"):
            number = int(match[1]); title = n.text().strip()
            if number in episodes and episodes[number]["title"] != title:
                raise ValueError("duplicate episode identity")
            episodes[number] = {"chapter": number, "source_url": url, "title": title}
        if re.fullmatch(re.escape(SOURCE) + r"\?p=\d+", url):
            pages.add(url)
    if not episodes:
        raise ValueError("no episodes in source index")
    return episodes, pages


def paragraphs(node):
    result = [n.text().replace("\r\n", "\n").replace("\r", "\n") for n in node.walk() if n.tag == "p"]
    if not result or not any(s.strip() for s in result):
        raise ValueError("chapter body is empty or no longer contains paragraphs")
    return result


def parse_episode(body, number, expected_title):
    nodes = list(Document(body).root.walk())
    url = SOURCE + f"{number}/"
    og = one([n for n in nodes if n.tag == "meta" and n.attrs.get("property") == "og:url"], "canonical URL")
    if og.attrs.get("content") != url:
        raise ValueError("chapter canonical URL mismatch")
    title = one([n for n in nodes if n.tag == "h1" and n.has("p-novel__title")], "episode title").text().strip()
    if title != expected_title:
        raise ValueError("chapter title differs from the checked index")
    counter = one([n for n in nodes if n.has("p-novel__number")], "episode counter").text().strip()
    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)", counter)
    if not match or int(match[1]) != number or int(match[2]) < number:
        raise ValueError("chapter number mismatch")
    bodies = [n for n in nodes if n.has("js-novel-text")]
    main = one([n for n in bodies if not any("preface" in c or "afterword" in c for c in n.attrs.get("class", "").split())], "main text")
    lines = paragraphs(main)
    if any(n.tag == "img" for n in main.walk()):
        raise ValueError("inline illustration needs explicit handling; refusing to drop it")
    paratext = [{"classes": n.attrs.get("class"), "paragraphs": paragraphs(n)} for n in bodies if n is not main]
    data = (title + "\n\n" + "\n".join(lines) + "\n").encode("utf-8")
    return data, {"title": title, "chapter": number, "source_url": url, "source_total": int(match[2]),
                  "body_paragraph_count": len(lines), "paratext": paratext,
                  "extraction": "SYOSETU_BODY_V1",
                  "text_policy": "title + main-body paragraphs; author notes preserved in metadata; ruby readings omitted"}


class Fetcher:
    def __init__(self, interval=0.8):
        self.lock = threading.Lock(); self.next_request = 0.0; self.interval = interval

    def __call__(self, url):
        if not url.startswith(SOURCE) or urlsplit(url).hostname != "ncode.syosetu.com":
            raise ValueError("URL outside the requested work")
        for attempt in range(4):
            with self.lock:
                time.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + self.interval
            try:
                request = Request(url, headers={"User-Agent": "AI-storytelling-corpus-ingest/1.0"})
                with urlopen(request, timeout=45) as response:
                    if response.url != url:
                        raise ValueError("source redirected away from requested episode/index")
                    data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError("response exceeds size limit")
                return data
            except (HTTPError, URLError, TimeoutError, ConnectionError) as error:
                if isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503, 504}:
                    raise
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))


def discover(fetch):
    episodes, pending, seen = {}, {SOURCE}, set()
    while pending:
        url = min(pending); pending.remove(url)
        body = fetch(url)
        suffix = "1" if url == SOURCE else urlsplit(url).query.split("=")[-1]
        atomic(STAGING / f"index_{suffix}.html", body)
        entries, pages = parse_index(body, url)
        for number, entry in entries.items():
            if number in episodes and episodes[number] != entry:
                raise ValueError("conflicting paginated index entries")
            episodes[number] = entry
        seen.add(url); pending.update(pages - seen)
        if len(seen) > 100:
            raise ValueError("unexpected index pagination")
    if sorted(episodes) != list(range(1, max(episodes) + 1)):
        raise ValueError("source index has missing episode numbers")
    save_json(STAGING / "source_index.json", {"checked_at": datetime.now(timezone.utc).isoformat(),
                                             "index_urls": sorted(seen), "episodes": list(episodes.values())})
    return episodes


def verify_baseline():
    manifest = yaml.safe_load((CORPUS / "CORPUS_30CH_LOCAL_MANIFEST.yaml").read_text(encoding="utf-8"))
    for chapter in manifest["chapters"]:
        data = (CORPUS / "raw" / chapter["filename"]).read_bytes()
        if digest(data) != chapter["sha256"]:
            raise ValueError("historical chapter differs from frozen manifest: " + chapter["filename"])
    return manifest


def ingest_one(entry, fetch):
    number = entry["chapter"]; name = f"chapter_{number:03d}"
    destination = CORPUS / "raw" / (name + ".txt")
    sidecar = CORPUS / "syosetu_local/chapters" / (name + ".json")
    snapshot = STAGING / "chapters" / (name + ".html")
    if destination.exists():
        if not sidecar.exists() or not snapshot.exists():
            raise ValueError("existing chapter lacks crawl evidence; refusing to overwrite " + name)
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        source_bytes = snapshot.read_bytes()
        data, parsed = parse_episode(source_bytes, number, entry["title"])
        if (data != destination.read_bytes() or digest(data) != metadata["sha256"]
                or digest(source_bytes) != metadata["source_html_sha256"] or parsed["source_url"] != metadata["source_url"]):
            raise ValueError("cached chapter does not match source evidence " + name)
        return metadata
    body = fetch(entry["source_url"])
    data, metadata = parse_episode(body, number, entry["title"])
    metadata.update(sha256=digest(data), byte_size=len(data), character_count=len(data.decode("utf-8")),
                    source_html_sha256=digest(body), source_snapshot=snapshot.relative_to(ROOT).as_posix(),
                    path=f"raw/{name}.txt", fetched_at=datetime.now(timezone.utc).isoformat(),
                    provenance="PUBLIC_AUTHOR_SOURCE", rights_basis="not_evaluated")
    atomic(snapshot, body)
    save_json(sidecar, metadata)
    atomic(destination, data)
    return metadata


def finalize(episodes, baseline, newly_downloaded):
    verify_baseline()
    previous = {c["chapter_number"]: c for c in baseline["chapters"]}
    records = []
    sample = yaml.safe_load((CORPUS / "LIGHT_NOVEL_SOURCE_MANIFEST_SAMPLE_V0.yaml").read_text(encoding="utf-8"))
    sample_ids = {d["order"]: d["document_id"] for d in sample["documents"]}
    documents = []
    for number, entry in sorted(episodes.items()):
        path = CORPUS / "raw" / f"chapter_{number:03d}.txt"
        data = path.read_bytes(); text = data.decode("utf-8", errors="strict")
        if not text.strip():
            raise ValueError("empty chapter")
        metadata = dict(newly_downloaded[number]) if number not in previous else {
            **entry, "provenance": "PROJECT_OWNER_LOCAL_COPY", "source_content_revalidated": False,
            "index_title_verified": text.splitlines()[0].strip() == entry["title"],
            "historical_hash_preserved": digest(data) == previous[number]["sha256"]}
        metadata.update(chapter=number, path=path.relative_to(CORPUS).as_posix(), sha256=digest(data),
                        byte_size=len(data), character_count=len(text))
        records.append(metadata)
        documents.append({"document_id": sample_ids.get(number, "srcdoc-" + uuid.uuid5(uuid.NAMESPACE_URL, entry["source_url"]).hex),
                          "order": number, "path": metadata["path"], "expected_sha256": metadata["sha256"],
                          "editorial_label": entry["title"][:200]})
    manifest = {**{k: sample[k] for k in ["contract_version", "story_id", "stream_id", "source_language"]},
                "story_editorial_label": "Angel Next Door / Syosetu web novel / local complete source set", "documents": documents}
    save_json(CORPUS / "LIGHT_NOVEL_SOURCE_MANIFEST_LATEST_LOCAL.json", manifest)
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "source": SOURCE, "latest_chapter": max(episodes),
              "chapter_count": len(records), "added_chapters": len(newly_downloaded), "preserved_chapters": len(previous),
              "chapter_sequence_complete": True, "all_text_utf8_and_hashes_verified": True,
              "new_chapter_source_identity_and_order_verified": True, "historical_30_hashes_preserved": True,
              "total_bytes": sum(r["byte_size"] for r in records), "errors": []}
    save_json(CORPUS / "syosetu_local/CORPUS_MANIFEST.json", {"summary": report, "chapters": records})
    save_json(CORPUS / "syosetu_local/INGEST_REPORT.json", report)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["chapter", "title", "path", "source_url", "sha256", "byte_size", "provenance"], extrasaction="ignore")
    writer.writeheader(); writer.writerows(records)
    atomic(CORPUS / "syosetu_local/CHAPTERS_INDEX.csv", output.getvalue().encode("utf-8-sig"))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    baseline = verify_baseline(); fetch = Fetcher(); episodes = discover(fetch)
    original = {c["chapter_number"] for c in baseline["chapters"]}
    pending = [e for n, e in sorted(episodes.items()) if n not in original]
    print(json.dumps({"listed": len(episodes), "latest": max(episodes), "preserved": len(original), "remaining": len(pending)}), flush=True)
    if not args.apply:
        return 0
    results, errors = {}, []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(ingest_one, e, fetch): e["chapter"] for e in pending}
        for future in as_completed(futures):
            number = futures[future]
            try:
                results[number] = future.result()
                print(f"chapter {number}: verified; {len(results)}/{len(pending)}", flush=True)
            except Exception as error:
                errors.append({"chapter": number, "error": str(error)})
                print(f"chapter {number}: ERROR {error}", flush=True)
            save_json(STAGING / "batch_report.json", {"complete_chapters": sorted(results), "errors": errors, "target_latest": max(episodes)})
    if errors:
        return 1
    current = discover(fetch)
    if current != episodes:
        raise ValueError("source index changed during crawl; rerun to include the new episodes")
    report = finalize(episodes, baseline, results)
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
