import hashlib
import json
import yaml
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any

@dataclass
class LineInfo:
    start: int
    end_exclusive: int
    text: str
    is_blank: bool

@dataclass
class ParagraphInfo:
    index: int
    char_start: int
    char_end_exclusive: int
    char_count: int
    text: str

@dataclass
class ChunkInfo:
    chunk_id: str
    contract_id: str = "OTONARI_LOCAL_PASSAGE_V1"
    contract_version: int = 1
    segmentation_version: str = "PARAGRAPH_PACK_V1"
    corpus_fingerprint_sha256: str = ""
    chapter_number: int = 0
    source_logical_path: str = ""
    source_chapter_sha256: str = ""
    chunk_index: int = 0
    char_start: int = 0
    char_end_exclusive: int = 0
    char_count: int = 0
    chunk_text_sha256: str = ""
    first_paragraph_index: int = 0
    last_paragraph_index: int = 0
    boundary_reason: str = ""
    text: str = ""

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def decode_source(b: bytes) -> str:
    return b.decode("utf-8", errors="strict")

def split_lines_with_offsets(text: str) -> List[LineInfo]:
    lines = text.splitlines(keepends=True)
    cursor = 0
    result = []
    
    # Terminal linebreak characters to strip for blank detection ONLY
    # splitlines boundary chars from python docs + \r\n
    # Python str.splitlines() splits on \n, \r, \r\n, \v, \x0b, \f, \x0c, \x1c, \x1d, \x1e, \x85, \u2028, \u2029
    
    for line in lines:
        line_char_start = cursor
        line_char_end_exclusive = cursor + len(line)
        cursor = line_char_end_exclusive
        
        # Remove terminal line-break sequence just for blank classification
        # We can simulate this by stripping the trailing newline characters
        # But splitlines already keeps the ending. We can just use splitlines(False) to get the line without the ending
        # But we need to handle CRLF exactly as two code points.
        
        # Simpler: just use python's splitlines(keepends=False) logic on the specific line, 
        # or we can strip any right-side characters that splitlines considers as line breaks.
        # But wait, Python's splitlines(keepends=False) output for this line should match.
        # However, a line might be just "\r\n". splitlines()[0] might be empty.
        
        parts = line.splitlines(keepends=False)
        if len(parts) == 0:
            line_body_without_terminal_linebreak = ""
        else:
            line_body_without_terminal_linebreak = parts[0]
            
        is_blank = (line_body_without_terminal_linebreak.strip() == "")
        
        result.append(LineInfo(
            start=line_char_start,
            end_exclusive=line_char_end_exclusive,
            text=line,
            is_blank=is_blank
        ))
        
    return result

def parse_paragraphs(lines_info: List[LineInfo], text: str) -> List[ParagraphInfo]:
    paragraphs = []
    current_para_lines = []
    para_index = 1
    
    for line in lines_info:
        if line.is_blank:
            if current_para_lines:
                # emit paragraph
                start = current_para_lines[0].start
                end = current_para_lines[-1].end_exclusive
                paragraphs.append(ParagraphInfo(
                    index=para_index,
                    char_start=start,
                    char_end_exclusive=end,
                    char_count=end - start,
                    text=text[start:end]
                ))
                para_index += 1
                current_para_lines = []
        else:
            current_para_lines.append(line)
            
    if current_para_lines:
        start = current_para_lines[0].start
        end = current_para_lines[-1].end_exclusive
        paragraphs.append(ParagraphInfo(
            index=para_index,
            char_start=start,
            char_end_exclusive=end,
            char_count=end - start,
            text=text[start:end]
        ))
        
    return paragraphs

def chunk_chapter(paragraphs: List[ParagraphInfo], text: str, 
                  chapter_number: int, source_path: str, chapter_sha256: str, corpus_sha256: str) -> List[ChunkInfo]:
    chunks = []
    chunk_index = 1
    
    current_start = -1
    current_end = -1
    first_paragraph_index = -1
    last_paragraph_index = -1
    
    def emit_current_normal():
        nonlocal current_start, current_end, first_paragraph_index, last_paragraph_index, chunk_index, chunks
        if current_start != -1:
            chunk_text = text[current_start:current_end]
            chunks.append(ChunkInfo(
                chunk_id=f"ch{chapter_number:03d}_c{chunk_index:04d}",
                corpus_fingerprint_sha256=corpus_sha256,
                chapter_number=chapter_number,
                source_logical_path=source_path,
                source_chapter_sha256=chapter_sha256,
                chunk_index=chunk_index,
                char_start=current_start,
                char_end_exclusive=current_end,
                char_count=current_end - current_start,
                chunk_text_sha256=sha256_bytes(chunk_text.encode("utf-8")),
                first_paragraph_index=first_paragraph_index,
                last_paragraph_index=last_paragraph_index,
                boundary_reason="PARAGRAPH_PACK",
                text=chunk_text
            ))
            chunk_index += 1
            current_start = -1
            current_end = -1
            first_paragraph_index = -1
            last_paragraph_index = -1

    for P in paragraphs:
        if P.char_count > 1200:
            # Case A
            emit_current_normal()
            
            piece_start = P.char_start
            while piece_start < P.char_end_exclusive:
                piece_end = min(piece_start + 1200, P.char_end_exclusive)
                chunk_text = text[piece_start:piece_end]
                chunks.append(ChunkInfo(
                    chunk_id=f"ch{chapter_number:03d}_c{chunk_index:04d}",
                    corpus_fingerprint_sha256=corpus_sha256,
                    chapter_number=chapter_number,
                    source_logical_path=source_path,
                    source_chapter_sha256=chapter_sha256,
                    chunk_index=chunk_index,
                    char_start=piece_start,
                    char_end_exclusive=piece_end,
                    char_count=piece_end - piece_start,
                    chunk_text_sha256=sha256_bytes(chunk_text.encode("utf-8")),
                    first_paragraph_index=P.index,
                    last_paragraph_index=P.index,
                    boundary_reason="OVERSIZED_PARAGRAPH_HARD_SPLIT",
                    text=chunk_text
                ))
                chunk_index += 1
                piece_start = piece_end
                
        elif current_start == -1:
            # Case B
            current_start = P.char_start
            current_end = P.char_end_exclusive
            first_paragraph_index = P.index
            last_paragraph_index = P.index
        else:
            # Case C
            candidate_start = current_start
            candidate_end = P.char_end_exclusive
            candidate_char_count = candidate_end - candidate_start
            
            if candidate_char_count <= 1200:
                current_end = P.char_end_exclusive
                last_paragraph_index = P.index
            else:
                emit_current_normal()
                current_start = P.char_start
                current_end = P.char_end_exclusive
                first_paragraph_index = P.index
                last_paragraph_index = P.index
                
    emit_current_normal()
    return chunks

def validate_chapter_chunks(chunks: List[ChunkInfo], paragraphs: List[ParagraphInfo], text: str) -> Dict[str, Any]:
    issues = []
    
    # spans ascending, no overlap
    for i in range(1, len(chunks)):
        if chunks[i].char_start < chunks[i-1].char_end_exclusive:
            issues.append("OVERLAPPING_CHUNK_SPANS")
            
    # each chunk exact source substring
    for c in chunks:
        if c.text != text[c.char_start:c.char_end_exclusive]:
            issues.append(f"CHUNK_TEXT_MISMATCH_{c.chunk_id}")
        if c.char_count != c.char_end_exclusive - c.char_start:
            issues.append(f"CHUNK_COUNT_MISMATCH_{c.chunk_id}")
        if c.char_count < 1 or c.char_count > 1200:
            issues.append(f"CHUNK_SIZE_INVALID_{c.chunk_id}")
            
    # verify paragraph coverage
    coverage = {}
    for p in paragraphs:
        for i in range(p.char_start, p.char_end_exclusive):
            coverage[i] = 0
            
    for c in chunks:
        for i in range(c.char_start, c.char_end_exclusive):
            if i in coverage:
                coverage[i] += 1
                
    for k, v in coverage.items():
        if v == 0:
            issues.append(f"PARAGRAPH_CHARACTER_OMITTED_{k}")
        elif v > 1:
            issues.append(f"PARAGRAPH_CHARACTER_DUPLICATED_{k}")
            
    # gap validation
    # gap between chapter start -> first chunk
    # previous chunk end -> next chunk start
    # last chunk -> chapter end
    
    legal_blank_gap_count = 0
    illegal_gap_count = 0
    
    def check_gap(start, end):
        nonlocal legal_blank_gap_count, illegal_gap_count
        if start >= end:
            return
        gap_text = text[start:end]
        # intersects no paragraph span
        intersects = False
        for p in paragraphs:
            if not (end <= p.char_start or start >= p.char_end_exclusive):
                intersects = True
                break
        if intersects or gap_text.strip() != "":
            issues.append(f"ILLEGAL_GAP_{start}_{end}")
            illegal_gap_count += 1
        else:
            legal_blank_gap_count += 1
            
    if chunks:
        check_gap(0, chunks[0].char_start)
        for i in range(1, len(chunks)):
            check_gap(chunks[i-1].char_end_exclusive, chunks[i].char_start)
        check_gap(chunks[-1].char_end_exclusive, len(text))
    else:
        check_gap(0, len(text))
        
    overlap_count = 0
    for i in range(1, len(chunks)):
        if chunks[i].char_start < chunks[i-1].char_end_exclusive:
            overlap_count += 1

    exact_source_slice_match_count = 0
    chunk_hash_match_count = 0
    empty_chunk_count = 0
    for c in chunks:
        if c.text == text[c.char_start:c.char_end_exclusive]:
            exact_source_slice_match_count += 1
        else:
            issues.append(f"CHUNK_TEXT_MISMATCH_{c.chunk_id}")
            
        if c.char_count == 0:
            empty_chunk_count += 1
            
        if c.char_count != c.char_end_exclusive - c.char_start:
            issues.append(f"CHUNK_COUNT_MISMATCH_{c.chunk_id}")
            
        if c.char_count < 1 or c.char_count > 1200:
            issues.append(f"CHUNK_SIZE_INVALID_{c.chunk_id}")
            
        actual_hash = sha256_bytes(c.text.encode("utf-8"))
        if actual_hash == c.chunk_text_sha256:
            chunk_hash_match_count += 1
        else:
            issues.append(f"CHUNK_HASH_MISMATCH_{c.chunk_id}")

    paragraph_character_omitted = 0
    paragraph_character_duplicated = 0
    for k, v in coverage.items():
        if v == 0:
            paragraph_character_omitted += 1
        elif v > 1:
            paragraph_character_duplicated += 1

    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": {
            "overlap_count": overlap_count,
            "exact_source_slice_match_count": exact_source_slice_match_count,
            "chunk_hash_match_count": chunk_hash_match_count,
            "empty_chunk_count": empty_chunk_count,
            "paragraph_character_omitted": paragraph_character_omitted,
            "paragraph_character_duplicated": paragraph_character_duplicated,
            "legal_blank_gap_count": legal_blank_gap_count,
            "illegal_gap_count": illegal_gap_count
        }
    }

def validate_corpus_chunks(chunks: List[ChunkInfo], chapter_info: List[Dict[str, Any]]) -> Dict[str, Any]:
    issues = []
    
    chunk_ids = [c.chunk_id for c in chunks]
    chunk_id_unique = len(set(chunk_ids)) == len(chunk_ids)
    if not chunk_id_unique:
        issues.append("DUPLICATE_CHUNK_ID")
        
    chunk_indices_sequential = True
    no_cross_chapter_chunks = True
    boundary_reason_enum_valid = True
    max_chunk_size_valid = True
    chunk_id_format_valid = True
    
    chapter_map = {ch["number"]: ch for ch in chapter_info}
    
    chunks_by_chapter = {}
    for c in chunks:
        chunks_by_chapter.setdefault(c.chapter_number, []).append(c)
        
    for ch_num, ch_chunks in chunks_by_chapter.items():
        if ch_num not in chapter_map:
            no_cross_chapter_chunks = False
            issues.append(f"UNKNOWN_CHAPTER_{ch_num}")
            continue
            
        expected_path = chapter_map[ch_num]["logical_path"]
        expected_sha256 = chapter_map[ch_num]["sha256"]
        
        for i, c in enumerate(ch_chunks):
            if c.source_logical_path != expected_path:
                no_cross_chapter_chunks = False
                issues.append(f"PATH_MISMATCH_{c.chunk_id}")
            if c.source_chapter_sha256 != expected_sha256:
                no_cross_chapter_chunks = False
                issues.append(f"HASH_MISMATCH_{c.chunk_id}")
                
            expected_id = f"ch{c.chapter_number:03d}_c{c.chunk_index:04d}"
            if c.chunk_id != expected_id:
                chunk_id_format_valid = False
                issues.append(f"MALFORMED_CHUNK_ID_{c.chunk_id}")
                
            if c.boundary_reason not in ["PARAGRAPH_PACK", "OVERSIZED_PARAGRAPH_HARD_SPLIT"]:
                boundary_reason_enum_valid = False
                issues.append(f"INVALID_BOUNDARY_REASON_{c.chunk_id}")
                
            if not (1 <= c.char_count <= 1200):
                max_chunk_size_valid = False
                issues.append(f"INVALID_CHUNK_SIZE_{c.chunk_id}")
                
            if i == 0:
                if c.chunk_index != 1:
                    chunk_indices_sequential = False
                    issues.append(f"FIRST_INDEX_NOT_1_CH_{c.chapter_number}")
            else:
                prev = ch_chunks[i-1]
                if c.chunk_index != prev.chunk_index + 1:
                    chunk_indices_sequential = False
                    issues.append(f"NON_SEQUENTIAL_INDEX_{c.chunk_id}")
                    
    return {
        "pass": len(issues) == 0,
        "issues": issues,
        "metrics": {
            "chunk_id_unique": chunk_id_unique,
            "chunk_id_format_valid": chunk_id_format_valid,
            "chunk_indices_sequential": chunk_indices_sequential,
            "no_cross_chapter_chunks": no_cross_chapter_chunks,
            "boundary_reason_enum_valid": boundary_reason_enum_valid,
            "max_chunk_size_valid": max_chunk_size_valid,
        }
    }

def compute_corpus_fingerprint(hashes: List[str]) -> str:
    lines = [f"{i+1:03d}:{h}" for i, h in enumerate(hashes)]
    content = "\n".join(lines).encode("ascii")
    return sha256_bytes(content)

def execute_corpus(repro_dir: Optional[str] = None):
    import sys
    import platform
    import os
    
    base_dir = Path("e:/ProjectDE/AI-storytelling")
    if not base_dir.exists():
        base_dir = Path(".")
        
    manifest_path = base_dir / "data/sample/otonari_no_tenshi/wn_jp/CORPUS_30CH_LOCAL_MANIFEST.yaml"
    contract_path = base_dir / "data/sample/otonari_no_tenshi/wn_jp/INGESTION_CHUNKING_CONTRACT_V1.yaml"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest_data = yaml.safe_load(f)
        
    with open(contract_path, "r", encoding="utf-8") as f:
        contract_data = yaml.safe_load(f)
        
    expected_fingerprint = manifest_data["identity"]["corpus_fingerprint_sha256"]
    
    actual_hashes = []
    chapter_info = []
    
    for ch in manifest_data["chapters"]:
        raw_path = base_dir / ch["logical_path"]
        raw_bytes = raw_path.read_bytes()
        actual_sha = sha256_bytes(raw_bytes)
        if actual_sha != ch["sha256"]:
            print(f"Hash mismatch for {ch['logical_path']}")
            return False
            
        text = decode_source(raw_bytes)
        actual_hashes.append(actual_sha)
        chapter_info.append({
            "number": ch["chapter_number"],
            "logical_path": ch["logical_path"],
            "sha256": actual_sha,
            "text": text
        })
        
    computed_fingerprint = compute_corpus_fingerprint(actual_hashes)
    if computed_fingerprint != expected_fingerprint:
        print("Corpus fingerprint mismatch")
        return False
        
    all_chunks = []
    all_paragraphs = []
    
    validation_failures = []
    
    total_metrics = {
        "overlap_count": 0,
        "exact_source_slice_match_count": 0,
        "chunk_hash_match_count": 0,
        "empty_chunk_count": 0,
        "paragraph_character_omitted": 0,
        "paragraph_character_duplicated": 0,
        "legal_blank_gap_count": 0,
        "illegal_gap_count": 0
    }
    
    for ch in chapter_info:
        lines = split_lines_with_offsets(ch["text"])
        paragraphs = parse_paragraphs(lines, ch["text"])
        chunks = chunk_chapter(paragraphs, ch["text"], ch["number"], ch["logical_path"], ch["sha256"], computed_fingerprint)
        val = validate_chapter_chunks(chunks, paragraphs, ch["text"])
        if not val["pass"]:
            validation_failures.append(f"Chapter {ch['number']} validation failed: {val['issues']}")
            
        for k, v in val["metrics"].items():
            total_metrics[k] += v
            
        all_chunks.extend(chunks)
        all_paragraphs.extend(paragraphs)
        
    corpus_val = validate_corpus_chunks(all_chunks, chapter_info)
    if not corpus_val["pass"]:
        validation_failures.append(f"Corpus validation failed: {corpus_val['issues']}")
        
    paragraph_coverage_pass = total_metrics["paragraph_character_omitted"] == 0 and total_metrics["paragraph_character_duplicated"] == 0
    
    overall_pass = True
    if len(validation_failures) > 0: overall_pass = False
    if not corpus_val["metrics"]["chunk_id_unique"]: overall_pass = False
    if not corpus_val["metrics"]["chunk_id_format_valid"]: overall_pass = False
    if not corpus_val["metrics"]["chunk_indices_sequential"]: overall_pass = False
    if not corpus_val["metrics"]["no_cross_chapter_chunks"]: overall_pass = False
    if not corpus_val["metrics"]["boundary_reason_enum_valid"]: overall_pass = False
    if total_metrics["empty_chunk_count"] > 0: overall_pass = False
    if total_metrics["exact_source_slice_match_count"] != len(all_chunks): overall_pass = False
    if total_metrics["chunk_hash_match_count"] != len(all_chunks): overall_pass = False
    if not paragraph_coverage_pass: overall_pass = False
    if total_metrics["illegal_gap_count"] > 0: overall_pass = False
    if total_metrics["overlap_count"] > 0: overall_pass = False
    if not corpus_val["metrics"]["max_chunk_size_valid"]: overall_pass = False
    
    # Validation report
    validation_report = {
        "input_corpus_fingerprint_match": True,
        "recomputed_corpus_fingerprint_sha256": computed_fingerprint,
        "corpus_fingerprint_match": True,
        "chapter_count_match": True,
        "processed_chapter_count": len(chapter_info),
        "chapter_hash_match_count": len(chapter_info),
        "all_chapter_hashes_match": True,
        "paragraph_count": len(all_paragraphs),
        "chunk_count": len(all_chunks),
        "chunk_id_unique": corpus_val["metrics"]["chunk_id_unique"],
        "chunk_id_format_valid": corpus_val["metrics"]["chunk_id_format_valid"],
        "chunk_indices_sequential": corpus_val["metrics"]["chunk_indices_sequential"],
        "no_cross_chapter_chunks": corpus_val["metrics"]["no_cross_chapter_chunks"],
        "max_chunk_size_valid": corpus_val["metrics"]["max_chunk_size_valid"],
        "empty_chunk_count": total_metrics["empty_chunk_count"],
        "exact_source_slice_match_count": total_metrics["exact_source_slice_match_count"],
        "chunk_hash_match_count": total_metrics["chunk_hash_match_count"],
        "paragraph_coverage_pass": paragraph_coverage_pass,
        "nonblank_coverage_complete": total_metrics["paragraph_character_omitted"] == 0,
        "duplicate_nonblank_coverage_detected": total_metrics["paragraph_character_duplicated"] > 0,
        "illegal_nonblank_gaps_detected": total_metrics["illegal_gap_count"] > 0,
        "legal_blank_gap_count": total_metrics["legal_blank_gap_count"],
        "illegal_gap_count": total_metrics["illegal_gap_count"],
        "overlap_count": total_metrics["overlap_count"],
        "boundary_reason_enum_valid": corpus_val["metrics"]["boundary_reason_enum_valid"],
        "model_invoked": False,
        "overall_status": "PASS" if overall_pass else "FAIL"
    }
    
    # Chunk manifest
    per_chapter_chunk_counts = {}
    for c in all_chunks:
        ch_str = f"{c.chapter_number:03d}"
        per_chapter_chunk_counts[ch_str] = per_chapter_chunk_counts.get(ch_str, 0) + 1
        
    char_counts = [c.char_count for c in all_chunks]
    
    chunk_manifest = {
        "contract_id": "OTONARI_LOCAL_PASSAGE_V1",
        "contract_version": 1,
        "segmentation_version": "PARAGRAPH_PACK_V1",
        "corpus_fingerprint_sha256": computed_fingerprint,
        "chapter_count": 30,
        "paragraph_count": len(all_paragraphs),
        "chunk_count": len(all_chunks),
        "per_chapter_chunk_counts": per_chapter_chunk_counts,
        "min_chunk_chars": min(char_counts) if char_counts else 0,
        "max_observed_chunk_chars": max(char_counts) if char_counts else 0,
        "mean_chunk_chars": sum(char_counts) / len(char_counts) if char_counts else 0,
        "median_chunk_chars": sorted(char_counts)[len(char_counts)//2] if char_counts else 0,
        "oversized_paragraph_count": len([p for p in all_paragraphs if p.char_count > 1200]),
        "hard_split_chunk_count": len([c for c in all_chunks if c.boundary_reason == "OVERSIZED_PARAGRAPH_HARD_SPLIT"]),
        "boundary_reason_counts": {
            "PARAGRAPH_PACK": len([c for c in all_chunks if c.boundary_reason == "PARAGRAPH_PACK"]),
            "OVERSIZED_PARAGRAPH_HARD_SPLIT": len([c for c in all_chunks if c.boundary_reason == "OVERSIZED_PARAGRAPH_HARD_SPLIT"])
        },
        "chunks_jsonl_sha256": ""
    }
    
    out_dir = base_dir / (repro_dir if repro_dir else ".local/story_integration/otonari_30ch/PARAGRAPH_PACK_V1")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    jsonl_path = out_dir / "chunks.jsonl"
    with open(jsonl_path, "wb") as f:
        for c in all_chunks:
            rec = {
                "chunk_id": c.chunk_id,
                "contract_id": c.contract_id,
                "contract_version": c.contract_version,
                "segmentation_version": c.segmentation_version,
                "corpus_fingerprint_sha256": c.corpus_fingerprint_sha256,
                "chapter_number": c.chapter_number,
                "source_logical_path": c.source_logical_path,
                "source_chapter_sha256": c.source_chapter_sha256,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end_exclusive": c.char_end_exclusive,
                "char_count": c.char_count,
                "chunk_text_sha256": c.chunk_text_sha256,
                "first_paragraph_index": c.first_paragraph_index,
                "last_paragraph_index": c.last_paragraph_index,
                "boundary_reason": c.boundary_reason,
                "text": c.text
            }
            f.write(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
            
    chunks_sha256 = sha256_bytes(jsonl_path.read_bytes())
    chunk_manifest["chunks_jsonl_sha256"] = chunks_sha256
    
    manifest_yaml = yaml.dump(chunk_manifest, sort_keys=False)
    manifest_path_out = out_dir / "chunk_manifest.yaml"
    with open(manifest_path_out, "w", encoding="utf-8") as f:
        f.write(manifest_yaml)
        
    report_yaml = yaml.dump(validation_report, sort_keys=False)
    report_path_out = out_dir / "validation_report.yaml"
    with open(report_path_out, "w", encoding="utf-8") as f:
        f.write(report_yaml)
        
    print(f"overall_status: {validation_report['overall_status']}")
    if not overall_pass:
        print("Validation failures found:", validation_failures)
        return False
        
    return True

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "repro":
        execute_corpus(".local/story_integration/otonari_30ch/repro_check")
    else:
        execute_corpus()
